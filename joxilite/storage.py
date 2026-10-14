from __future__ import annotations
import copy
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime
from pathlib import Path


def data_directory():
    if sys.platform == "darwin":
        return Path.home()/"Library/Application Support/JoxiLite"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home()/"AppData/Local"))/"JoxiLite"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home()/".local/share"))/"JoxiLite"


def defaults():
    return {"version": 1, "capture_keys": {"area": "Meta+Shift+2" if sys.platform == "darwin" else "Ctrl+Alt+2",
            "window": "Ctrl+Alt+3", "screen": "Ctrl+Alt+4", "delayed": "Ctrl+Alt+5"},
            "tool_keys": dict(zip(("arrow", "rectangle", "ellipse", "line", "pen", "text", "pixelate", "crop"), "12345678")),
            "close_on_escape": True, "confirm_unsaved": True, "include_cursor": False,
            "history_dir": str(data_directory()/"History"), "history_limit_mb": 100,
            "toolbar_position": None}


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".joxilite-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def validate(settings):
    from PySide6.QtGui import QKeySequence
    all_capture = []
    for action, value in settings["capture_keys"].items():
        if not value:
            continue
        seq = QKeySequence(value)
        canonical = seq.toString(QKeySequence.SequenceFormat.PortableText)
        if seq.count() != 1 or not canonical or not any(m+"+" in canonical for m in ("Ctrl", "Alt", "Meta")):
            raise ValueError("Для захвата нужна одна буква/цифра с Ctrl, Alt или Cmd.")
        if len(canonical.split("+")[-1]) != 1 or not canonical.split("+")[-1].isascii() or not canonical.split("+")[-1].isalnum():
            raise ValueError("Основная клавиша захвата должна быть латинской буквой или цифрой.")
        if canonical in all_capture:
            raise ValueError("Одно сочетание назначено нескольким режимам захвата.")
        all_capture.append(canonical)
        settings["capture_keys"][action] = canonical
    keys = [k.upper() for k in settings["tool_keys"].values() if k]
    if any(len(k) != 1 or not k.isascii() or not k.isalnum() for k in keys):
        raise ValueError("Инструментам назначаются латинские буквы/цифры без модификаторов.")
    if len(keys) != len(set(keys)):
        raise ValueError("Одна клавиша назначена нескольким инструментам.")
    if not 1 <= settings["history_limit_mb"] <= 10000:
        raise ValueError("Лимит истории: от 1 до 10000 МБ.")
    if not str(settings["history_dir"]).strip():
        raise ValueError("Укажите папку истории.")
    settings["history_dir"] = str(Path(settings["history_dir"]).expanduser().absolute())


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory()/"settings.json"
        self.values = defaults()
        self.load_error = ""
        if self.path.exists():
            try:
                stored = json.loads(self.path.read_text())
                for key in self.values:
                    if key in stored:
                        if isinstance(self.values[key], dict):
                            self.values[key].update(stored[key])
                        else:
                            self.values[key] = stored[key]
                validate(self.values)
            except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
                self.values = defaults()
                self.load_error = f"Настройки не прочитаны: {error}. Используются исходные значения."
        elif sys.platform == "darwin":
            self._migrate_swift()

    def _migrate_swift(self):
        import subprocess, plistlib
        try:
            old = plistlib.loads(subprocess.check_output(["defaults", "export", "com.german.joxilite", "-"], stderr=subprocess.DEVNULL))
            for previous, current in (("closeOnEscape", "close_on_escape"), ("confirmUnsaved", "confirm_unsaved"),
                                      ("includeCursor", "include_cursor"), ("historyLimitMB", "history_limit_mb")):
                if previous in old:
                    self.values[current] = old[previous]
            from .platforms.macos import KEY_CODES
            reverse = {v:k for k,v in KEY_CODES.items()}
            for index, action in enumerate(("area", "window", "screen"), 1):
                code = old.get(f"capture.{index}.keyCode")
                if code is not None:
                    mods = old.get(f"capture.{index}.modifiers", 0)
                    names = [name for bit,name in ((256,"Meta"),(512,"Shift"),(2048,"Alt"),(4096,"Ctrl")) if mods&bit]
                    self.values["capture_keys"][action] = "+".join(names+[reverse[code]]) if code in reverse else ""
            for index, tool in enumerate(self.values["tool_keys"]):
                code = old.get(f"tool.{index}")
                if code is not None:
                    self.values["tool_keys"][tool] = reverse.get(code, "")
            validate(self.values)
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass

    def save(self, values):
        values = copy.deepcopy(values)
        validate(values)
        atomic_write(self.path, json.dumps(values, ensure_ascii=False, indent=2).encode())
        self.values = values


class HistoryStore:
    def __init__(self, directory, limit_bytes):
        self.directory = Path(directory)
        self.limit_bytes = limit_bytes

    def save(self, png):
        if len(png) > self.limit_bytes:
            raise OSError("Снимок превышает лимит истории. Увеличьте лимит в настройках.")
        name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_")+uuid.uuid4().hex[:12]+".png"
        path = self.directory/name
        atomic_write(path, png)
        self.prune(protected=path)
        return path

    def prune(self, protected=None):
        # Only managed screenshots: never delete unrelated PNGs in a user-selected folder.
        import re
        entries = []
        for path in self.directory.glob("*.png"):
            if path.is_symlink() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[a-fA-F0-9-]{8,36}\.png", path.name):
                continue
            stat = path.stat()
            entries.append((stat.st_mtime_ns, path.name, path, stat.st_size))
        total = sum(item[3] for item in entries)
        for _, _, path, size in sorted(entries):
            if total <= self.limit_bytes:
                break
            if path != protected:
                path.unlink()
                total -= size


class CopyService:
    """Clipboard commits FIRST. A history failure is a warning, not a copy failure."""
    def __init__(self, clipboard, history, close, warning, recovery=None):
        self.clipboard, self.history, self.close, self.warning = clipboard, history, close, warning
        self.recovery = recovery

    def copy(self, document, close_overlay=True):
        png = document.png()
        self.clipboard(png)  # On failure: don't mark saved, don't close, don't write history.
        try:
            self.history.save(png)
        except Exception as error:
            recovery = ""
            if self.recovery:
                try:
                    recovery = str(self.recovery(png))
                except OSError:
                    pass
            self.warning(f"Снимок скопирован. История не сохранена: {error}" +
                         (f"\nРезервная копия: {recovery}" if recovery else ""))
        document.mark_saved()
        if close_overlay:
            self.close()
        return png

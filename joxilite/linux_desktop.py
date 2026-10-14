"""User-level launcher so GNOME can identify JoxiLite when it asks for the screen."""
from __future__ import annotations
import os
import stat
import sys
from pathlib import Path
from . import APP_ID


def project_root():
    return Path(__file__).resolve().parent.parent


def ensure_user_launcher():
    if not sys.platform.startswith("linux"):
        return
    root = project_root()
    binary_dir = Path.home() / ".local/bin"
    binary_dir.mkdir(parents=True, exist_ok=True)
    launcher = binary_dir / "joxilite"
    launcher.write_text(
        "#!/bin/sh\n"
        f"cd {sh_quote(root)}\n"
        "exec python3 main.py \"$@\"\n"
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)

    applications = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    desktop = applications / f"{APP_ID}.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=JoxiLite\n"
        "Comment=Локальные снимки экрана\n"
        f"Exec={launcher} %u\n"
        f"TryExec={launcher}\n"
        "Icon=camera-photo\n"
        "Terminal=false\n"
        "Categories=Graphics;Utility;\n"
        "StartupNotify=true\n"
        f"StartupWMClass={APP_ID}\n"
    )
    autostart_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    autostart = autostart_dir / f"{APP_ID}.desktop"
    if not autostart.exists():
        autostart.write_text(desktop.read_text() + "X-GNOME-Autostart-enabled=true\n")


def sh_quote(path: Path):
    return "'" + str(path).replace("'", "'\\''") + "'"

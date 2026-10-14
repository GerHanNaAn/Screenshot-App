import ctypes as C
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage
from . import Frame

KEY_CODES = dict(zip("ASDFHGZXCVBQWERTY123465=97-80]OU[IP\nLJK;'\\,/NM.",
                    range(47)))
# Explicit ANSI table avoids layout-dependent characters and preserves Swift shortcuts.
KEY_CODES = {"A":0,"S":1,"D":2,"F":3,"H":4,"G":5,"Z":6,"X":7,"C":8,"V":9,"B":11,
             "Q":12,"W":13,"E":14,"R":15,"Y":16,"T":17,"1":18,"2":19,"3":20,"4":21,
             "6":22,"5":23,"9":25,"7":26,"8":28,"0":29,"O":31,"U":32,"I":34,"P":35,
             "L":37,"J":38,"K":40,"N":45,"M":46}


def helper_path():
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)/"MacCapture"
    return Path(__file__).resolve().parents[2]/"build/MacCapture"


class MacCapture:
    def _run(self, mode, cursor=False, window=None):
        helper = helper_path()
        if not helper.exists():
            raise RuntimeError("Не найден MacCapture. Выполните python scripts/build.py --helper.")
        with tempfile.TemporaryDirectory(prefix="JoxiLite-capture-") as directory:
            args = [str(helper), mode, directory]
            if window is not None:
                args.append(str(window))
            if cursor:
                args.append("--cursor")
            process = subprocess.run(args, capture_output=True, text=True, timeout=60)
            if process.returncode:
                raise RuntimeError(process.stderr or "ScreenCaptureKit не вернул изображение.")
            result = json.loads(process.stdout)
            if mode == "windows":
                return result
            frames = [Frame(QImage(r["path"]), QRect(round(r["x"]), round(r["y"]), round(r["width"]), round(r["height"])), r["name"]) for r in result]
            if not frames or any(f.image.isNull() for f in frames):
                raise RuntimeError("Не удалось прочитать захваченный кадр.")
            return frames

    def screens(self, cursor=False):
        return self._run("screens", cursor)

    def windows(self):
        return self._run("windows")

    def window(self, identifier, cursor=False):
        return self._run("window", cursor, identifier)[0]


class EventSpec(C.Structure):
    _fields_ = [("eventClass", C.c_uint32), ("eventKind", C.c_uint32)]


class HotkeyID(C.Structure):
    _fields_ = [("signature", C.c_uint32), ("id", C.c_uint32)]


class MacHotkeys:
    def __init__(self, callback):
        self.callback, self.refs, self.actions = callback, [], {}
        self.carbon = C.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        c = self.carbon
        c.GetApplicationEventTarget.restype = C.c_void_p
        c.RegisterEventHotKey.argtypes = [C.c_uint32,C.c_uint32,HotkeyID,C.c_void_p,C.c_uint32,C.POINTER(C.c_void_p)]
        c.UnregisterEventHotKey.argtypes = [C.c_void_p]
        c.InstallEventHandler.argtypes = [C.c_void_p,C.c_void_p,C.c_uint32,C.POINTER(EventSpec),C.c_void_p,C.POINTER(C.c_void_p)]
        c.RemoveEventHandler.argtypes = [C.c_void_p]
        c.GetEventParameter.argtypes = [C.c_void_p,C.c_uint32,C.c_uint32,C.c_void_p,C.c_size_t,C.c_void_p,C.c_void_p]
        handler_type = C.CFUNCTYPE(C.c_int32,C.c_void_p,C.c_void_p,C.c_void_p)
        def handle(_, event, __):
            identifier = HotkeyID()
            result = c.GetEventParameter(event, int.from_bytes(b"----", "big"), int.from_bytes(b"hkid", "big"), None,
                                         C.sizeof(identifier), None, C.byref(identifier))
            if result == 0 and identifier.signature == 0x4A584C54 and identifier.id in self.actions:
                self.callback(self.actions[identifier.id])
                return 0
            return -9874
        self.handler = handler_type(handle)
        spec, self.handler_ref = EventSpec(int.from_bytes(b"keyb", "big"),6), C.c_void_p()
        status = c.InstallEventHandler(c.GetApplicationEventTarget(), self.handler, 1, C.byref(spec), None, C.byref(self.handler_ref))
        if status:
            raise RuntimeError(f"Не удалось включить глобальные клавиши Carbon ({status}).")

    def register(self, keys):
        self.clear()
        errors = []
        for index,(action,key) in enumerate(keys.items(),1):
            if not key:
                continue
            parts = key.upper().split("+")
            flags = sum(value for name,value in (("META",256),("SHIFT",512),("ALT",2048),("CTRL",4096)) if name in parts)
            ref = C.c_void_p()
            result = self.carbon.RegisterEventHotKey(KEY_CODES[parts[-1]], flags, HotkeyID(0x4A584C54,index),
                                                     self.carbon.GetApplicationEventTarget(),0,C.byref(ref))
            if result:
                errors.append(f"{key}: сочетание занято или недоступно (Carbon {result}).")
            else:
                self.refs.append(ref)
                self.actions[index] = action
        return errors

    def clear(self):
        for ref in self.refs:
            self.carbon.UnregisterEventHotKey(ref)
        self.refs.clear()
        self.actions.clear()

    def close(self):
        self.clear()
        self.carbon.RemoveEventHandler(self.handler_ref)

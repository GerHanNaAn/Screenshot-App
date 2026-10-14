import asyncio
import ctypes as C
import ctypes.util
import os
from PySide6.QtCore import QSocketNotifier, QRect, QPoint
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from . import Frame


def wayland():
    return QGuiApplication.platformName().startswith("wayland")


def wayland_session():
    return bool(os.environ.get("WAYLAND_DISPLAY")) and (not QGuiApplication.platformName() or wayland())


class X11:
    def __init__(self):
        self.lib = C.CDLL(ctypes.util.find_library("X11"))
        x = self.lib
        x.XOpenDisplay.argtypes = [C.c_char_p]; x.XOpenDisplay.restype = C.c_void_p
        x.XDefaultRootWindow.argtypes = [C.c_void_p]; x.XDefaultRootWindow.restype = C.c_ulong
        x.XInternAtom.argtypes = [C.c_void_p,C.c_char_p,C.c_int]; x.XInternAtom.restype = C.c_ulong
        x.XGetWindowProperty.argtypes = [C.c_void_p,C.c_ulong,C.c_ulong,C.c_long,C.c_long,C.c_int,C.c_ulong,
                                        C.POINTER(C.c_ulong),C.POINTER(C.c_int),C.POINTER(C.c_ulong),C.POINTER(C.c_ulong),C.POINTER(C.c_void_p)]
        x.XFree.argtypes = [C.c_void_p]
        x.XCloseDisplay.argtypes = [C.c_void_p]
        self.display = x.XOpenDisplay(None)
        if not self.display: raise RuntimeError("Нет соединения с X11.")
        self.root = x.XDefaultRootWindow(self.display)

    def property(self, window, name):
        atom = self.lib.XInternAtom(self.display,name.encode(),0)
        actual,format_,count,left,data = C.c_ulong(),C.c_int(),C.c_ulong(),C.c_ulong(),C.c_void_p()
        status = self.lib.XGetWindowProperty(self.display,window,atom,0,65536,0,0,C.byref(actual),C.byref(format_),
                                             C.byref(count),C.byref(left),C.byref(data))
        if status or not data: return None
        try:
            if format_.value == 8: return C.string_at(data,count.value)
            if format_.value == 32: return list(C.cast(data,C.POINTER(C.c_ulong))[:count.value])
            return None
        finally: self.lib.XFree(data)

    def close(self):
        if self.display: self.lib.XCloseDisplay(self.display); self.display = None


class LinuxCapture:
    def screens(self, cursor=False):
        if wayland():
            from .portal import capture
            return asyncio.run(capture(cursor=cursor))
        frames = []
        for screen in QGuiApplication.screens():
            image = screen.grabWindow(0).toImage()
            if image.isNull(): raise RuntimeError("X11 не вернул изображение.")
            image.setDevicePixelRatio(1)
            frame = Frame(image,screen.geometry(),screen.name())
            if cursor: self._cursor(frame)
            frames.append(frame)
        return frames

    def _cursor(self, frame):
        class CursorImage(C.Structure):
            _fields_ = [("x",C.c_short),("y",C.c_short),("width",C.c_ushort),("height",C.c_ushort),
                        ("xhot",C.c_ushort),("yhot",C.c_ushort),("serial",C.c_ulong),("pixels",C.POINTER(C.c_ulong)),
                        ("atom",C.c_ulong),("name",C.c_char_p)]
        x = X11()
        try:
            lib = C.CDLL(ctypes.util.find_library("Xfixes"))
            lib.XFixesGetCursorImage.argtypes = [C.c_void_p]
            lib.XFixesGetCursorImage.restype = C.POINTER(CursorImage)
            ptr = lib.XFixesGetCursorImage(x.display)
            if not ptr: return
            try:
                cursor = ptr.contents
                # X11 cursor positions are device pixels. Convert origin via Qt's screen ratio.
                ratio = frame.image.width()/frame.geometry.width()
                cx = cursor.x-cursor.xhot-round(frame.geometry.x()*ratio)
                cy = cursor.y-cursor.yhot-round(frame.geometry.y()*ratio)
                raw = (C.c_uint32*(cursor.width*cursor.height))(*ptr.contents.pixels[:cursor.width*cursor.height])
                image = QImage(bytes(raw),cursor.width,cursor.height,cursor.width*4,QImage.Format.Format_ARGB32_Premultiplied).copy()
                painter = QPainter(frame.image); painter.drawImage(cx,cy,image); painter.end()
            finally: x.lib.XFree(ptr)
        finally: x.close()

    def windows(self):
        if wayland(): return [{"id":"portal","title":"Выбрать окно в системном диалоге…"}]
        x = X11()
        try:
            ids = x.property(x.root,"_NET_CLIENT_LIST_STACKING") or []
            result = []
            import os
            for identifier in reversed(ids):
                pid = x.property(identifier,"_NET_WM_PID")
                title = x.property(identifier,"_NET_WM_NAME") or x.property(identifier,"WM_NAME")
                if title and (not pid or pid[0] != os.getpid()):
                    result.append({"id":identifier,"title":title.decode(errors="replace")})
            return result
        finally: x.close()

    def window(self, identifier, cursor=False):
        if wayland():
            from .portal import capture
            return asyncio.run(capture(window=True,cursor=cursor))[0]
        # Qt/XCB captures native window pixels, including its screen's actual DPR.
        pixmap = QGuiApplication.primaryScreen().grabWindow(int(identifier))
        if pixmap.isNull(): raise RuntimeError("Окно закрыто или не разрешило захват.")
        if cursor:
            raise RuntimeError("Для снимка отдельного окна X11 отключите курсор или используйте захват области.")
        image = pixmap.toImage(); image.setDevicePixelRatio(1)
        return Frame(image,QRect(0,0,image.width(),image.height()),"Окно")


class XKeyEvent(C.Structure):
    _fields_ = [("type",C.c_int),("serial",C.c_ulong),("send",C.c_int),("display",C.c_void_p),
                ("window",C.c_ulong),("root",C.c_ulong),("subwindow",C.c_ulong),("time",C.c_ulong),
                ("x",C.c_int),("y",C.c_int),("xroot",C.c_int),("yroot",C.c_int),
                ("state",C.c_uint),("keycode",C.c_uint),("same",C.c_int)]


class XEvent(C.Union):
    _fields_ = [("key",XKeyEvent),("padding",C.c_long*24)]


class X11Hotkeys:
    def __init__(self, callback):
        self.x,self.callback,self.keys = X11(),callback,{}
        x = self.x.lib
        x.XKeysymToKeycode.argtypes = [C.c_void_p,C.c_ulong]; x.XKeysymToKeycode.restype = C.c_uint
        x.XStringToKeysym.argtypes = [C.c_char_p]; x.XStringToKeysym.restype = C.c_ulong
        x.XGrabKey.argtypes = [C.c_void_p,C.c_int,C.c_uint,C.c_ulong,C.c_int,C.c_int,C.c_int]
        x.XUngrabKey.argtypes = [C.c_void_p,C.c_int,C.c_uint,C.c_ulong]
        x.XConnectionNumber.argtypes = [C.c_void_p]
        x.XPending.argtypes = [C.c_void_p]
        x.XNextEvent.argtypes = [C.c_void_p,C.POINTER(XEvent)]
        x.XSync.argtypes = [C.c_void_p,C.c_int]
        x.XSetErrorHandler.argtypes = [C.c_void_p]; x.XSetErrorHandler.restype = C.c_void_p
        self.notifier = QSocketNotifier(x.XConnectionNumber(self.x.display),QSocketNotifier.Type.Read)
        self.notifier.activated.connect(self._events)

    def register(self, keys):
        self.clear()
        x,errors = self.x.lib,[]
        handler_type = C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_void_p)
        error_codes = []
        def error_handler(display,event):
            error_codes.append(True); return 0
        handler = handler_type(error_handler)
        old = x.XSetErrorHandler(handler)
        try:
            for action,key in keys.items():
                if not key: continue
                parts = key.upper().split("+")
                mods = sum(flag for name,flag in (("SHIFT",1),("CTRL",4),("ALT",8),("META",64)) if name in parts)
                code = x.XKeysymToKeycode(self.x.display,x.XStringToKeysym(parts[-1].lower().encode()))
                error_codes.clear()
                # NumLock and CapsLock variants must not disable a shortcut.
                for lock in (0,2,16,18): x.XGrabKey(self.x.display,code,mods|lock,self.x.root,0,1,1)
                x.XSync(self.x.display,0)
                if error_codes:
                    for lock in (0,2,16,18): x.XUngrabKey(self.x.display,code,mods|lock,self.x.root)
                    errors.append(f"{key}: сочетание занято другим приложением X11.")
                else: self.keys[(code,mods)] = action
        finally:
            x.XSetErrorHandler(old)
            x.XSync(self.x.display,0)
        return errors

    def _events(self,*args):
        x = self.x.lib
        while x.XPending(self.x.display):
            event = XEvent(); x.XNextEvent(self.x.display,C.byref(event))
            if event.key.type == 2:
                action = self.keys.get((event.key.keycode,event.key.state&~(2|16)))
                if action: self.callback(action)

    def clear(self):
        for code,mods in self.keys:
            for lock in (0,2,16,18): self.x.lib.XUngrabKey(self.x.display,code,mods|lock,self.x.root)
        self.keys.clear()
        self.x.lib.XSync(self.x.display,0)

    def close(self):
        self.clear(); self.notifier.setEnabled(False); self.x.close()


def LinuxHotkeys(callback):
    if wayland():
        from .portal import PortalHotkeys
        return PortalHotkeys(callback)
    return X11Hotkeys(callback)

"""Win32 screen/window capture and system-owned hotkey registration."""
import ctypes as C
from ctypes import wintypes as W
from PySide6.QtCore import QAbstractNativeEventFilter, QRect
from PySide6.QtGui import QGuiApplication, QImage
from . import Frame


class BitmapInfoHeader(C.Structure):
    _fields_ = [("size",W.DWORD),("width",W.LONG),("height",W.LONG),("planes",W.WORD),
                ("bits",W.WORD),("compression",W.DWORD),("imageSize",W.DWORD),("xppm",W.LONG),
                ("yppm",W.LONG),("used",W.DWORD),("important",W.DWORD)]


class CursorInfo(C.Structure):
    _fields_ = [("size",W.DWORD),("flags",W.DWORD),("cursor",W.HANDLE),("pos",W.POINT)]


class IconInfo(C.Structure):
    _fields_ = [("icon",W.BOOL),("x",W.DWORD),("y",W.DWORD),("mask",W.HANDLE),("color",W.HANDLE)]


def api():
    user, gdi = C.windll.user32, C.windll.gdi32
    for library,name,args,ret in [
        (user,"GetDC",[W.HWND],W.HDC),(user,"GetWindowDC",[W.HWND],W.HDC),
        (user,"ReleaseDC",[W.HWND,W.HDC],C.c_int),
        (gdi,"CreateCompatibleDC",[W.HDC],W.HDC),
        (gdi,"CreateCompatibleBitmap",[W.HDC,C.c_int,C.c_int],W.HBITMAP),
        (gdi,"SelectObject",[W.HDC,W.HANDLE],W.HANDLE),(gdi,"DeleteObject",[W.HANDLE],W.BOOL),
        (gdi,"DeleteDC",[W.HDC],W.BOOL),
        (gdi,"BitBlt",[W.HDC,C.c_int,C.c_int,C.c_int,C.c_int,W.HDC,C.c_int,C.c_int,W.DWORD],W.BOOL),
        (gdi,"GetDIBits",[W.HDC,W.HBITMAP,W.UINT,W.UINT,C.c_void_p,C.c_void_p,W.UINT],C.c_int),
        (user,"PrintWindow",[W.HWND,W.HDC,W.UINT],W.BOOL),
        (user,"DrawIconEx",[W.HDC,C.c_int,C.c_int,W.HANDLE,C.c_int,C.c_int,W.UINT,W.HANDLE,W.UINT],W.BOOL),
        (user,"GetIconInfo",[W.HANDLE,C.POINTER(IconInfo)],W.BOOL),
    ]:
        f = getattr(library,name)
        f.argtypes, f.restype = args, ret
    return user,gdi


class WindowsCapture:
    def _capture(self, rect, cursor, hwnd=None):
        user,gdi = api()
        width,height = rect.width(),rect.height()
        dc = user.GetDC(None)
        memory = gdi.CreateCompatibleDC(dc)
        bitmap = gdi.CreateCompatibleBitmap(dc,width,height)
        previous = gdi.SelectObject(memory,bitmap)
        try:
            if hwnd:
                # PW_RENDERFULLCONTENT supports modern DWM windows; protected windows may refuse.
                if not user.PrintWindow(hwnd,memory,2):
                    raise RuntimeError("Окно не разрешило захват. Используйте захват области.")
            elif not gdi.BitBlt(memory,0,0,width,height,dc,rect.x(),rect.y(),0x40CC0020):
                raise RuntimeError("Windows не разрешила захват экрана.")
            if cursor:
                ci,ii = CursorInfo(),IconInfo()
                ci.size = C.sizeof(ci)
                if user.GetCursorInfo(C.byref(ci)) and ci.flags&1 and user.GetIconInfo(ci.cursor,C.byref(ii)):
                    user.DrawIconEx(memory,ci.pos.x-rect.x()-ii.x,ci.pos.y-rect.y()-ii.y,ci.cursor,0,0,0,None,3)
                    if ii.mask: gdi.DeleteObject(ii.mask)
                    if ii.color: gdi.DeleteObject(ii.color)
            gdi.SelectObject(memory,previous)
            header = BitmapInfoHeader(C.sizeof(BitmapInfoHeader),width,-height,1,32,0,0,0,0,0,0)
            raw = C.create_string_buffer(width*height*4)
            if not gdi.GetDIBits(dc,bitmap,0,height,raw,C.byref(header),0):
                raise RuntimeError("Не удалось прочитать пиксели Windows.")
            image = QImage(raw.raw,width,height,width*4,QImage.Format.Format_RGB32).copy()
            return image
        finally:
            gdi.SelectObject(memory,previous)
            gdi.DeleteObject(bitmap)
            gdi.DeleteDC(memory)
            user.ReleaseDC(None,dc)

    def screens(self, cursor=False):
        user = C.windll.user32
        # EnumDisplayMonitors returns PHYSICAL rectangles under per-monitor v2 DPI awareness.
        frames = []
        class MonitorInfo(C.Structure):
            _fields_ = [("size",W.DWORD),("monitor",W.RECT),("work",W.RECT),("flags",W.DWORD),("device",W.WCHAR*32)]
        enum = C.WINFUNCTYPE(W.BOOL,W.HANDLE,W.HDC,C.POINTER(W.RECT),W.LPARAM)
        def visit(handle,dc,r,data):
            info = MonitorInfo(); info.size = C.sizeof(info)
            user.GetMonitorInfoW(handle,C.byref(info))
            physical = QRect(r.contents.left,r.contents.top,r.contents.right-r.contents.left,r.contents.bottom-r.contents.top)
            screen = next((s for s in QGuiApplication.screens() if s.name().upper()==info.device.upper()),None)
            frames.append(Frame(self._capture(physical,cursor),screen.geometry() if screen else physical,info.device))
            return True
        callback = enum(visit)
        user.EnumDisplayMonitors.argtypes = [W.HDC,C.c_void_p,enum,W.LPARAM]
        user.GetMonitorInfoW.argtypes = [W.HANDLE,C.c_void_p]
        user.EnumDisplayMonitors(None,None,callback,0)
        return frames

    def windows(self):
        user = C.windll.user32
        result = []
        enum = C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        user.IsWindowVisible.argtypes = [W.HWND]
        user.IsIconic.argtypes = [W.HWND]
        user.GetWindowTextLengthW.argtypes = [W.HWND]
        user.GetWindowTextW.argtypes = [W.HWND,W.LPWSTR,C.c_int]
        user.GetWindowThreadProcessId.argtypes = [W.HWND,C.POINTER(W.DWORD)]
        def visit(hwnd,_):
            import os
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd,C.byref(pid))
            if user.IsWindowVisible(hwnd) and not user.IsIconic(hwnd) and pid.value != os.getpid():
                length = user.GetWindowTextLengthW(hwnd)
                if length:
                    title = C.create_unicode_buffer(length+1)
                    user.GetWindowTextW(hwnd,title,length+1)
                    result.append({"id":int(hwnd),"title":title.value})
            return True
        callback = enum(visit)
        user.EnumWindows.argtypes = [enum,W.LPARAM]
        user.EnumWindows(callback,0)
        return result

    def window(self, identifier, cursor=False):
        user = C.windll.user32
        r = W.RECT()
        user.GetWindowRect.argtypes = [W.HWND,C.POINTER(W.RECT)]
        if not user.GetWindowRect(identifier,C.byref(r)):
            raise RuntimeError("Окно закрыто.")
        rect = QRect(r.left,r.top,r.right-r.left,r.bottom-r.top)
        return Frame(self._capture(rect,cursor,identifier),rect,"Окно")


class WindowsHotkeys(QAbstractNativeEventFilter):
    def __init__(self, callback):
        super().__init__()
        self.callback, self.actions = callback, {}
        self.user = C.windll.user32
        self.user.RegisterHotKey.argtypes = [W.HWND,C.c_int,W.UINT,W.UINT]
        self.user.UnregisterHotKey.argtypes = [W.HWND,C.c_int]
        QGuiApplication.instance().installNativeEventFilter(self)

    def register(self, keys):
        self.clear()
        errors = []
        for index,(action,key) in enumerate(keys.items(),1):
            if not key: continue
            parts = key.upper().split("+")
            mods = 0x4000|sum(flag for name,flag in (("ALT",1),("CTRL",2),("SHIFT",4),("META",8)) if name in parts)
            if not self.user.RegisterHotKey(None,index,mods,ord(parts[-1])):
                errors.append(f"{key}: сочетание занято другим приложением (Windows {C.GetLastError()}).")
            else:
                self.actions[index] = action
        return errors

    def nativeEventFilter(self, event_type, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == 0x0312 and msg.wParam in self.actions:
            self.callback(self.actions[msg.wParam])
            return True,0
        return False,0

    def clear(self):
        for index in self.actions:
            self.user.UnregisterHotKey(None,index)
        self.actions.clear()

    def close(self):
        self.clear()
        QGuiApplication.instance().removeNativeEventFilter(self)

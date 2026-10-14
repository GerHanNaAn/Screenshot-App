from __future__ import annotations
import sys
from dataclasses import dataclass
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage


@dataclass
class Frame:
    image: QImage
    geometry: QRect
    name: str = ""


def capture_backend():
    if sys.platform == "darwin":
        from .macos import MacCapture
        return MacCapture()
    if sys.platform == "win32":
        from .windows import WindowsCapture
        return WindowsCapture()
    from .linux import LinuxCapture
    return LinuxCapture()


def hotkey_backend(callback):
    if sys.platform == "darwin":
        from .macos import MacHotkeys
        return MacHotkeys(callback)
    if sys.platform == "win32":
        from .windows import WindowsHotkeys
        return WindowsHotkeys(callback)
    from .linux import LinuxHotkeys
    return LinuxHotkeys(callback)

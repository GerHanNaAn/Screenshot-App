from __future__ import annotations
from pathlib import Path
import sys
from PySide6.QtCore import QEvent, QPoint, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget
from .canvas import Canvas
from .platforms.linux import wayland_session
from .storage import CopyService, HistoryStore, atomic_write, data_directory
from .toolbar import Toolbar


class Editor(QWidget):
    closed = Signal(object)
    becameActive = Signal(object)
    def __init__(self,document,settings,overlay=False,geometry=None,copy_warning=None):
        linux = sys.platform.startswith("linux")
        # A Tool window on GNOME Wayland does not take keyboard focus, so Esc and shortcuts never arrive.
        flags = Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint if overlay else Qt.WindowType.Window
        if overlay and not linux:
            flags |= Qt.WindowType.Tool
        super().__init__(None,flags)
        self.document,self.settings,self.overlay = document,settings,overlay
        self.allow_close=False; self._closed=False
        self.warning_callback=copy_warning or self.warning
        self.setWindowTitle("JoxiLite — Выделение области" if overlay else "JoxiLite — Редактор")
        self.canvas=Canvas(document,overlay,self)
        if overlay:
            self._wayland_overlay = linux and wayland_session()
            if self._wayland_overlay: self.resize(geometry.size())
            else: self.setGeometry(geometry)
            self.canvas.setGeometry(self.rect())
            self.toolbar=Toolbar(self.canvas.style,settings.values["tool_keys"],self)
            self.toolbar.hide()
        else:
            self.resize(1100,760)
            layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
            header=QHBoxLayout(); header.setContentsMargins(12,6,12,6)
            header.addWidget(QLabel("JoxiLite · локальный редактор")); header.addStretch()
            fit=QPushButton("Вписать"); fit.clicked.connect(self.fit); header.addWidget(fit)
            header.addWidget(QLabel("Масштаб")); zoom=QSlider(Qt.Orientation.Horizontal); zoom.setRange(10,400); zoom.setValue(100); zoom.setFixedWidth(150)
            zoom.valueChanged.connect(lambda v:self.canvas.set_zoom(v/100)); header.addWidget(zoom)
            self.zoom_slider=zoom; layout.addLayout(header)
            self.scroll=QScrollArea(); self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter); self.scroll.setWidget(self.canvas)
            layout.addWidget(self.scroll)
            self.canvas.set_zoom(1)
            self.toolbar=Toolbar(self.canvas.style,settings.values["tool_keys"],self.scroll.viewport())
            self.toolbar.choose("arrow"); QTimer.singleShot(0,self.fit)
        self.toolbar.toolChanged.connect(self.choose_tool); self.toolbar.styleChanged.connect(self.canvas.text_changed)
        self.toolbar.undoRequested.connect(self.undo); self.toolbar.redoRequested.connect(self.redo)
        self.toolbar.copyRequested.connect(self.copy_image); self.toolbar.saveRequested.connect(self.save_image)
        self.toolbar.closeRequested.connect(self.close); self.toolbar.positionChanged.connect(self.save_position)
        self.canvas.changed.connect(self.update_controls); self.canvas.selectionChanged.connect(self.selection_changed)
        self.canvas.active.connect(lambda:self.becameActive.emit(self))
        self.restore_position()
        QApplication.instance().installEventFilter(self)
        if not getattr(self, "_wayland_overlay", False):
            self.show()
            if overlay and sys.platform=="darwin": self.mac_overlay_level()
            self.raise_(); self.activateWindow(); self.canvas.setFocus()
        self.update_controls()

    def present_on_screen(self, screen):
        """Wayland ignores setGeometry. Fullscreen is bound to one monitor via the window's screen."""
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self.winId()
        handle = self.windowHandle()
        if handle is not None and screen is not None:
            handle.setScreen(screen)
        self.showFullScreen()
        self.raise_(); self.activateWindow(); self.canvas.setFocus()

    def mac_overlay_level(self):
        import ctypes as C
        objc=C.CDLL("/usr/lib/libobjc.A.dylib")
        objc.sel_registerName.argtypes=[C.c_char_p]; objc.sel_registerName.restype=C.c_void_p
        send=C.CFUNCTYPE(C.c_void_p,C.c_void_p,C.c_void_p)(("objc_msgSend",objc))
        window=send(int(self.winId()),objc.sel_registerName(b"window"))
        if window:
            set_int=C.CFUNCTYPE(None,C.c_void_p,C.c_void_p,C.c_long)(("objc_msgSend",objc))
            set_int(window,objc.sel_registerName(b"setLevel:"),1000)
            set_int(window,objc.sel_registerName(b"setCollectionBehavior:"),1|256)

    def restore_position(self):
        parent=self.toolbar.parentWidget(); stored=self.settings.values.get("toolbar_position")
        if stored and isinstance(stored,list) and len(stored)==2:
            point=QPoint(round(stored[0]*max(0,parent.width()-self.toolbar.width_px())),round(stored[1]*max(0,parent.height()-self.toolbar.height())))
        else: point=QPoint(20,max(0,parent.height()-self.toolbar.height()-35))
        self.toolbar.move_bounded(point)

    def save_position(self):
        parent=self.toolbar.parentWidget()
        values=dict(self.settings.values)
        values["toolbar_position"]=[self.toolbar.x()/max(1,parent.width()-self.toolbar.width_px()),self.toolbar.y()/max(1,parent.height()-self.toolbar.height())]
        try: self.settings.save(values)
        except OSError as error: self.warning(f"Не удалось сохранить положение панели: {error}")

    def resizeEvent(self,event):
        if hasattr(self,"canvas") and self.overlay: self.canvas.setGeometry(self.rect())
        if hasattr(self,"toolbar"): self.toolbar.move_bounded(self.toolbar.pos())
        super().resizeEvent(event)

    def selection_changed(self):
        self.toolbar.setVisible(self.document.crop is not None)
        if self.overlay: self.becameActive.emit(self)
        self.toolbar.raise_(); self.update_controls()

    def choose_tool(self,tool):
        self.canvas.finish_text(); self.canvas.tool=tool; self.canvas.setFocus(); self.canvas.update()
    def undo(self):
        self.canvas.finish_text(); self.document.undo(); self.canvas.update(); self.update_controls()
    def redo(self):
        self.canvas.finish_text(); self.document.redo(); self.canvas.update(); self.update_controls()
    def update_controls(self):
        self.canvas.update()
        if self.overlay: self.toolbar.setVisible(self.document.crop is not None)
    def fit(self):
        if self.overlay: return
        available=self.scroll.viewport().size()
        scale=min(1,(available.width()-24)/self.document.image.width(),(available.height()-120)/self.document.image.height())
        self.zoom_slider.setValue(max(10,round(scale*100)))

    def eventFilter(self,watched,event):
        # One active editor handles keys. Dialogs (palette/save/confirm) keep their own input.
        if QApplication.activeModalWidget() is not None: return False
        widget=QApplication.focusWidget()
        if widget is None or widget.window() is not self: return False
        if event.type()==QEvent.Type.ShortcutOverride:
            mods=event.modifiers()
            if mods&(Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.MetaModifier) and event.key() in (Qt.Key.Key_C,Qt.Key.Key_S):
                event.accept(); return True
        if event.type()!=QEvent.Type.KeyPress: return False
        mods=event.modifiers(); command=bool(mods&(Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.MetaModifier))
        if command and event.key()==Qt.Key.Key_C:
            self.copy_image(); return True
        if command and event.key()==Qt.Key.Key_S:
            self.save_image(); return True
        if self.canvas.text_input is not None: return False
        if command and event.key()==Qt.Key.Key_Z:
            (self.redo if mods&Qt.KeyboardModifier.ShiftModifier else self.undo)(); return True
        if command and event.key()==Qt.Key.Key_Y:
            self.redo(); return True
        if event.key()==Qt.Key.Key_Escape:
            if self.overlay or self.settings.values["close_on_escape"]: self.close()
            else: self.canvas.cancel_gesture()
            return True
        if not command and not mods&Qt.KeyboardModifier.AltModifier:
            text=event.text().upper()
            # Physical number shortcuts remain usable with Russian input layout.
            if Qt.Key.Key_0<=event.key()<=Qt.Key.Key_9: text=chr(event.key())
            for tool,key in self.settings.values["tool_keys"].items():
                if key and key.upper()==text:
                    self.toolbar.choose(tool); return True
        return False

    def clipboard(self,png):
        from PySide6.QtCore import QByteArray,QMimeData
        from PySide6.QtGui import QImage
        image=QImage.fromData(png,"PNG")
        if image.isNull(): raise OSError("Итоговое изображение не прочитано.")
        mime=QMimeData(); mime.setData("image/png",QByteArray(png)); mime.setImageData(image)
        cb=QApplication.clipboard(); cb.setMimeData(mime)
        if not cb.mimeData().hasImage(): raise OSError("Системный буфер не принял изображение. Повторите копирование.")

    def warning(self,message):
        QTimer.singleShot(0,lambda:QMessageBox.warning(None,"JoxiLite",message))

    def copy_image(self):
        self.canvas.finish_text()
        if self.overlay and self.document.crop is None:
            self.warning("Сначала выделите область."); return
        values=self.settings.values
        history=HistoryStore(values["history_dir"],values["history_limit_mb"]*1_000_000)
        def recovery(png):
            from datetime import datetime
            path=data_directory()/"Recovery"/(datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".png")
            atomic_write(path,png); return path
        service=CopyService(self.clipboard,history,self.close_after_copy,self.warning_callback,recovery)
        try: service.copy(self.document,close_overlay=self.overlay)
        except Exception as error: self.warning(f"Не удалось скопировать снимок: {error}")

    def close_after_copy(self):
        self.allow_close=True; self.close()

    def save_image(self):
        self.canvas.finish_text()
        if self.overlay and self.document.crop is None: return False
        path,_=QFileDialog.getSaveFileName(self,"Сохранить снимок",str(Path.home()/"JoxiLite.png"),"PNG (*.png)")
        if not path: return False
        if not path.lower().endswith(".png"): path+=".png"
        try:
            atomic_write(Path(path),self.document.png()); self.document.mark_saved(); return True
        except OSError as error:
            QMessageBox.warning(self,"Ошибка сохранения",str(error)); return False

    def confirm_close(self):
        self.canvas.finish_text()
        if self.allow_close or not self.document.dirty or not self.settings.values["confirm_unsaved"]: return True
        box=QMessageBox(self); box.setWindowTitle("JoxiLite"); box.setText("Сохранить снимок перед закрытием?")
        save=box.addButton("Сохранить PNG…",QMessageBox.ButtonRole.AcceptRole)
        discard=box.addButton("Закрыть без сохранения",QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Отмена",QMessageBox.ButtonRole.RejectRole); box.exec()
        if box.clickedButton() is save: return self.save_image()
        return box.clickedButton() is discard

    def closeEvent(self,event):
        # Esc in the capture overlay always cancels immediately, like the original app.
        if not self.overlay and not self.confirm_close(): event.ignore(); return
        self._closed=True
        QApplication.instance().removeEventFilter(self)
        self.closed.emit(self); event.accept()
        self.deleteLater()

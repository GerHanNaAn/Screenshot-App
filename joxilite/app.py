from __future__ import annotations
import argparse
import copy
import logging
import os
from pathlib import Path
import sys
from PySide6.QtCore import QObject, QPoint, QRect, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QCursor, QDesktopServices, QIcon, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLabel, QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget
from . import __version__
from .document import Document
from .editor import Editor
from .instance import SingleInstance
from .linux_desktop import ensure_user_launcher
from .platforms import capture_backend, hotkey_backend
from .settings_ui import SettingsDialog
from .storage import Settings, data_directory


def icon():
    image=QImage(64,64,QImage.Format.Format_ARGB32); image.fill(Qt.GlobalColor.transparent)
    p=QPainter(image); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#096ee8")); p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(1,1,62,62,15,15)
    p.setPen(QPen(QColor("white"),4)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRoundedRect(12,20,40,30,5,5)
    p.drawEllipse(23,24,18,18); p.drawLine(21,14,42,14); p.end()
    from PySide6.QtGui import QPixmap
    return QIcon(QPixmap.fromImage(image))


class CaptureThread(QThread):
    result=Signal(object)
    failed=Signal(str)
    def __init__(self,function): super().__init__(); self.function=function
    def run(self):
        try: self.result.emit(self.function())
        except Exception as error: self.failed.emit(str(error))


class Controller(QObject):
    action=Signal(str)
    def __init__(self,app,no_hotkeys=False):
        super().__init__(); self.app=app; self.settings=Settings(); self.backend=capture_backend()
        self.editors=[]; self.overlays=[]; self.busy=False; self.threads=[]; self.hotkeys=None; self.dashboard=None
        self.action.connect(self.dispatch)
        self.tray=QSystemTrayIcon(icon(),self); self.tray.setToolTip(f"JoxiLite {__version__}")
        self.menu=QMenu(); self.tray.setContextMenu(self.menu); self.build_menu(); self.tray.show()
        self.tray.activated.connect(lambda reason:self.capture("area") if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if not no_hotkeys:
            QTimer.singleShot(400, self.setup_hotkeys)
        if self.settings.load_error: self.warn(self.settings.load_error)
        if not QSystemTrayIcon.isSystemTrayAvailable(): QTimer.singleShot(0,self.show_dashboard)

    def build_menu(self):
        self.menu.clear()
        for mode,title in (("area","Выделить область"),("window","Снять окно"),("screen","Снять экран под курсором"),("delayed","Экран через 3 секунды")):
            key=self.settings.values["capture_keys"].get(mode,"").replace("Meta","Cmd")
            action=self.menu.addAction(title+("  "+key if key else "")); action.triggered.connect(lambda checked=False,m=mode:self.capture(m))
        self.menu.addSeparator()
        for title,callback in (("Открыть изображение…",self.open_image),("История снимков…",self.history),("Настройки…",self.show_settings),("О JoxiLite",self.about)):
            action=self.menu.addAction(title); action.triggered.connect(callback)
        self.menu.addSeparator(); self.menu.addAction("Выход",self.quit)

    def setup_hotkeys(self):
        def hotkey_event(action):
            if action.startswith("error:"):
                logging.warning("%s", action[6:])
                return
            self.action.emit(action)
        try:
            self.hotkeys=hotkey_backend(hotkey_event)
            errors=self.hotkeys.register(self.settings.values["capture_keys"])
            if errors: logging.warning("\n".join(errors))
        except Exception as error:
            logging.warning("Горячие клавиши недоступны: %s", error)

    def warn(self,message):
        logging.warning(message)
        QTimer.singleShot(0,lambda:QMessageBox.warning(None,"JoxiLite",message))

    def dispatch(self,action):
        if action.startswith("error:"): self.warn(action[6:]); return
        if action in ("area","window","screen","delayed"): self.capture(action)
        elif action=="settings": self.show_settings()
        elif action=="history": self.history()
        elif action=="quit": self.quit()
        else: self.show_dashboard()

    def message(self,message):
        if message.get("open"): self.open_path(message["open"])
        else: self.dispatch(message.get("action","dashboard"))

    def run_capture(self,function,success):
        # QScreen.grabWindow is a GUI-thread API. Other native capture APIs run in a worker.
        from .platforms.linux import wayland
        gui=sys.platform.startswith("linux") and not wayland()
        if gui:
            try: success(function())
            except Exception as error: self.capture_error(str(error))
            return
        thread=CaptureThread(function); self.threads.append(thread)
        thread.result.connect(success); thread.failed.connect(self.capture_error)
        def done():
            self.threads.remove(thread); thread.deleteLater()
        thread.finished.connect(done); thread.start()

    def capture_error(self,error):
        self.busy=False
        if "отменён" not in error.lower(): self.warn(error)

    def capture(self,mode):
        if self.busy:
            if self.overlays: self.overlays[-1].raise_(); self.overlays[-1].activateWindow()
            return
        self.busy=True
        if mode=="window":
            self.run_capture(self.backend.windows,self.choose_window); return
        cursor=self.settings.values["include_cursor"]
        def start(): self.run_capture(lambda:self.backend.screens(cursor),lambda frames:self.show_overlay(frames,mode!="area"))
        if mode=="delayed":
            self.tray.showMessage("JoxiLite","Снимок через 3 секунды",QSystemTrayIcon.MessageIcon.Information,2500)
            QTimer.singleShot(3000,start)
        else: start()

    def choose_window(self,windows):
        if not windows: self.capture_error("Не найдено открытых окон."); return
        if len(windows)==1 and windows[0]["id"]=="portal": identifier="portal"
        else:
            titles=[w["title"] for w in windows]
            title,ok=QInputDialog.getItem(None,"Снять окно — JoxiLite","Окно",titles,0,False)
            if not ok: self.busy=False; return
            identifier=windows[titles.index(title)]["id"]
        QTimer.singleShot(180,lambda:self.run_capture(lambda:self.backend.window(identifier,self.settings.values["include_cursor"]),self.window_captured))

    def window_captured(self,frame):
        self.busy=False
        doc=Document(frame.image); doc.captured=True; self.show_editor(doc)

    def show_overlay(self,frames,full):
        if not frames: self.capture_error("Не найден экран."); return
        frames=self.frames_per_screen(frames)
        cursor=QCursor.pos(); active=None
        screens=self.app.screens()
        for frame in frames:
            geometry=frame.geometry
            # Match native logical bounds first; portal metadata can omit monitor positions.
            screen=next((s for s in screens if s.geometry()==geometry),None)
            if screen is None:
                screen=next((s for s in screens if s.geometry().size()==geometry.size() and s.geometry().topLeft()==geometry.topLeft()),None)
            if screen: geometry=screen.geometry()
            elif len(frames)==1:
                screen=self.app.screenAt(cursor) or self.app.primaryScreen()
                geometry=screen.geometry()
            doc=Document(frame.image); doc.captured=True
            if full and (geometry.contains(cursor) or len(frames)==1): doc.crop=doc.bounds
            editor=Editor(doc,self.settings,True,geometry,self.warn)
            editor.closed.connect(self.overlay_closed); editor.becameActive.connect(self.activate_overlay)
            self.overlays.append(editor)
            if getattr(editor,"_wayland_overlay",False): editor.present_on_screen(screen)
            if geometry.contains(cursor): active=editor
        active=active or self.overlays[0]
        self.activate_overlay(active); active.raise_(); active.activateWindow(); active.canvas.setFocus()

    def frames_per_screen(self, frames):
        """GNOME's screenshot portal returns one PNG of the whole desktop. Split it per monitor."""
        screens=self.app.screens()
        if len(frames)!=1 or len(screens)<2: return frames
        image=frames[0].image
        origin_x=min(screen.geometry().x() for screen in screens)
        origin_y=min(screen.geometry().y() for screen in screens)
        width=max(screen.geometry().right() for screen in screens)-origin_x+1
        height=max(screen.geometry().bottom() for screen in screens)-origin_y+1
        if image.width()!=width or image.height()!=height: return frames
        from .platforms import Frame
        pieces=[]
        for screen in screens:
            geometry=screen.geometry()
            crop=image.copy(geometry.x()-origin_x, geometry.y()-origin_y, geometry.width(), geometry.height())
            pieces.append(Frame(crop, geometry, screen.name()))
        return pieces

    def activate_overlay(self,editor):
        for other in self.overlays:
            if other is not editor:
                other.canvas.cancel_gesture(); other.toolbar.hide()
                # Keep frozen pixels but clear prior selection when choosing another monitor.
                other.document.crop=None; other.canvas.update()
        if editor.document.crop is not None: editor.toolbar.show(); editor.toolbar.raise_()

    def overlay_closed(self,editor):
        if editor in self.overlays: self.overlays.remove(editor)
        remaining=list(self.overlays); self.overlays.clear()
        for other in remaining: other.allow_close=True; other.close()
        self.busy=False

    def show_editor(self,doc):
        editor=Editor(doc,self.settings,copy_warning=self.warn); self.editors.append(editor)
        editor.closed.connect(lambda e:self.editors.remove(e) if e in self.editors else None)

    def open_path(self,path):
        try:
            image=QImage(str(path)); self.show_editor(Document(image))
        except (ValueError,OSError) as error: self.warn(str(error))

    def open_image(self):
        path,_=QFileDialog.getOpenFileName(None,"Открыть изображение",str(Path.home()),"Изображения (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp *.heic);;Все файлы (*)")
        if path: self.open_path(path)

    def history(self):
        path=Path(self.settings.values["history_dir"])
        try: path.mkdir(parents=True,exist_ok=True)
        except OSError as error: self.warn(str(error)); return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def apply_settings(self,values):
        old=copy.deepcopy(self.settings.values)
        if self.hotkeys:
            errors=self.hotkeys.register(values["capture_keys"])
            if errors:
                self.hotkeys.register(old["capture_keys"]); raise ValueError("\n".join(errors))
        try: self.settings.save(values)
        except Exception:
            if self.hotkeys: self.hotkeys.register(old["capture_keys"])
            raise
        self.build_menu()
        for editor in self.editors+self.overlays:
            for tool,button in editor.toolbar.buttons.items():
                from .toolbar import SYMBOLS
                button.setText(f"{SYMBOLS[tool]} {values['tool_keys'][tool]}")

    def show_settings(self):
        # Release hotkeys during recording so the old binding cannot launch capture.
        if self.hotkeys: self.hotkeys.clear()
        dialog=SettingsDialog(self.settings,self.apply_settings); dialog.exec()
        if self.hotkeys:
            errors=self.hotkeys.register(self.settings.values["capture_keys"])
            if errors: self.warn("\n".join(errors))

    def about(self):
        QMessageBox.information(None,"JoxiLite",f"JoxiLite {__version__}\nСнимки и история хранятся локально.\nОбщий редактор Qt 6 · системные адаптеры ОС")

    def show_dashboard(self):
        if self.dashboard is None:
            self.dashboard=QWidget(); self.dashboard.setWindowTitle("JoxiLite"); layout=QVBoxLayout(self.dashboard)
            layout.addWidget(QLabel("JoxiLite · снимки хранятся локально"))
            for title,callback in (("Выделить область",lambda:self.capture("area")),("Снять окно",lambda:self.capture("window")),
                                   ("Снять экран",lambda:self.capture("screen")),("Открыть изображение…",self.open_image),
                                   ("История",self.history),("Настройки",self.show_settings),("Выход",self.quit)):
                button=QPushButton(title); button.clicked.connect(callback); layout.addWidget(button)
            self.dashboard.resize(340,340)
        self.dashboard.show(); self.dashboard.raise_(); self.dashboard.activateWindow()

    def quit(self):
        for editor in list(self.editors)+list(self.overlays):
            if not editor.confirm_close(): return
        for editor in list(self.editors)+list(self.overlays): editor.allow_close=True; editor.close()
        if self.threads:
            self.warn("Дождитесь завершения текущего захвата перед выходом."); return
        if self.hotkeys: self.hotkeys.close()
        self.tray.hide(); self.app.quit()


def main():
    parser=argparse.ArgumentParser(description="JoxiLite — локальные снимки экрана")
    parser.add_argument("path",nargs="?")
    parser.add_argument("--open")
    parser.add_argument("--capture",choices=("area","window","screen","delayed"))
    parser.add_argument("--settings",action="store_true"); parser.add_argument("--history",action="store_true")
    parser.add_argument("--quit",action="store_true"); parser.add_argument("--no-hotkeys",action="store_true",help=argparse.SUPPRESS)
    args=parser.parse_args()
    if sys.platform=="win32":
        import ctypes
        try: ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except (AttributeError,OSError): pass
    ensure_user_launcher()
    app=QApplication(sys.argv[:1]); app.setApplicationName("JoxiLite"); app.setOrganizationName("JoxiLite")
    app.setApplicationVersion(__version__); app.setQuitOnLastWindowClosed(False); app.setWindowIcon(icon())
    data_directory().mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=str(data_directory()/"JoxiLite.log"),encoding="utf-8",level=logging.WARNING)
    controller=None
    instance=SingleInstance(lambda message:controller.message(message))
    action=args.capture or ("settings" if args.settings else "history" if args.history else "quit" if args.quit else "dashboard")
    message={"open":str(Path(args.open or args.path).absolute())} if args.open or args.path else {"action":action}
    if not instance.primary:
        instance.send(message); return 0
    controller=Controller(app,args.no_hotkeys)
    if args.open or args.path or args.capture or args.settings or args.history or args.quit:
        QTimer.singleShot(0,lambda:controller.message(message))
    app.aboutToQuit.connect(instance.close)
    return app.exec()


if __name__=="__main__":
    raise SystemExit(main())

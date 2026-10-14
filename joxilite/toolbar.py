from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget
from .document import TOOLS, HINTS
from .palette import Palette

SYMBOLS = {"arrow":"↗","rectangle":"□","ellipse":"○","line":"╱","pen":"✎","text":"T","pixelate":"▦","crop":"⌗"}


class DragHandle(QLabel):
    moved = Signal(QPoint)
    released = Signal()
    def __init__(self,parent):
        super().__init__("⠿",parent)
        self.setFixedWidth(24)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("Перетащить панель")
        self.start = None

    def mousePressEvent(self,e):
        self.start = e.globalPosition().toPoint()-self.parentWidget().pos()
    def mouseMoveEvent(self,e):
        if self.start is not None and e.buttons()&Qt.MouseButton.LeftButton:
            self.moved.emit(e.globalPosition().toPoint()-self.start)
    def mouseReleaseEvent(self,e):
        self.start = None; self.released.emit()


class Toolbar(QFrame):
    toolChanged = Signal(str)
    styleChanged = Signal()
    undoRequested = Signal()
    redoRequested = Signal()
    copyRequested = Signal()
    saveRequested = Signal()
    closeRequested = Signal()
    positionChanged = Signal()
    def __init__(self,style,keys,parent=None):
        super().__init__(parent)
        self.style = style
        self.setObjectName("toolbar")
        self.setStyleSheet('''QFrame#toolbar {background:#0868df;border:1px solid #60a4ff;border-radius:10px;}
            QLabel,QCheckBox {color:white;} QPushButton {background:#1479ed;color:white;border:1px solid #69aaff;
            border-radius:5px;padding:5px;min-height:24px;} QPushButton:hover {background:#3495ff;}
            QPushButton:checked {background:#fff;color:#0758bd;} QSpinBox {background:white;color:#142438;}
            QSlider::groove:horizontal {height:5px;background:#9dceff;border-radius:2px;}
            QSlider::handle:horizontal {width:13px;margin:-5px 0;background:white;border-radius:6px;}''')
        layout = QVBoxLayout(self); layout.setContentsMargins(8,6,8,6); layout.setSpacing(4)
        row = QHBoxLayout(); row.setSpacing(4); layout.addLayout(row)
        self.handle = DragHandle(self); self.handle.moved.connect(self.move_bounded); self.handle.released.connect(self.positionChanged)
        row.addWidget(self.handle)
        self.buttons = {}
        for tool,title in TOOLS.items():
            button = QPushButton(f"{SYMBOLS[tool]} {keys.get(tool,'')}")
            button.setToolTip(f"{title} · {keys.get(tool,'')}\n{HINTS[tool]}")
            button.setAccessibleName(title)
            button.setCheckable(True); button.setFixedWidth(42)
            button.clicked.connect(lambda checked=False,t=tool:self.choose(t))
            row.addWidget(button); self.buttons[tool] = button
        self.color_button = QPushButton("Цвет"); self.color_button.clicked.connect(lambda:self.palette(False)); row.addWidget(self.color_button)
        for title,tip,signal in (("↶","Отмена · Ctrl/Cmd+Z",self.undoRequested),("↷","Повтор · Ctrl/Cmd+Shift+Z",self.redoRequested),
                                 ("Копировать","Ctrl/Cmd+C",self.copyRequested),("PNG","Сохранить · Ctrl/Cmd+S",self.saveRequested),
                                 ("×","Закрыть · Esc",self.closeRequested)):
            b = QPushButton(title); b.setToolTip(tip); b.clicked.connect(signal.emit); row.addWidget(b)
        row2 = QHBoxLayout(); layout.addLayout(row2)
        row2.addWidget(QLabel("Толщина"))
        self.width = QSlider(Qt.Orientation.Horizontal); self.width.setRange(1,30); self.width.setValue(int(style.width)); self.width.setFixedWidth(120)
        self.width.valueChanged.connect(self.width_changed); row2.addWidget(self.width)
        self.width_label = QLabel(f"{style.width:g} px"); row2.addWidget(self.width_label)
        self.hint = QLabel("Выделите область · Shift — квадрат"); row2.addWidget(self.hint); row2.addStretch()
        self.text_row = QWidget(); tr = QHBoxLayout(self.text_row); tr.setContentsMargins(0,0,0,0); layout.addWidget(self.text_row)
        tr.addWidget(QLabel("Текст, px")); self.font = QSpinBox(); self.font.setRange(10,192); self.font.setValue(round(style.font_size)); tr.addWidget(self.font)
        tr.addWidget(QLabel("Буквы, %")); self.opacity = QSpinBox(); self.opacity.setRange(0,100); self.opacity.setValue(100); tr.addWidget(self.opacity)
        self.background = QCheckBox("Подложка"); tr.addWidget(self.background)
        self.bg_button = QPushButton("Цвет подложки"); self.bg_button.clicked.connect(lambda:self.palette(True)); tr.addWidget(self.bg_button)
        tr.addStretch(); self.text_row.hide()
        self.font.valueChanged.connect(self.text_changed); self.opacity.valueChanged.connect(self.text_changed); self.background.toggled.connect(self.text_changed)
        self.refresh_color(); self.adjustSize()

    def choose(self,tool):
        for name,button in self.buttons.items(): button.setChecked(name==tool)
        self.hint.setText(HINTS[tool]); self.text_row.setVisible(tool=="text")
        self.adjustSize(); self.move_bounded(self.pos()); self.toolChanged.emit(tool)

    def width_changed(self,value):
        self.style.width = value; self.width_label.setText(f"{value} px"); self.styleChanged.emit()
    def text_changed(self,*args):
        self.style.font_size = self.font.value(); self.style.text_opacity = self.opacity.value()/100
        self.style.background = self.background.isChecked(); self.styleChanged.emit()
    def refresh_color(self):
        self.color_button.setStyleSheet(f"background:{QColor(self.style.color).name()};color:white;")
    def palette(self,background):
        dialog = Palette(self.style.background_color if background else self.style.color,self.window())
        def changed(color):
            if background: self.style.background_color = color.name(QColor.NameFormat.HexArgb)
            else: self.style.color = color.name(QColor.NameFormat.HexArgb)
            self.refresh_color(); self.styleChanged.emit()
        dialog.colorChanged.connect(changed)
        dialog.exec()

    def move_bounded(self,point):
        parent = self.parentWidget()
        self.move(max(0,min(point.x(),parent.width()-self.width_px())),max(0,min(point.y(),parent.height()-self.height())))
    def width_px(self): return QWidget.width(self)

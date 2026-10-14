import math
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QSlider, QSpinBox, QVBoxLayout, QWidget


class ColorWheel(QWidget):
    changed = Signal(float,float)
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220,220)
        self.hue,self.saturation,self.value = 0.,1.,1.
        self.cache = None
        self.setAccessibleName("Цветовой круг")

    def paintEvent(self,event):
        if self.cache is None:
            image = QImage(220,220,QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            for y in range(220):
                for x in range(220):
                    dx,dy = (x-110)/106,(y-110)/106
                    radius = math.hypot(dx,dy)
                    if radius <= 1:
                        hue = (math.atan2(-dy,dx)/(2*math.pi))%1
                        image.setPixelColor(x,y,QColor.fromHsvF(hue,radius,self.value))
            self.cache = image
        p = QPainter(self); p.drawImage(0,0,self.cache)
        angle = self.hue*2*math.pi
        point = QPointF(110+106*self.saturation*math.cos(angle),110-106*self.saturation*math.sin(angle))
        p.setPen(QPen(Qt.GlobalColor.black,3)); p.drawEllipse(point,6,6)
        p.setPen(QPen(Qt.GlobalColor.white,1)); p.drawEllipse(point,6,6)

    def choose(self,event):
        dx,dy = (event.position().x()-110)/106,(110-event.position().y())/106
        self.hue = (math.atan2(dy,dx)/(2*math.pi))%1
        self.saturation = min(1,math.hypot(dx,dy))
        self.changed.emit(self.hue,self.saturation); self.update()

    def mousePressEvent(self,e): self.choose(e)
    def mouseMoveEvent(self,e):
        if e.buttons()&Qt.MouseButton.LeftButton: self.choose(e)


class Palette(QDialog):
    colorChanged = Signal(QColor)
    def __init__(self, color, parent=None):
        super().__init__(parent,Qt.WindowType.Dialog|Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Цвет и прозрачность — JoxiLite")
        self.color = QColor(color)
        self.updating = False
        layout = QVBoxLayout(self)
        self.wheel = ColorWheel(self); layout.addWidget(self.wheel,alignment=Qt.AlignmentFlag.AlignHCenter)
        form = QFormLayout(); layout.addLayout(form)
        self.value = QSlider(Qt.Orientation.Horizontal); self.value.setRange(0,100)
        form.addRow("Яркость",self.value)
        self.rgb = []
        for label in ("R","G","B"):
            spin = QSpinBox(); spin.setRange(0,255); form.addRow(label,spin); self.rgb.append(spin)
            spin.valueChanged.connect(self.rgb_changed)
        self.hex = QLineEdit(); self.hex.setMaxLength(9); form.addRow("HEX (#RRGGBB)",self.hex)
        self.alpha = QSlider(Qt.Orientation.Horizontal); self.alpha.setRange(0,100); form.addRow("Непрозрачность",self.alpha)
        self.sample = QLabel(); self.sample.setMinimumHeight(28); layout.addWidget(self.sample)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Готово")
        buttons.rejected.connect(self.accept); layout.addWidget(buttons)
        self.wheel.changed.connect(self.wheel_changed)
        self.value.valueChanged.connect(self.value_changed)
        self.alpha.valueChanged.connect(self.alpha_changed)
        self.hex.editingFinished.connect(self.hex_changed)
        self.sync()

    def sync(self):
        self.updating = True
        h,s,v,_ = self.color.getHsvF()
        self.wheel.hue,self.wheel.saturation = max(0,h),s
        if self.wheel.value != v: self.wheel.value = v; self.wheel.cache = None
        self.wheel.update()
        for spin,value in zip(self.rgb,(self.color.red(),self.color.green(),self.color.blue())): spin.setValue(value)
        self.value.setValue(round(v*100)); self.alpha.setValue(round(self.color.alphaF()*100))
        self.hex.setText(self.color.name(QColor.NameFormat.HexRgb).upper())
        self.sample.setText(f"{self.alpha.value()}%")
        self.sample.setStyleSheet(f"background:{self.color.name(QColor.NameFormat.HexArgb)};border:1px solid #999;padding:4px;")
        self.updating = False

    def emit(self): self.sync(); self.colorChanged.emit(QColor(self.color))
    def wheel_changed(self,h,s):
        self.color = QColor.fromHsvF(h,s,self.wheel.value,self.color.alphaF()); self.emit()
    def value_changed(self,value):
        if self.updating: return
        h,s,_,a = self.color.getHsvF(); self.color = QColor.fromHsvF(max(0,h),s,value/100,a); self.emit()
    def rgb_changed(self,*args):
        if self.updating: return
        self.color = QColor(*[s.value() for s in self.rgb],self.color.alpha()); self.emit()
    def alpha_changed(self,value):
        if self.updating: return
        self.color.setAlphaF(value/100); self.emit()
    def hex_changed(self):
        c = QColor(self.hex.text())
        if c.isValid(): c.setAlpha(self.color.alpha()); self.color=c; self.emit()
        else: self.sync()

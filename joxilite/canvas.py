from __future__ import annotations
import copy
from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPlainTextEdit, QWidget
from .document import Annotation, Style, text_bounds, text_font
from .geometry import PixelMapping, bounded_rect, square_end


class TextInput(QPlainTextEdit):
    def __init__(self,canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.setFrameStyle(0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet("QPlainTextEdit {background:transparent;color:transparent;border:0;selection-background-color:rgba(80,130,255,60);}")
        self.document().setDocumentMargin(0)
        self.textChanged.connect(canvas.text_changed)
        self.cursorPositionChanged.connect(canvas.update)

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and not event.modifiers()&Qt.KeyboardModifier.ShiftModifier:
            self.canvas.finish_text(); event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.canvas.finish_text(cancel=True); event.accept()
        else: super().keyPressEvent(event)


class Canvas(QWidget):
    changed = Signal()
    selectionChanged = Signal()
    active = Signal()
    def __init__(self,document,overlay=False,parent=None):
        super().__init__(parent)
        self.document = document
        self.overlay = overlay
        self.style = Style()
        self.tool = None if overlay else "arrow"
        self.preview = None
        self.selection = None
        self.gesture = []
        self.drag_mode = None
        self.resize_edges = ""
        self.drag_start = QPointF()
        self.original = QRectF()
        self.shift = False
        self.zoom = 1.
        self.text_input = None
        self.text_annotation = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @property
    def image_rect(self):
        return QRectF(self.rect()) if self.overlay else QRectF(0,0,self.document.image.width()*self.zoom,self.document.image.height()*self.zoom)
    @property
    def mapping(self):
        return PixelMapping(QSizeF(self.document.image.size()),self.image_rect)
    @property
    def selected(self):
        return self.selection if self.selection is not None else (QRectF(self.document.crop) if self.document.crop is not None else None)

    def paintEvent(self,event):
        p = QPainter(self)
        p.fillRect(self.rect(),QColor("#202c3b"))
        m = self.mapping
        sx,sy = m.view.width()/m.pixels.width(),m.view.height()/m.pixels.height()
        p.save(); p.scale(sx,sy)
        # Single rendering path for text (including live text), shapes, mosaic and PNG.
        self.document.draw(p,self.text_annotation or self.preview)
        p.restore()
        rect = self.selected
        if self.overlay or rect is not None:
            mask = QPainterPath(); mask.addRect(self.image_rect)
            if rect is not None: mask.addRect(m.rect_to_view(rect))
            p.fillPath(mask,QColor(0,0,0,105))
        if rect is not None:
            r = m.rect_to_view(rect)
            p.setPen(QPen(QColor("white"),1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(r)
            for x,y in self.handles(r):
                p.fillRect(QRectF(x-4,y-4,8,8),QColor("white"))
                p.setPen(QColor("#23354d")); p.drawRect(QRectF(x-4,y-4,8,8))
            size = bounded_rect(rect,self.document.image.width(),self.document.image.height())
            label = f"{size.width()} × {size.height()} px"
            p.setFont(QFont("Arial",11)); width = p.fontMetrics().horizontalAdvance(label)+16
            x = max(8,min(self.width()-width-8,r.x()))
            y = r.y()-28 if r.y()>30 else min(self.height()-26,r.bottom()+6)
            p.fillRect(QRectF(x,y,width,22),QColor(0,0,0,210)); p.setPen(QColor("white")); p.drawText(QPointF(x+8,y+16),label)
        if self.text_input is not None:
            # The QPlainTextEdit is an input sink. Visible text is always drawn above by Document.
            caret = self.text_input.cursorRect()
            p.setPen(QPen(QColor(self.style.color),1))
            p.drawLine(caret.topLeft()+self.text_input.pos(),caret.bottomLeft()+self.text_input.pos())
        p.end()

    @staticmethod
    def handles(r):
        return [(r.left(),r.top()),(r.center().x(),r.top()),(r.right(),r.top()),(r.left(),r.center().y()),
                (r.right(),r.center().y()),(r.left(),r.bottom()),(r.center().x(),r.bottom()),(r.right(),r.bottom())]

    def hit_edges(self,point):
        if self.selected is None: return ""
        r = self.mapping.rect_to_view(self.selected)
        if not r.adjusted(-9,-9,9,9).contains(point): return ""
        return ("l" if abs(point.x()-r.left())<=9 else "")+("r" if abs(point.x()-r.right())<=9 else "")+(
                "t" if abs(point.y()-r.top())<=9 else "")+("b" if abs(point.y()-r.bottom())<=9 else "")

    def mousePressEvent(self,event):
        if event.button() != Qt.MouseButton.LeftButton: return
        self.active.emit(); self.setFocus(); self.finish_text()
        self.shift = bool(event.modifiers()&Qt.KeyboardModifier.ShiftModifier)
        point = self.mapping.to_pixel(event.position())
        self.drag_start = point; self.original = QRectF(self.selected) if self.selected is not None else QRectF()
        self.resize_edges = self.hit_edges(event.position())
        if self.resize_edges:
            self.drag_mode = "resize"
        elif self.tool in (None,"crop"):
            self.drag_mode = "move" if self.selected is not None and self.selected.contains(point) else "select"
        elif self.selected is not None and not self.selected.contains(point):
            self.drag_mode = "select"
        elif self.tool == "text":
            self.start_text(point); return
        else:
            self.drag_mode = "draw"; self.gesture = [point]
        self.update()

    def mouseMoveEvent(self,event):
        if not self.drag_mode:
            edges = self.hit_edges(event.position())
            cursor = Qt.CursorShape.SizeFDiagCursor if edges in ("lt","rb") else Qt.CursorShape.SizeBDiagCursor if edges in ("rt","lb") else (
                Qt.CursorShape.SizeHorCursor if edges in ("l","r") else Qt.CursorShape.SizeVerCursor if edges else Qt.CursorShape.CrossCursor)
            self.setCursor(cursor); return
        point = self.mapping.to_pixel(event.position())
        self.shift = bool(event.modifiers()&Qt.KeyboardModifier.ShiftModifier)
        if self.drag_mode == "draw":
            if self.tool == "pen": self.gesture.append(point)
            else: self.gesture = [self.drag_start,point]
            self.preview = Annotation.drawing(self.tool,self.gesture,self.style,self.shift)
        elif self.drag_mode == "select":
            if self.shift: point = square_end(self.drag_start,point)
            self.selection = QRectF(bounded_rect(QRectF(self.drag_start,point),self.document.image.width(),self.document.image.height()))
        elif self.drag_mode == "move":
            delta = point-self.drag_start
            if self.shift:
                if abs(delta.x())>=abs(delta.y()): delta.setY(0)
                else: delta.setX(0)
            x = max(0,min(self.document.image.width()-self.original.width(),self.original.x()+delta.x()))
            y = max(0,min(self.document.image.height()-self.original.height(),self.original.y()+delta.y()))
            self.selection = QRectF(x,y,self.original.width(),self.original.height())
        elif self.drag_mode == "resize":
            r = QRectF(self.original)
            if "l" in self.resize_edges: r.setLeft(point.x())
            if "r" in self.resize_edges: r.setRight(point.x())
            if "t" in self.resize_edges: r.setTop(point.y())
            if "b" in self.resize_edges: r.setBottom(point.y())
            if self.shift:
                r = r.normalized(); side=min(r.width(),r.height()); r.setSize(QSizeF(side,side))
            self.selection = QRectF(bounded_rect(r,self.document.image.width(),self.document.image.height()))
        self.update()

    def mouseReleaseEvent(self,event):
        if event.button() != Qt.MouseButton.LeftButton or not self.drag_mode: return
        self.mouseMoveEvent(event)
        if self.drag_mode == "draw":
            if self.preview: self.document.add(self.preview)
        elif self.selection is not None:
            self.document.set_crop(self.selection)
            self.selectionChanged.emit()
        self.drag_mode=None; self.preview=None; self.gesture=[]; self.selection=None
        self.changed.emit(); self.update()

    def cancel_gesture(self):
        self.drag_mode=None; self.preview=None; self.selection=None; self.gesture=[]
        self.finish_text(cancel=True); self.update()

    def start_text(self,point):
        self.text_annotation = Annotation("text",[point],copy.deepcopy(self.style))
        self.text_input = TextInput(self)
        self.text_input.show(); self.layout_text(); self.text_input.setFocus(); self.update()

    def text_changed(self):
        if self.text_input is None: return
        self.text_annotation.text = self.text_input.toPlainText()
        self.text_annotation.style = copy.deepcopy(self.style)
        self.layout_text(); self.update()

    def layout_text(self):
        if self.text_input is None: return
        scale = self.image_rect.width()/self.document.image.width()
        font = text_font(self.style); font.setPixelSize(max(1,round(self.style.font_size*scale)))
        self.text_input.setFont(font)
        r = self.mapping.rect_to_view(text_bounds(self.text_annotation))
        self.text_input.setGeometry(round(r.x()),round(r.y()),max(100,round(r.width()+40)),max(30,round(r.height()+20)))
        self.text_input.raise_()
        # Toolbar must stay above the transparent input's hit area.
        if hasattr(self.window(),"toolbar"): self.window().toolbar.raise_()

    def finish_text(self,cancel=False):
        if self.text_input is None: return
        if not cancel and self.text_input.toPlainText().strip():
            self.text_annotation.text = self.text_input.toPlainText()
            self.document.add(self.text_annotation); self.changed.emit()
        self.text_input.hide(); self.text_input.deleteLater(); self.text_input=None; self.text_annotation=None
        self.setFocus(); self.update()

    def set_zoom(self,zoom):
        self.zoom = zoom
        self.resize(max(1,round(self.document.image.width()*zoom)),max(1,round(self.document.image.height()*zoom)))
        self.layout_text(); self.update()

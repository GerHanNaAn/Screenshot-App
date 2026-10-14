from __future__ import annotations
import copy
import math
from dataclasses import dataclass, field
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPainterPath, QPen
from .geometry import bounded_rect, snapped_end

TOOLS = {"arrow": "Стрелка", "rectangle": "Рамка", "ellipse": "Овал", "line": "Линия",
         "pen": "Перо", "text": "Текст", "pixelate": "Мозаика", "crop": "Обрезка"}
HINTS = {"arrow": "Shift — шаг 45°", "line": "Shift — шаг 45°", "pen": "Shift — прямой штрих",
         "rectangle": "Shift — заливка", "ellipse": "Shift — заливка", "pixelate": "Shift — крупнее",
         "crop": "Shift — квадрат · внутри — перемещение по одной оси",
         "text": "Enter — готово · Shift+Enter — новая строка"}


@dataclass
class Style:
    color: str = "#ffed3e45"  # ARGB, consistently including alpha
    width: float = 4
    font_size: float = 28
    text_opacity: float = 1
    background: bool = False
    background_color: str = "#b3000000"


@dataclass
class Annotation:
    tool: str
    points: list[QPointF]
    style: Style = field(default_factory=Style)
    text: str = ""
    alternative: bool = False

    @property
    def rect(self):
        return QRectF(self.points[0], self.points[-1]).normalized()

    @classmethod
    def drawing(cls, tool, points, style, shift=False):
        points = [QPointF(p) for p in points]
        if shift and tool in ("line", "arrow"):
            points = [points[0], snapped_end(points[0], points[-1])]
        if shift and tool == "pen":
            points = [points[0], points[-1]]
        return cls(tool, points, copy.deepcopy(style), alternative=shift)


def text_font(style):
    font = QFont("Arial")
    # Pixel size is measured in the ORIGINAL image, not logical display points.
    font.setPixelSize(round(style.font_size))
    font.setBold(True)
    return font


def text_bounds(a):
    metrics = QFontMetricsF(text_font(a.style))
    lines = a.text.split("\n")
    return QRectF(a.points[0], __import__('PySide6.QtCore', fromlist=['QSizeF']).QSizeF(
        max(a.style.font_size, max(metrics.horizontalAdvance(s) for s in lines)),
        metrics.lineSpacing()*len(lines)))


class Document:
    def __init__(self, image: QImage):
        if image.isNull():
            raise ValueError("Не удалось открыть изображение.")
        self.image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        self.image.setDevicePixelRatio(1)
        self.annotations: list[Annotation] = []
        self.crop: QRect | None = None
        self.undo_stack = []
        self.redo_stack = []
        self.saved_state = self.state()
        self.captured = False

    @property
    def bounds(self):
        return QRect(0, 0, self.image.width(), self.image.height())

    def state(self):
        return copy.deepcopy((self.annotations, self.crop))

    @property
    def dirty(self):
        return self.captured or self.state() != self.saved_state

    def mark_saved(self):
        self.saved_state = self.state()
        self.captured = False

    def checkpoint(self):
        self.undo_stack.append(self.state())
        self.undo_stack = self.undo_stack[-100:]
        self.redo_stack.clear()

    def add(self, annotation):
        self.checkpoint()
        self.annotations.append(copy.deepcopy(annotation))

    def set_crop(self, rect):
        rect = bounded_rect(QRectF(rect), self.image.width(), self.image.height()) if rect is not None else None
        if rect is not None and (rect.width() < 2 or rect.height() < 2):
            return
        if self.crop != rect:
            self.checkpoint()
            self.crop = rect

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.state())
            self.annotations, self.crop = self.undo_stack.pop()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.state())
            self.annotations, self.crop = self.redo_stack.pop()

    def draw(self, painter: QPainter, preview=None):
        painter.save()
        painter.setClipRect(self.bounds)
        painter.drawImage(0, 0, self.image)
        for annotation in self.annotations + ([preview] if preview else []):
            self.draw_annotation(painter, annotation)
        painter.restore()

    def draw_annotation(self, p, a):
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        color = QColor(a.style.color)
        pen = QPen(color, a.style.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        start, end = a.points[0], a.points[-1]
        if a.tool in ("line", "arrow", "pen"):
            path = QPainterPath(start)
            for point in a.points[1:]:
                path.lineTo(point)
            if len(a.points) == 1:
                p.drawPoint(start)
            else:
                p.drawPath(path)
            if a.tool == "arrow":
                angle = math.atan2(end.y()-start.y(), end.x()-start.x())
                size = max(12, a.style.width*5)
                for offset in (-math.pi/6, math.pi/6):
                    p.drawLine(end, end-QPointF(size*math.cos(angle+offset), size*math.sin(angle+offset)))
        elif a.tool in ("rectangle", "ellipse"):
            if a.alternative:
                p.setBrush(color)
                p.setPen(Qt.PenStyle.NoPen)
            (p.drawRect if a.tool == "rectangle" else p.drawEllipse)(a.rect)
        elif a.tool == "text":
            font = text_font(a.style)
            metrics = QFontMetricsF(font)
            r = text_bounds(a)
            if a.style.background:
                padding = max(4, a.style.font_size*0.2)
                p.fillRect(r.adjusted(-padding, -padding, padding, padding), QColor(a.style.background_color))
            color.setAlphaF(color.alphaF()*a.style.text_opacity)
            p.setPen(color)
            p.setFont(font)
            for i, line in enumerate(a.text.split("\n")):
                p.drawText(start+QPointF(0, metrics.ascent()+i*metrics.lineSpacing()), line)
        elif a.tool == "pixelate":
            r = bounded_rect(a.rect, self.image.width(), self.image.height())
            if r.width() and r.height():
                block = 28 if a.alternative else 14
                source = self.image.copy(r)
                small = source.scaled(max(1, math.ceil(r.width()/block)), max(1, math.ceil(r.height()/block)),
                                      Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                mosaic = small.scaled(r.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
                p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
                p.drawImage(r.topLeft(), mosaic)
        p.restore()

    def render(self, preview=None, cropped=True):
        rect = self.crop if cropped and self.crop is not None else self.bounds
        result = QImage(rect.size(), QImage.Format.Format_ARGB32_Premultiplied)
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        p.translate(-rect.x(), -rect.y())
        self.draw(p, preview)
        p.end()
        return result

    def png(self):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not self.render().save(buffer, "PNG"):
            raise OSError("Не удалось сформировать PNG.")
        return bytes(data)

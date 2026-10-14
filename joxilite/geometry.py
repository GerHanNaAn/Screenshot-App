"""All document coordinates are physical image pixels, independent of OS DPI."""
import math
from PySide6.QtCore import QPointF, QRect, QRectF, QSizeF


def bounded_rect(rect: QRectF, width: int, height: int) -> QRect:
    r = rect.normalized().intersected(QRectF(0, 0, width, height))
    # Outward rounding keeps every selected physical pixel, including at fractional DPI.
    left, top = max(0, math.floor(r.left())), max(0, math.floor(r.top()))
    right, bottom = min(width, math.ceil(r.right())), min(height, math.ceil(r.bottom()))
    return QRect(left, top, max(0, right-left), max(0, bottom-top))


def square_end(start: QPointF, end: QPointF) -> QPointF:
    dx, dy = end.x()-start.x(), end.y()-start.y()
    side = min(abs(dx), abs(dy))
    return QPointF(start.x()+math.copysign(side, dx), start.y()+math.copysign(side, dy))


def snapped_end(start: QPointF, end: QPointF) -> QPointF:
    dx, dy = end.x()-start.x(), end.y()-start.y()
    length = math.hypot(dx, dy)
    angle = math.floor(math.atan2(dy, dx)/(math.pi/4)+0.5)*(math.pi/4)
    return start + QPointF(length*math.cos(angle), length*math.sin(angle))


class PixelMapping:
    def __init__(self, pixels: QSizeF, view: QRectF):
        self.pixels, self.view = pixels, view

    def to_pixel(self, point: QPointF, clamp=True) -> QPointF:
        x = (point.x()-self.view.x())*self.pixels.width()/self.view.width()
        y = (point.y()-self.view.y())*self.pixels.height()/self.view.height()
        if clamp:
            x, y = min(self.pixels.width(), max(0, x)), min(self.pixels.height(), max(0, y))
        return QPointF(x, y)

    def to_view(self, point: QPointF) -> QPointF:
        return self.view.topLeft()+QPointF(point.x()*self.view.width()/self.pixels.width(),
                                         point.y()*self.view.height()/self.pixels.height())

    def rect_to_view(self, rect: QRectF) -> QRectF:
        return QRectF(self.to_view(rect.topLeft()), self.to_view(rect.bottomRight()))

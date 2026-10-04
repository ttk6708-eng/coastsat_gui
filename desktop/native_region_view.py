"""Polygon input in image coordinates, independent of viewport zoom/pan."""
from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsPolygonItem, QGraphicsEllipseItem, QGraphicsItem
from desktop.native_widgets import ImageView


class RegionImageView(ImageView):
    points_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.drawing = False
        self.points = []
        self.markers = []
        self.region = QGraphicsPolygonItem()
        pen = QPen(QColor('#36e8b4'), 2); pen.setCosmetic(True)
        self.region.setPen(pen)
        self.region.setBrush(QColor(54,232,180,35))
        self.region.setZValue(2)
        self.scene().addItem(self.region)

    def set_drawing(self, drawing, clear=False):
        self.drawing = drawing
        if clear:
            self.set_points([])
        self.setDragMode(self.DragMode.NoDrag if drawing else self.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.CrossCursor if drawing else Qt.CursorShape.OpenHandCursor)
        self.points_changed.emit()

    def set_points(self, points):
        self.points = [(float(x),float(y)) for x,y in points]
        self.region.setPolygon(QPolygonF([QPointF(x,y) for x,y in self.points]))
        for marker in self.markers:
            self.scene().removeItem(marker)
        self.markers=[]
        for x,y in self.points:
            marker=QGraphicsEllipseItem(-3,-3,6,6)
            marker.setBrush(QColor('#36e8b4'));marker.setPen(QPen(QColor('#12382e')))
            marker.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            marker.setPos(x,y);marker.setZValue(3);self.scene().addItem(marker);self.markers.append(marker)
        self.points_changed.emit()

    def undo_point(self):
        self.set_points(self.points[:-1])

    def mousePressEvent(self, event):
        if self.drawing and event.button() == Qt.MouseButton.LeftButton:
            point = self.mapToScene(event.position().toPoint())
            if self.base.boundingRect().contains(point):
                xy = (point.x(), point.y())
                if not self.points or (QPointF(*self.points[-1])-point).manhattanLength() > .05:
                    self.set_points([*self.points, xy])
            event.accept()
            return
        if self.drawing:
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.drawing:
            event.accept()  # Applying is always explicit; double-click cannot save/close.
            return
        super().mouseDoubleClickEvent(event)

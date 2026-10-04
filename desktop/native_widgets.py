"""Native Qt widgets; no web engine or local web server."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem


class ImageView(QGraphicsView):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.base = QGraphicsPixmapItem()
        self.mask = QGraphicsPixmapItem()
        self.mask.setZValue(1)
        self.scene().addItem(self.base)
        self.scene().addItem(self.mask)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor('#182b3d'))
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMinimumSize(170,200)
        self.fitted = True
        self._syncing = False
        self.horizontalScrollBar().valueChanged.connect(self.broadcast)
        self.verticalScrollBar().valueChanged.connect(self.broadcast)

    def set_images(self, image_path, mask_path):
        image = QPixmap(str(image_path))
        mask = QPixmap(str(mask_path))
        if image.isNull() or mask.isNull():
            raise ValueError('미리보기 이미지를 읽을 수 없습니다.')
        same_size = self.base.pixmap().size() == image.size()
        self.base.setPixmap(image)
        self.mask.setPixmap(mask)
        self.scene().setSceneRect(self.base.boundingRect())
        if not same_size or self.fitted:
            self.fit_image()

    def fit_image(self):
        if not self.base.pixmap().isNull():
            self.fitted = True
            self.fitInView(self.base.boundingRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.broadcast()

    def actual_size(self):
        self.fitted = False
        self.resetTransform()
        self.broadcast()

    def wheelEvent(self, event):
        if self.base.pixmap().isNull():
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        next_scale = self.transform().m11() * factor
        if .015 <= next_scale <= 32:
            self.fitted = False
            self.scale(factor, factor)
            self.broadcast()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fitted:
            self.fit_image()

    def broadcast(self, *args):
        if not self._syncing and not self.base.pixmap().isNull():
            self.changed.emit(self)

    def sync_from(self, other):
        if self.base.pixmap().isNull():
            return
        self._syncing = True
        self.fitted = other.fitted
        self.setTransform(other.transform())
        self.centerOn(other.mapToScene(other.viewport().rect().center()))
        self._syncing = False

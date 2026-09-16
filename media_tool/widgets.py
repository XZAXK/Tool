"""Shared video widgets and input filters."""
import math
from PyQt5.QtCore import Qt, QTimer, QEvent
from PyQt5.QtGui import QPixmap, QPainter, QImage, QCursor
from PyQt5.QtWidgets import QPushButton, QGraphicsView, QGraphicsScene, QToolTip

VIDEOS = '视频 (*.mp4 *.mkv *.avi *.mov *.webm *.m4v);;所有文件 (*)'


def button(text, layout, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    layout.addWidget(widget)
    return widget


class ImageView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.item = self.scene().addPixmap(QPixmap())
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(Qt.black)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.manual = False
        self.source_image = QImage()
        self.brightness_enabled = False
        self.hover_position = None
        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setTimerType(Qt.PreciseTimer)
        self.hover_timer.setInterval(200)
        self.hover_timer.timeout.connect(self.show_brightness)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.horizontalScrollBar().valueChanged.connect(self.cancel_hover)
        self.verticalScrollBar().valueChanged.connect(self.cancel_hover)

    def cancel_hover(self, *args):
        self.hover_timer.stop()
        self.hover_position = None
        QToolTip.hideText()

    def set_brightness_enabled(self, enabled):
        self.cancel_hover()
        self.brightness_enabled = bool(enabled)
        if enabled:
            self.schedule_hover(self.viewport().mapFromGlobal(QCursor.pos()))

    def image_pixel(self, position):
        if self.source_image.isNull() or not self.viewport().rect().contains(position):
            return None
        point = self.item.mapFromScene(self.mapToScene(position))
        x, y = math.floor(point.x()), math.floor(point.y())
        if 0 <= x < self.source_image.width() and 0 <= y < self.source_image.height():
            return x, y
        return None

    def schedule_hover(self, position):
        self.cancel_hover()
        if self.brightness_enabled and self.image_pixel(position) is not None:
            self.hover_position = position
            self.hover_timer.start()

    def show_brightness(self):
        if not self.brightness_enabled or self.hover_position is None or not self.isVisible():
            return
        pixel = self.image_pixel(self.hover_position)
        if pixel is None:
            return
        x, y = pixel
        color = self.source_image.pixelColor(x, y)
        # Encoded RGB luma (BT.601 weights), not physical luminance in cd/m².
        value = int(0.299*color.red() + 0.587*color.green() + 0.114*color.blue() + 0.5)
        QToolTip.showText(self.viewport().mapToGlobal(self.hover_position),
                         '像素 ({}, {})\n亮度：{} / 255'.format(x, y, value), self.viewport())

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if event.buttons() == Qt.NoButton:
            self.schedule_hover(event.pos())
        else:
            self.cancel_hover()

    def mousePressEvent(self, event):
        self.cancel_hover()
        super().mousePressEvent(event)

    def viewportEvent(self, event):
        if event.type() in (QEvent.Leave, QEvent.Hide) and hasattr(self, 'hover_timer'):
            self.cancel_hover()
        return super().viewportEvent(event)

    def set_image(self, image):
        self.cancel_hover()
        self.source_image = image
        old_size = self.item.pixmap().size()
        self.item.setPixmap(QPixmap.fromImage(image))
        self.scene().setSceneRect(self.item.boundingRect())
        if not self.manual or old_size != image.size():
            self.fit()

    def fit(self):
        self.cancel_hover()
        if not self.item.pixmap().isNull():
            self.fitInView(self.item, Qt.KeepAspectRatio)
        self.manual = False

    def wheelEvent(self, event):
        self.cancel_hover()
        factor = 1.2 if event.angleDelta().y() > 0 else 1/1.2
        if 0.03 < self.transform().m11()*factor < 20:
            self.scale(factor, factor)
            self.manual = True
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.manual:
            self.fit()


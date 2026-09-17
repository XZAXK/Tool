"""Shared video widgets and input filters."""
import math
from PyQt5.QtCore import Qt, QTimer, QEvent, pyqtSignal, QRectF
from PyQt5.QtGui import QPixmap, QPainter, QImage, QCursor, QColor
from PyQt5.QtWidgets import (QPushButton, QGraphicsView, QGraphicsScene, QToolTip,
                            QSlider, QStyle, QStyleOptionSlider)

VIDEOS = '视频 (*.mp4 *.mkv *.avi *.mov *.webm *.m4v);;所有文件 (*)'


def button(text, layout, callback):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    layout.addWidget(widget)
    return widget


class TimelineSlider(QSlider):
    """Absolute mouse seeking, separate from programmatic playback updates."""
    seekRequested = pyqtSignal(int)
    scrubStarted = pyqtSignal()

    def __init__(self):
        super().__init__(Qt.Horizontal)
        self.setTracking(False)
        self.selection = None

    def track_geometry(self):
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        groove = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderGroove, self)
        handle = self.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, self)
        return option, groove, handle

    def value_at(self, position):
        option, groove, handle = self.track_geometry()
        span = max(1, groove.width()-handle.width())
        offset = position.x()-groove.x()-handle.width()//2
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                              max(0,min(span,offset)), span, option.upsideDown)

    def request_at(self, position):
        value = self.value_at(position)
        self.setValue(value)
        self.seekRequested.emit(value)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        self.setFocus()
        self.scrubStarted.emit()
        self.setSliderDown(True)
        self.request_at(event.pos())
        event.accept()

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.request_at(event.pos())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
            self.request_at(event.pos())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        self.scrubStarted.emit()
        previous = self.value()
        super().keyPressEvent(event)
        if self.value() != previous:
            self.seekRequested.emit(self.value())

    def wheelEvent(self, event):
        self.scrubStarted.emit()
        previous = self.value()
        super().wheelEvent(event)
        if self.value() != previous:
            self.seekRequested.emit(self.value())

    def set_frame_value(self, value):
        if not self.isSliderDown():
            self.blockSignals(True)
            self.setValue(value)
            self.blockSignals(False)

    def set_selection(self, start, end):
        self.selection = (start, end)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.selection is None or self.maximum() <= self.minimum():
            return
        option, groove, handle = self.track_geometry()
        span = max(1, groove.width()-handle.width())
        start,end = self.selection
        start = max(self.minimum(),min(self.maximum(),start))
        end = max(self.minimum(),min(self.maximum(),end))
        x1 = groove.x()+handle.width()/2+span*(start-self.minimum())/(self.maximum()-self.minimum())
        x2 = groove.x()+handle.width()/2+span*(end-self.minimum())/(self.maximum()-self.minimum())
        painter = QPainter(self)
        painter.fillRect(QRectF(x1, groove.center().y()+5, max(2,x2-x1), 4), QColor('#219b88'))
        painter.end()


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

    def clear_image(self):
        self.cancel_hover()
        self.source_image = QImage()
        self.item.setPixmap(QPixmap())
        self.scene().setSceneRect(self.item.boundingRect())
        self.manual = False

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
        if old_size != image.size():
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


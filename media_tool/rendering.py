"""Convert decoded video pixels for Qt display and image export."""
import cv2
from PyQt5.QtGui import QImage


def to_image(frame):
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()



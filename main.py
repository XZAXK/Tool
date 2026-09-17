"""Run with: python main.py"""
import sys
from pathlib import Path

from PyQt5.QtWidgets import QApplication
from media_tool.ui import MainWindow
from media_tool import __version__


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('帧析 · 视频工具')
    app.setApplicationVersion(__version__)
    app.setStyle('Fusion')
    window = MainWindow(Path(__file__).resolve().parent)
    window.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())

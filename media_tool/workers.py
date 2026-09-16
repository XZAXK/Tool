import threading
from PyQt5.QtCore import QThread, pyqtSignal


class Job(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(self.function(self.progress.emit, self.cancel))
        except Exception as error:
            self.failed.emit(str(error) or type(error).__name__)


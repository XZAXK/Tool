"""Main window and independent clip/convert pages."""
from pathlib import Path
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTabWidget, QGroupBox, QFormLayout, QDoubleSpinBox, QComboBox, QLineEdit,
    QFileDialog, QMessageBox, QProgressBar)
from PyQt5.QtCore import Qt
from .media import inspect_video, transcode
from .frame_store import FrameStore
from .frame_page import FramePage
from .widgets import button, VIDEOS
from .workers import Job


class ProcessPage(QWidget):
    def __init__(self, window, clipping=False):
        super().__init__()
        self.window, self.clipping = window, clipping
        self.info = None
        layout = QVBoxLayout(self)
        heading = QLabel('视频剪辑' if clipping else '视频格式转换')
        heading.setObjectName('heading')
        layout.addWidget(heading)
        description = ('选择一个时间区间，截取并保存为新视频。' if clipping else '选择输出格式，转换并保存为新视频。')
        layout.addWidget(QLabel(description + ' 保留首条音轨（如有）。'))
        group = QGroupBox('处理设置')
        form = QFormLayout(group)
        source_row = QHBoxLayout()
        self.source = QLineEdit()
        self.source.setReadOnly(True)
        self.source.setPlaceholderText('选择视频文件')
        source_row.addWidget(self.source)
        button('浏览…', source_row, self.choose_source)
        form.addRow('输入视频', source_row)
        self.details = QLabel('尚未选择视频')
        form.addRow('', self.details)
        self.start, self.end = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.start, self.end):
            spin.setDecimals(3)
            spin.setSuffix(' 秒')
            spin.setRange(0, 999999)
        if clipping:
            form.addRow('起始时间（包含）', self.start)
            form.addRow('结束时间（不包含）', self.end)
        self.format = QComboBox()
        self.format.addItems(['MP4', 'MKV', 'AVI'])
        form.addRow('输出格式', self.format)
        self.output = QLineEdit()
        self.output.setReadOnly(True)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output)
        button('保存到…', output_row, self.choose_output)
        form.addRow('输出文件', output_row)
        self.format.currentTextChanged.connect(self.reset_output)
        layout.addWidget(group)
        actions = QHBoxLayout()
        self.execute = button('开始剪辑' if clipping else '开始转换', actions, self.process)
        self.cancel_button = button('取消处理', actions, self.cancel)
        self.cancel_button.setEnabled(False)
        actions.addStretch()
        layout.addLayout(actions)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.message = QLabel('输出为新文件，原视频保留。')
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.message)
        layout.addStretch()

    def choose_source(self):
        if self.window.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, '选择视频', '', VIDEOS)
        if path:
            self.window.run_job('读取视频信息…', lambda p,c: inspect_video(path), self.set_source)

    def set_source(self, info):
        self.info = info
        self.source.setText(info.path)
        self.details.setText('{}×{} · {:.3f} 秒 · {:.3f} FPS'.format(info.width, info.height, info.duration, info.fps))
        self.start.setMaximum(info.duration)
        self.end.setMaximum(info.duration)
        self.start.setValue(0)
        self.end.setValue(info.duration)
        self.output.clear()

    def reset_output(self):
        self.output.clear()

    def choose_output(self):
        ext = self.format.currentText().lower()
        path, _ = QFileDialog.getSaveFileName(self, '选择新的输出文件', '', '{} 视频 (*.{})'.format(ext.upper(), ext))
        if path:
            if Path(path).suffix.lower() != '.'+ext:
                path += '.'+ext
            self.output.setText(path)

    def process(self):
        if self.window.busy:
            return
        if not self.info or not self.output.text():
            return self.window.error('请先选择输入视频和输出文件。')
        self.window.frames.pause()
        source, output = self.info.path, self.output.text()
        start = self.start.value() if self.clipping else None
        end = min(self.end.value(), self.info.duration) if self.clipping else None
        self.message.setText('正在处理…')
        self.progress.setValue(0)
        self.cancel_button.setEnabled(True)
        self.execute.setEnabled(False)
        def done(path):
            self.message.setText('处理完成：' + path)
            self.progress.setValue(100)
        self.window.run_job('正在处理视频…', lambda p,c: transcode(source, output, start, end, c, p), done,
                            progress=self.progress.setValue, cleanup=self.finished, failure=self.failed)

    def failed(self, message):
        self.message.setText(message)

    def finished(self):
        self.cancel_button.setEnabled(False)
        self.execute.setEnabled(True)

    def cancel(self):
        if self.window.job:
            self.window.job.cancel.set()
            self.message.setText('正在取消…')


class MainWindow(QMainWindow):
    def __init__(self, root):
        super().__init__()
        self.root = Path(root)
        self.store = FrameStore(self.root / '.demo-data' / 'frames.sqlite3')
        self.job = None
        self.busy = False
        self.setWindowTitle('帧析 · 视频与图像处理工具 Demo')
        self.resize(1450, 850)
        self.setMinimumSize(1150, 720)
        container = QWidget()
        layout = QVBoxLayout(container)
        title = QLabel('帧析  /  本地视频工作台')
        title.setObjectName('heading')
        layout.addWidget(title)
        self.tabs = QTabWidget()
        self.frames = FramePage(self)
        self.clip = ProcessPage(self, True)
        self.convert = ProcessPage(self)
        self.tabs.addTab(self.frames, '帧标记与导出')
        self.tabs.addTab(self.clip, '视频剪辑')
        self.tabs.addTab(self.convert, '格式转换')
        self.tabs.currentChanged.connect(lambda _: self.frames.pause())
        layout.addWidget(self.tabs)
        self.setCentralWidget(container)
        self.statusBar().showMessage('就绪 · 导入视频或载入演示视频开始标记')
        self.setStyleSheet('''
            QWidget { font-family: "Microsoft YaHei"; font-size: 12px; }
            QMainWindow, QTabWidget::pane { background: #f4f6f9; }
            QLabel#heading { font-size: 23px; font-weight: 600; color: #173d52; padding: 12px; }
            QPushButton { padding: 8px 12px; background: #e5eef2; color: #163e54; border: 1px solid #c3d4df; border-radius: 5px; }
            QPushButton:hover { background: #d3e7ee; }
            QPushButton:disabled { color: #909ba2; background: #edf0f2; }
            QGroupBox { font-weight: 600; border: 1px solid #d1dbe2; border-radius: 6px; margin-top: 12px; padding: 12px 8px 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; }
            QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 5px; background: white; border: 1px solid #ccd5df; border-radius: 3px; }
            QListWidget { background: white; border: 1px solid #d1dbe2; }
            QListWidget::item { padding: 12px 5px; }
            QListWidget::item:selected { background: #d8ebf2; color: #173d52; }
            QTabBar::tab { padding: 12px 28px; }
            QTabBar::tab:selected { background: #d8ebf2; color: #173d52; }
        ''')

    def run_job(self, message, function, done, frame_job=False, progress=None, cleanup=None, failure=None):
        if self.busy:
            return
        self.busy = True
        self.frames.list.setEnabled(False)
        self.statusBar().showMessage(message)
        job = Job(function, self)
        self.job = job
        state = {}
        job.result.connect(lambda value: state.update(result=value))
        job.failed.connect(lambda error: state.update(error=error))
        if progress:
            job.progress.connect(progress)
        def finish():
            self.busy = False
            self.job = None
            self.frames.list.setEnabled(True)
            if cleanup:
                cleanup()
            if 'error' in state:
                self.frames.pause()
                if failure:
                    failure(state['error'])
                if frame_job:
                    self.frames.panel.setEnabled(False)
                self.error(state['error'])
            else:
                self.statusBar().showMessage('就绪 · 本地记录自动保存')
                try:
                    done(state.get('result'))
                except Exception as error:
                    self.error(str(error))
            job.deleteLater()
        job.finished.connect(finish)
        job.start()

    def error(self, message):
        self.statusBar().showMessage(message[:180])
        QMessageBox.warning(self, '无法完成操作', message)

    def inform(self, message):
        QMessageBox.information(self, '完成', message)

    def closeEvent(self, event):
        if self.busy:
            self.statusBar().showMessage('后台任务尚未结束，请等待；视频处理中可先点击取消。')
            event.ignore()
            return
        self.frames.pause()
        if self.frames.reader:
            self.frames.reader.close()
        self.store.close()
        event.accept()

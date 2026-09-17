"""Video frame selection UI, independent of detection and review workflows."""
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                            QListWidget, QSplitter, QSpinBox, QCheckBox,
                            QComboBox, QFileDialog, QShortcut)

from .demo import generate_sample
from .exports import export_images
from .frame_store import fingerprint
from .media import FrameReader, inspect_video
from .rendering import to_image
from .widgets import ImageView, TimelineSlider, button, VIDEOS


class FramePage(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.tasks = []
        self.current = None
        self.index = 0
        self.loading = False
        self.frame_ready = False
        self.reader = None
        self.reader_path = None
        self.pending_frame = None
        self.window.job_idle.connect(self.flush_pending_frame)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        button('导入视频', toolbar, self.import_files)
        button('载入演示视频', toolbar, self.load_demo)
        button('恢复上次任务', toolbar, self.restore)
        toolbar.addStretch()
        self.total = QLabel('尚未导入视频')
        toolbar.addWidget(self.total)
        layout.addLayout(toolbar)
        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        side.addWidget(QLabel('视频列表 · 最多 10 个'))
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.switch_task)
        side.addWidget(self.list)
        splitter.addWidget(sidebar)
        center = QWidget()
        middle = QVBoxLayout(center)
        self.view = ImageView()
        middle.addWidget(self.view, 1)
        self.frame_label = QLabel('导入视频后，标记需要保存为图片的帧。')
        middle.addWidget(self.frame_label)
        self.slider = TimelineSlider()
        self.slider.scrubStarted.connect(self.pause)
        self.slider.seekRequested.connect(self.seek)
        self.slider.setEnabled(False)
        middle.addWidget(self.slider)
        nav = QHBoxLayout()
        button('上一帧', nav, lambda: self.step(-1))
        self.play = button('播放', nav, self.toggle_play)
        button('下一帧', nav, lambda: self.step(1))
        self.brightness = QPushButton('亮度审查')
        self.brightness.setCheckable(True)
        self.brightness.setEnabled(False)
        self.brightness.setToolTip('仅暂停时可开启；悬停 0.2 秒显示原图像素亮度（0–255）')
        self.brightness.toggled.connect(self.set_brightness)
        nav.addWidget(self.brightness)
        nav.addStretch()
        nav.addWidget(QLabel('跳转帧（从 0 开始）'))
        self.jump = QSpinBox()
        nav.addWidget(self.jump)
        button('跳转', nav, lambda: self.seek(self.jump.value()))
        middle.addLayout(nav)
        splitter.addWidget(center)
        self.panel = QWidget()
        controls = QVBoxLayout(self.panel)
        controls.addWidget(QLabel('帧标记'))
        self.selected = QCheckBox('标记当前帧用于导出')
        self.selected.stateChanged.connect(self.save_mark)
        controls.addWidget(self.selected)
        controls.addWidget(QLabel('已标记帧 · 双击定位'))
        self.marks = QListWidget()
        self.marks.itemDoubleClicked.connect(lambda item: self.locate_mark(item.data(Qt.UserRole)))
        controls.addWidget(self.marks, 1)
        button('取消选中条目的标记', controls, self.unmark_item)
        self.image_format = QComboBox()
        self.image_format.addItems(['PNG', 'JPG'])
        controls.addWidget(self.image_format)
        button('导出当前视频已标记帧', controls, self.export_pictures)
        hint = QLabel('标记和查看位置自动保存。\n图片保持视频原分辨率。\n滚轮缩放 · 拖动平移 · 双击复位')
        hint.setWordWrap(True)
        controls.addWidget(hint)
        self.panel.setEnabled(False)
        splitter.addWidget(self.panel)
        splitter.setSizes([220, 900, 260])
        for key, callback in [('Left', lambda: self.step(-1)), ('Right', lambda: self.step(1)),
                              ('Space', self.toggle_play), ('M', self.toggle_mark)]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)

    @property
    def store(self):
        return self.window.store

    def pause(self):
        self.timer.stop()
        self.play.setText('播放')
        self.refresh_brightness()

    def refresh_brightness(self):
        available = self.frame_ready and not self.timer.isActive()
        if not available:
            self.brightness.setChecked(False)
            self.view.set_brightness_enabled(False)
        self.brightness.setEnabled(available)

    def set_brightness(self, enabled):
        if enabled and (self.timer.isActive() or not self.frame_ready):
            self.brightness.setChecked(False)
            return
        self.view.set_brightness_enabled(enabled)

    def import_files(self):
        if self.window.busy:
            return
        self.pause()
        paths, _ = QFileDialog.getOpenFileNames(self, '选择视频（最多10个）', '', VIDEOS)
        if len(paths)+len(self.tasks) > 10:
            return self.window.error('当前列表加上新视频不能超过 10 个。')
        if paths:
            self.import_paths(paths)

    def import_paths(self, paths):
        self.pause()
        def work(progress, cancel):
            successes, failures = [], []
            for path in paths:
                try:
                    info = inspect_video(path, frame_limits=True)
                    successes.append(dict(info=info, key=fingerprint(path)))
                except Exception as error:
                    failures.append('{}：{}'.format(Path(path).name, error))
            return successes, failures
        self.window.run_job('正在读取视频…', work, self.imported)

    def imported(self, result):
        successes, failures = result
        for task in successes:
            if any(t['key'] == task['key'] for t in self.tasks):
                continue
            if len(self.tasks) >= 10:
                failures.append('已达10个视频上限，其余视频未导入。')
                break
            self.store.register(task['key'], task['info'].path)
            self.tasks.append(task)
            self.list.addItem(Path(task['info'].path).name)
        self.update_marks()
        if self.tasks:
            self.list.setCurrentRow(len(self.tasks)-1)
        if failures:
            self.window.error('\n\n'.join(failures))

    def load_demo(self):
        if self.window.busy:
            return
        if len(self.tasks) >= 10:
            return self.window.error('列表已达 10 个视频。')
        self.window.run_job('正在准备本地演示视频…',
                            lambda p,c: generate_sample(self.window.root / '.demo-data' / 'sample'),
                            lambda path: self.import_paths([path]))

    def restore(self):
        if self.window.busy:
            return
        saved = self.store.videos()[-10:]
        if saved:
            self.import_paths([r['path'] for r in saved])
        else:
            self.window.statusBar().showMessage('没有可恢复的任务。')

    def switch_task(self, row):
        if row < 0 or row >= len(self.tasks):
            return
        self.pause()
        self.current = self.tasks[row]
        self.pending_frame = None
        self.frame_ready = False
        self.panel.setEnabled(False)
        self.view.clear_image()
        self.frame_label.setText('正在载入当前视频…')
        self.slider.setEnabled(False)
        info = self.current['info']
        self.jump.setRange(0, info.frame_count-1)
        self.slider.blockSignals(True)
        self.slider.setRange(0, info.frame_count-1)
        self.slider.blockSignals(False)
        self.update_marks()
        self.request_frame(min(self.store.position(self.current['key']), info.frame_count-1))

    def seek(self, index):
        self.pause()
        self.request_frame(index)

    def flush_pending_frame(self):
        if self.window.busy or self.pending_frame is None or not self.current:
            return
        key,index = self.pending_frame
        self.pending_frame = None
        if key == self.current['key']:
            self.request_frame(index)

    def request_frame(self, index):
        if not self.current:
            return
        if not 0 <= index < self.current['info'].frame_count:
            return
        key = self.current['key']
        if self.window.busy:
            self.pending_frame = (key,index)
            return
        if self.frame_ready and index == self.index:
            self.slider.set_frame_value(index)
            return
        self.pending_frame = None
        self.frame_ready = False
        self.refresh_brightness()
        path = self.current['info'].path
        def work(progress, cancel):
            if self.reader_path != path:
                if self.reader:
                    self.reader.close()
                self.reader = FrameReader(path)
                self.reader_path = path
            return key,index, to_image(self.reader.read(index))
        self.window.run_job('读取第 {} 帧…'.format(index), work, self.show_frame,
                            frame_job=True, failure=self.frame_failed)

    def frame_failed(self, message):
        self.pause()
        self.pending_frame = None
        self.frame_ready = False
        self.refresh_brightness()
        self.slider.set_frame_value(self.index)

    def show_frame(self, result):
        key,index,image = result
        if self.current['key'] != key or (self.pending_frame is not None and self.pending_frame != (key,index)):
            return
        self.index = index
        self.view.set_image(image)
        self.frame_ready = True
        self.refresh_brightness()
        self.loading = True
        self.selected.setChecked(self.index in self.store.marked(self.current['key']))
        self.slider.set_frame_value(self.index)
        self.jump.setValue(self.index)
        self.loading = False
        self.store.set_position(self.current['key'], self.index)
        self.panel.setEnabled(True)
        self.slider.setEnabled(True)
        info = self.current['info']
        self.frame_label.setText('帧 {} / {} · {:.3f} 秒 · {}×{} · M 标记/取消'.format(
            self.index, info.frame_count-1, self.index/info.fps, info.width, info.height))

    def save_mark(self):
        if self.loading or not self.current:
            return
        if not self.frame_ready:
            self.loading = True
            self.selected.setChecked(self.index in self.store.marked(self.current['key']))
            self.loading = False
            return
        self.store.set_mark(self.current['key'], self.index, self.selected.isChecked())
        self.update_marks()

    def toggle_mark(self):
        if self.panel.isEnabled() and not self.window.busy:
            self.selected.toggle()

    def unmark_item(self):
        item = self.marks.currentItem()
        if item is None or not self.current:
            return
        index = item.data(Qt.UserRole)
        self.store.set_mark(self.current['key'], index, False)
        if index == self.index:
            self.selected.setChecked(False)
        self.update_marks()

    def update_marks(self):
        count = 0
        for i, task in enumerate(self.tasks):
            amount = len(self.store.marked(task['key']))
            count += amount
            self.list.item(i).setText('{}\n已标记 {} 帧'.format(Path(task['info'].path).name, amount))
        self.total.setText('{} 个视频 · 已标记 {} 帧'.format(len(self.tasks), count))
        previous = self.marks.currentItem()
        previous_index = previous.data(Qt.UserRole) if previous else None
        self.marks.clear()
        if self.current:
            for index in self.store.marked(self.current['key']):
                self.marks.addItem('帧 {} · {:.3f} 秒'.format(index, index/self.current['info'].fps))
                self.marks.item(self.marks.count()-1).setData(Qt.UserRole, index)
                if index == previous_index:
                    self.marks.setCurrentRow(self.marks.count()-1)

    def locate_mark(self, index):
        self.pause()
        self.request_frame(index)

    def step(self, delta):
        self.pause()
        if self.current:
            self.request_frame(self.index+delta)

    def toggle_play(self):
        if not self.current:
            return
        if self.timer.isActive():
            self.pause()
        else:
            self.timer.start(max(1, int(1000/self.current['info'].fps)))
            self.play.setText('暂停')
            self.refresh_brightness()

    def advance(self):
        if self.window.busy:
            return
        if self.index >= self.current['info'].frame_count-1:
            self.pause()
        else:
            self.request_frame(self.index+1)

    def export_pictures(self):
        self.pause()
        if not self.current or self.window.busy:
            return
        indices = self.store.marked(self.current['key'])
        if not indices:
            return self.window.error('请先标记需要导出的帧。')
        parent = QFileDialog.getExistingDirectory(self, '选择图片导出目录')
        if not parent:
            return
        folder = Path(parent) / ('帧析_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        task, ext = self.current, self.image_format.currentText().lower()
        self.window.run_job('正在导出已标记帧…', lambda p,c: export_images(task['info'], indices, folder, ext, p),
                            lambda count: self.window.inform('已导出 {} 张图片到\n{}'.format(count, folder)))

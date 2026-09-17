"""Visual clip selection with independent decoding and bounded playback."""
import math

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel

from .media import FrameReader
from .rendering import to_image
from .widgets import ImageView, TimelineSlider, button


class ClipPreview(QWidget):
    rangeChanged = pyqtSignal(float, float)

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.info = None
        self.index = 0
        self.start = self.end = 0.0
        self.reader = None
        self.reader_path = None
        self.pending = None
        self.ready = False
        self.selection_playing = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.window.job_idle.connect(self.flush_pending)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.view = ImageView()
        self.view.setMinimumSize(400,240)
        layout.addWidget(self.view,1)
        self.position = QLabel('选择视频后，在画面中定位剪辑起止帧。')
        layout.addWidget(self.position)
        self.slider = TimelineSlider()
        self.slider.scrubStarted.connect(self.pause)
        self.slider.seekRequested.connect(self.seek)
        layout.addWidget(self.slider)
        navigation = QHBoxLayout()
        button('上一帧', navigation, lambda: self.seek(self.index-1))
        self.play = button('播放', navigation, self.toggle_play)
        button('下一帧', navigation, lambda: self.seek(self.index+1))
        self.range_play = button('预览选区', navigation, self.play_selection)
        navigation.addStretch()
        layout.addLayout(navigation)
        selection = QHBoxLayout()
        self.in_button = button('当前帧设为起点', selection, self.pick_start)
        self.out_button = button('当前帧设为终点（含此帧）', selection, self.pick_end)
        button('选择全部', selection, self.select_all)
        layout.addLayout(selection)
        self.range_label = QLabel('绿色时间轴标出将要保留的区间。')
        self.range_label.setWordWrap(True)
        layout.addWidget(self.range_label)
        self.setEnabled(False)

    def load(self, info):
        self.pause()
        self.info = info
        self.pending = None
        self.ready = False
        self.index = 0
        self.setEnabled(True)
        self.slider.setRange(0,info.frame_count-1)
        self.view.clear_image()
        self.set_range(0,info.duration)
        self.request_frame(0)

    def set_range(self, start, end):
        self.start, self.end = start,end
        self.pause()
        valid = self.info is not None and 0 <= start < end <= self.info.duration+0.000001
        self.range_play.setEnabled(valid)
        if not valid:
            self.slider.set_selection(0,0)
            self.range_label.setText('请选择有效区间：起点必须早于终点，且不能超出视频时长。')
            return
        first,last = self.range_frames()
        self.slider.set_selection(first,min(self.info.frame_count,last))
        self.range_label.setText('选区 {:.3f}–{:.3f} 秒 · 时长 {:.3f} 秒\n终点时间不包含；画面设终点时自动取当前帧之后的边界。'.format(start,end,end-start))

    def range_frames(self):
        # Spinboxes retain 6 decimal places; tolerate <1e-4 frame rounding.
        first = max(0,int(math.ceil(self.start*self.info.fps-0.0001)))
        last = min(self.info.frame_count,int(math.ceil(self.end*self.info.fps-0.0001)))
        return first,last

    def pick_start(self):
        if not self.ready or not self.info:
            return
        self.pause()
        start = self.index/self.info.fps
        if start >= self.end:
            self.range_label.setText('当前帧不早于终点，请先调整终点。')
            return
        self.rangeChanged.emit(start,self.end)

    def pick_end(self):
        if not self.ready or not self.info:
            return
        self.pause()
        end = min((self.index+1)/self.info.fps,self.info.duration)
        if end <= self.start:
            self.range_label.setText('当前帧不晚于起点，请先调整起点。')
            return
        self.rangeChanged.emit(self.start,end)

    def select_all(self):
        if self.info:
            self.rangeChanged.emit(0,self.info.duration)

    def pause(self):
        self.timer.stop()
        self.selection_playing = False
        self.play.setText('播放')

    def seek(self, index):
        self.pause()
        self.request_frame(index)

    def request_frame(self, index):
        if self.info is None or not 0 <= index < self.info.frame_count:
            return
        path = self.info.path
        if self.window.busy:
            self.pending = (path,index)
            return
        if self.ready and self.index == index:
            self.slider.set_frame_value(index)
            return
        self.pending = None
        self.ready = False
        def work(progress,cancel):
            if self.reader_path != path:
                if self.reader:
                    self.reader.close()
                self.reader = FrameReader(path)
                self.reader_path = path
            return path,index,to_image(self.reader.read(index))
        self.window.run_job('正在读取剪辑预览…',work,self.show_frame,
                            frame_job=True,failure=self.failed)

    def flush_pending(self):
        if self.window.busy or self.pending is None or self.info is None:
            return
        path,index = self.pending
        self.pending = None
        if path == self.info.path:
            self.request_frame(index)

    def show_frame(self,result):
        path,index,image = result
        if path != self.info.path or (self.pending is not None and self.pending != (path,index)):
            return
        self.index = index
        self.ready = True
        self.view.set_image(image)
        self.slider.set_frame_value(index)
        self.position.setText('帧 {} / {} · {:.3f} 秒 · {}×{}'.format(
            index,self.info.frame_count-1,index/self.info.fps,self.info.width,self.info.height))

    def failed(self,message):
        self.pause()
        self.pending = None
        self.ready = False
        self.position.setText('预览失败：'+message)

    def toggle_play(self):
        if self.timer.isActive():
            self.pause()
        elif self.info:
            self.selection_playing = False
            if self.index >= self.info.frame_count-1:
                self.request_frame(0)
            self.timer.start(max(1,int(1000/self.info.fps)))
            self.play.setText('暂停')

    def play_selection(self):
        if not self.info or not 0 <= self.start < self.end <= self.info.duration+0.000001:
            return
        first,last = self.range_frames()
        if first >= last:
            self.range_label.setText('所选时间区间内没有可预览的视频帧。')
            return
        self.pause()
        self.selection_playing = True
        self.request_frame(first)
        self.timer.start(max(1,int(1000/self.info.fps)))
        self.play.setText('暂停')

    def advance(self):
        if self.window.busy or not self.ready:
            return
        last = self.range_frames()[1] if self.selection_playing else self.info.frame_count
        if self.index >= last-1:
            self.pause()
        else:
            self.request_frame(self.index+1)

    def close_reader(self):
        self.pause()
        self.pending = None
        if self.reader:
            self.reader.close()
            self.reader = None
            self.reader_path = None

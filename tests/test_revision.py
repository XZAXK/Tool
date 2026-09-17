"""Regression tests for timeline seeking and stable frame-page controls."""
import os
import tempfile
import time
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

if os.name != 'nt':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt5.QtCore import Qt, QPoint, QObject, QEvent
from PyQt5.QtTest import QTest, QSignalSpy
from PyQt5.QtWidgets import QApplication

from media_tool.demo import generate_sample
from media_tool.media import FrameReader, inspect_video
from media_tool.ui import MainWindow


class EnabledChanges(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, obj, event):
        if event.type() == QEvent.EnabledChange:
            self.count += 1
        return False


class UiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = generate_sample(self.root/'sample')
        self.errors = []
        self.window = MainWindow(self.root)
        self.window.error = self.errors.append
        self.window.show()
        self.app.processEvents()
        self.page = self.window.frames
        self.page.import_paths([self.video])
        self.wait_idle()

    def wait_idle(self, timeout=15):
        deadline = time.monotonic()+timeout
        # Process a full event-loop turn even if a deferred request is pending.
        while True:
            self.app.processEvents()
            if not self.window.busy:
                self.app.processEvents()
                if not self.window.busy:
                    break
            if time.monotonic() > deadline:
                self.fail('Qt operation timed out')
            time.sleep(0.005)
        self.assertFalse(self.errors, self.errors)

    def tearDown(self):
        self.page.pause()
        if hasattr(self.window.clip, 'preview'):
            self.window.clip.preview.pause()
        self.wait_idle()
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def test_timeline_click_seeks_to_clicked_position_and_pauses(self):
        slider = self.page.slider
        self.page.toggle_play()
        QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(int(slider.width()*0.75), slider.height()//2))
        self.wait_idle()
        self.assertFalse(self.page.timer.isActive(), 'Timeline interaction must pause playback')
        self.assertAlmostEqual(self.page.index, 107, delta=3)
        self.assertEqual(slider.value(), self.page.index)
        QTest.qWait(250)
        self.assertEqual(slider.value(), self.page.index)

    def test_frame_change_does_not_disable_sidebar_or_rebuild_marks(self):
        self.page.selected.setChecked(True)
        self.page.marks.setCurrentRow(0)
        resets = QSignalSpy(self.page.marks.model().modelReset)
        watcher = EnabledChanges()
        list_watcher = EnabledChanges()
        self.page.panel.installEventFilter(watcher)
        self.page.list.installEventFilter(list_watcher)
        self.page.request_frame(10)
        self.wait_idle()
        self.assertEqual(watcher.count, 0, 'Per-frame disabling causes visual flashing')
        self.assertEqual(list_watcher.count,0)
        self.assertEqual(len(resets), 0, 'Frame changes must retain mark list items')
        self.assertEqual(self.page.marks.currentRow(), 0)

    def test_timeline_drag_commits_release_position(self):
        slider = self.page.slider
        self.page.toggle_play()
        QTest.mousePress(slider,Qt.LeftButton,pos=QPoint(slider.width()//4,slider.height()//2))
        self.wait_idle()
        QTest.mouseMove(slider,QPoint(slider.width()//2,slider.height()//2))
        QTest.mouseRelease(slider,Qt.LeftButton,pos=QPoint(slider.width()-1,slider.height()//2))
        self.wait_idle()
        self.assertFalse(self.page.timer.isActive())
        self.assertEqual(self.page.index,143)
        self.assertEqual(slider.value(),143)
        QTest.mouseClick(slider,Qt.LeftButton,pos=QPoint(0,slider.height()//2))
        self.wait_idle()
        self.assertEqual(self.page.index,0)

    def test_switch_video_during_decode_discards_previous_result(self):
        second = self.root/'second.mp4'
        import cv2
        import numpy as np
        writer = cv2.VideoWriter(str(second),cv2.VideoWriter_fourcc(*'mp4v'),24,(320,180))
        self.assertTrue(writer.isOpened())
        for _ in range(24):
            writer.write(np.full((180,320,3),100,np.uint8))
        writer.release()
        self.page.import_paths([str(second)])
        self.wait_idle()
        self.page.list.setCurrentRow(0)
        self.wait_idle()
        started,release = threading.Event(),threading.Event()
        original = FrameReader.read
        def slow_read(reader,index):
            if reader.path == self.page.tasks[0]['info'].path and index == 10:
                started.set()
                release.wait(5)
            return original(reader,index)
        try:
            with patch.object(FrameReader,'read',slow_read):
                self.page.request_frame(10)
                self.assertTrue(started.wait(2))
                self.page.list.setCurrentRow(1)
                release.set()
                self.wait_idle()
            self.assertEqual(self.page.index,0)
            self.assertEqual(self.page.view.source_image.width(),320)
            self.assertEqual(self.page.slider.maximum(),23)
        finally:
            release.set()

    def test_latest_seek_is_not_dropped_while_decode_is_busy(self):
        started, release = threading.Event(), threading.Event()
        original = FrameReader.read
        def slow_read(reader, index):
            if index == 10:
                started.set()
                release.wait(5)
            return original(reader, index)
        try:
            with patch.object(FrameReader, 'read', slow_read):
                self.page.request_frame(10)
                self.assertTrue(started.wait(2))
                self.page.request_frame(55)
                release.set()
                self.wait_idle()
            self.assertEqual(self.page.index,55)
            self.assertEqual(self.page.slider.value(),55)
        finally:
            release.set()

    def test_visual_clip_selection_preview_and_actual_export(self):
        clip = self.window.clip
        self.window.tabs.setCurrentIndex(1)
        clip.set_source(inspect_video(self.video))
        self.wait_idle()
        preview = clip.preview
        preview.seek(24)
        self.wait_idle()
        preview.pick_start()
        preview.seek(47)
        self.wait_idle()
        preview.pick_end()
        self.assertAlmostEqual(clip.start.value(),1,places=5)
        self.assertAlmostEqual(clip.end.value(),2,places=5)
        self.assertEqual(preview.slider.selection,(24,48))
        capture = Path(__file__).resolve().parents[1]/'test-output'
        capture.mkdir(exist_ok=True)
        self.window.grab().save(str(capture/'v0.2.0-visual-clip.png'))
        preview.play_selection()
        deadline = time.monotonic()+6
        while preview.timer.isActive() or self.window.busy:
            self.app.processEvents()
            QTest.qWait(5)
            if time.monotonic() > deadline:
                self.fail('Selection preview did not stop')
        self.assertEqual(preview.index,47)
        self.assertAlmostEqual(clip.start.value(),1,places=5)
        output = self.root/'visual-clip.mp4'
        clip.output.setText(str(output))
        clip.process()
        self.wait_idle()
        result = inspect_video(output)
        self.assertEqual(result.frame_count,24)
        self.assertAlmostEqual(result.duration,1,places=2)

    def test_visual_clip_last_frame_and_manual_range(self):
        self.window.tabs.setCurrentIndex(1)
        clip = self.window.clip
        clip.set_source(inspect_video(self.video))
        self.wait_idle()
        clip.start.setValue(2)
        clip.end.setValue(4)
        self.assertEqual(clip.preview.slider.selection,(48,96))
        clip.preview.seek(143)
        self.wait_idle()
        clip.preview.pick_end()
        self.assertEqual(clip.end.value(),6)
        clip.preview.pick_start()
        self.assertAlmostEqual(clip.start.value(),143/24,places=5)
        clip.start.setValue(6)
        self.assertFalse(clip.preview.range_play.isEnabled())

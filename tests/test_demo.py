import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

if os.name != 'nt':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import cv2
import numpy as np
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QPoint, QPointF, QEvent
from PyQt5.QtGui import QImage, QColor, QMouseEvent
from PyQt5.QtTest import QTest
from media_tool.demo import generate_sample
from media_tool.exports import export_images
from media_tool.media import FrameReader, inspect_video, transcode, find_ffmpeg
from media_tool.frame_store import FrameStore
from media_tool.ui import MainWindow
from media_tool.widgets import ImageView


class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion')
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.video = generate_sample(cls.root/'sample')
        cls.info = inspect_video(cls.video, frame_limits=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_nonsequential_frames_match_sequential_decode(self):
        cap = cv2.VideoCapture(self.video)
        reference = {}
        for index in range(144):
            ok, frame = cap.read()
            self.assertTrue(ok)
            if index in (0, 55, 95, 143):
                reference[index] = frame
        cap.release()
        reader = FrameReader(self.video)
        try:
            for index in (95, 0, 143, 55, 0):
                self.assertTrue(np.array_equal(reader.read(index), reference[index]))
            self.assertLessEqual(reader.bytes, 48*1024*1024)
        finally:
            reader.close()

    def test_clip_convert_and_protect_existing_output(self):
        clipped = self.root/'clip.mp4'
        transcode(self.video, clipped, 1, 2)
        info = inspect_video(clipped)
        self.assertAlmostEqual(info.duration, 1, delta=1/info.fps)
        self.assertEqual(info.frame_count, 24)
        source_reader, clip_reader = FrameReader(self.video), FrameReader(clipped)
        try:
            difference = np.abs(source_reader.read(24).astype(float)-clip_reader.read(0).astype(float)).mean()
            self.assertLess(difference, 4, 'Clip must begin at source second 1, not at an earlier keyframe')
        finally:
            source_reader.close()
            clip_reader.close()
        for ext in ('mkv', 'avi'):
            output = self.root/('converted.'+ext)
            transcode(clipped, output)
            converted = inspect_video(output)
            self.assertEqual((converted.width,converted.height), (960,540))
            self.assertEqual(converted.frame_count,24)
        before = clipped.read_bytes()
        with self.assertRaises(ValueError):
            transcode(self.video, clipped)
        self.assertEqual(clipped.read_bytes(),before)
        with self.assertRaises(ValueError):
            transcode(self.video, self.root/'invalid.mp4', 2, 1)
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ValueError):
            transcode(self.video, self.root/'cancel.mp4', cancel=cancel)
        self.assertFalse((self.root/'cancel.mp4').exists())

    def test_audio_is_retained(self):
        source = self.root/'with-audio.mp4'
        flags = 0x08000000 if os.name == 'nt' else 0
        subprocess.run([find_ffmpeg(), '-hide_banner', '-loglevel', 'error', '-y',
                        '-i', self.video, '-f', 'lavfi', '-i', 'sine=frequency=440:duration=6',
                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac',
                        '-shortest', str(source)], check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, creationflags=flags)
        output = self.root/'audio-clip.mp4'
        transcode(source, output, 1, 2)
        result = subprocess.run([find_ffmpeg(), '-hide_banner', '-loglevel', 'error',
                                 '-i', str(output), '-map', '0:a:0', '-f', 'null', '-'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))

    def wait_for(self, predicate, timeout=20):
        deadline = time.monotonic()+timeout
        while not predicate():
            self.app.processEvents()
            time.sleep(0.005)
            if time.monotonic() > deadline:
                self.fail('Qt asynchronous operation timed out')
        self.app.processEvents()

    def test_marks_persist_and_cancel_without_affecting_other_video(self):
        path = self.root/'marks.sqlite3'
        store = FrameStore(path)
        store.register('one', self.video)
        store.register('two', 'second.mp4')
        for index in (55, 0, 95, 55):
            store.set_mark('one', index, True)
        store.set_mark('two', 55, True)
        store.set_mark('one', 95, False)
        store.set_position('one', 55)
        store.close()
        store = FrameStore(path)
        try:
            self.assertEqual(store.marked('one'), [0,55])
            self.assertEqual(store.marked('two'), [55])
            self.assertEqual(store.position('one'), 55)
        finally:
            store.close()

    def test_gui_mark_export_and_restore(self):
        root = self.root/'ui'
        root.mkdir(exist_ok=True)
        Path(self.video).with_suffix('.json').write_text('invalid JSON', encoding='utf-8')
        errors, notices = [], []
        window = MainWindow(root)
        window.error = errors.append
        window.inform = notices.append
        window.show()
        self.app.processEvents()
        try:
            self.assertEqual(window.tabs.tabText(0), '帧标记与导出')
            with patch('media_tool.frame_page.QFileDialog.getOpenFileNames', return_value=([self.video], '')), \
                    patch('media_tool.frame_page.QFileDialog.getOpenFileName') as marker_dialog:
                window.frames.import_files()
                marker_dialog.assert_not_called()
            self.wait_for(lambda: not window.busy)
            page = window.frames
            self.assertFalse(errors, errors)
            self.assertIsNotNone(page.current)
            for removed in ('reviewed','flags','export_tables','record_format'):
                self.assertFalse(hasattr(page, removed))
            page.selected.setChecked(True)
            page.request_frame(55)
            self.wait_for(lambda: not window.busy)
            page.selected.setChecked(True)
            key = page.current['key']
            self.assertEqual(window.store.marked(key), [0,55])
            page.marks.setCurrentRow(0)
            page.unmark_item()
            self.assertEqual(window.store.marked(key), [55])
            capture = Path(__file__).resolve().parents[1]/'test-output'
            capture.mkdir(exist_ok=True)
            window.grab().save(str(capture/'frame-marking-demo.png'))
            output = root/'images'
            output.mkdir()
            for ext in ('PNG','JPG'):
                page.image_format.setCurrentText(ext)
                with patch('media_tool.frame_page.QFileDialog.getExistingDirectory', return_value=str(output)):
                    page.export_pictures()
                self.wait_for(lambda: not window.busy)
                files = list(output.rglob('*.'+ext.lower()))
                self.assertEqual(len(files),1)
                self.assertEqual(files[0].stem, 'frame_000055')
                pixels = cv2.imdecode(np.fromfile(str(files[0]), dtype=np.uint8), cv2.IMREAD_COLOR)
                self.assertEqual(pixels.shape[:2], (540,960))
                if ext == 'PNG':
                    reader = FrameReader(self.video)
                    try:
                        self.assertTrue(np.array_equal(pixels,reader.read(55)))
                    finally:
                        reader.close()
            self.assertEqual(len(notices),2)
            self.assertFalse(errors,errors)
            page.request_frame(0)
            self.wait_for(lambda: not window.busy)
            page.locate_mark(55)
            self.wait_for(lambda: not window.busy)
            self.assertEqual(page.index,55)
            self.assertTrue(page.selected.isChecked())
        finally:
            window.close()
        window = MainWindow(root)
        window.error = errors.append
        try:
            window.frames.restore()
            self.wait_for(lambda: not window.busy)
            self.assertEqual(window.frames.index,55)
            self.assertEqual(window.store.marked(key),[55])
            self.assertTrue(window.frames.selected.isChecked())
            self.assertFalse(errors,errors)
        finally:
            window.close()

    def test_invalid_export_and_existing_image_are_rejected(self):
        folder = self.root/'invalid-exports'
        with self.assertRaises(ValueError):
            export_images(self.info, [144], folder)
        with self.assertRaises(ValueError):
            export_images(self.info, [0], folder, 'exe')
        export_images(self.info, [0,0], folder)
        self.assertEqual(len(list(folder.iterdir())),1)
        original = (folder/'frame_000000.png').read_bytes()
        with self.assertRaises(ValueError):
            export_images(self.info, [0], folder)
        self.assertEqual((folder/'frame_000000.png').read_bytes(),original)

    def test_brightness_hover_delay_motion_mapping_and_black_bars(self):
        view = ImageView()
        view.resize(420,420)
        image = QImage(200,100,QImage.Format_RGB32)
        image.fill(QColor(255,0,0))
        view.show()
        view.set_image(image)
        self.app.processEvents()
        def move(position):
            event = QMouseEvent(QEvent.MouseMove, QPointF(position), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
            QApplication.sendEvent(view.viewport(),event)
        try:
            with patch('media_tool.widgets.QToolTip.showText') as show:
                view.set_brightness_enabled(True)
                pos = view.mapFromScene(QPointF(50.5,50.5))
                move(pos)
                QTest.qWait(100)
                show.assert_not_called()
                # A movement restarts the complete 200 ms dwell.
                pos = view.mapFromScene(QPointF(80.5,50.5))
                move(pos)
                QTest.qWait(120)
                show.assert_not_called()
                QTest.qWait(130)
                self.assertEqual(show.call_count,1)
                text = show.call_args[0][1]
                self.assertIn('亮度：76 / 255',text)
                self.assertIn('像素 (80, 50)',text)
                show.reset_mock()
                # Letterbox area must not report black as an image pixel.
                move(QPoint(5,5))
                QTest.qWait(250)
                show.assert_not_called()
                # Zoom/pan: values and coordinates still refer to source pixels.
                view.scale(2,2)
                view.centerOn(120,50)
                self.app.processEvents()
                move(view.mapFromScene(QPointF(120.5,50.5)))
                QTest.qWait(250)
                self.assertIn('像素 (120, 50)',show.call_args[0][1])
                self.assertIn('亮度：76 / 255',show.call_args[0][1])
                show.reset_mock()
                move(view.mapFromScene(QPointF(121.5,50.5)))
                QApplication.sendEvent(view.viewport(),QEvent(QEvent.Leave))
                QTest.qWait(250)
                show.assert_not_called()
                move(view.mapFromScene(QPointF(121.5,50.5)))
                view.set_brightness_enabled(False)
                QTest.qWait(250)
                show.assert_not_called()
        finally:
            view.close()

    def test_brightness_cannot_be_enabled_during_playback(self):
        root = self.root/'brightness-ui'
        window = MainWindow(root)
        errors = []
        window.error = errors.append
        window.show()
        try:
            page = window.frames
            self.assertFalse(page.brightness.isEnabled())
            page.import_paths([self.video])
            self.wait_for(lambda: not window.busy)
            self.assertFalse(errors,errors)
            self.assertTrue(page.brightness.isEnabled())
            page.brightness.click()
            self.assertTrue(page.view.brightness_enabled)
            page.toggle_play()
            self.assertTrue(page.timer.isActive())
            self.assertFalse(page.brightness.isEnabled())
            self.assertFalse(page.brightness.isChecked())
            self.assertFalse(page.view.brightness_enabled)
            self.assertFalse(page.view.hover_timer.isActive())
            page.brightness.setChecked(True)
            self.assertFalse(page.brightness.isChecked())
            self.assertFalse(page.view.brightness_enabled)
            page.pause()
            self.assertTrue(page.brightness.isEnabled())
            self.assertFalse(page.brightness.isChecked())
            page.brightness.click()
            page.request_frame(55)
            self.assertFalse(page.brightness.isEnabled())
            self.assertFalse(page.view.brightness_enabled)
            self.wait_for(lambda: not window.busy)
            self.assertTrue(page.brightness.isEnabled())
            self.assertFalse(page.brightness.isChecked())
        finally:
            page.pause()
            self.wait_for(lambda: not window.busy)
            window.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)


"""Video decode and FFmpeg operations; no GUI dependencies."""
import os
import shutil
import subprocess
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cv2


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int

    @property
    def duration(self):
        return self.frame_count / self.fps


def inspect_video(path, frame_limits=False):
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise ValueError('无法打开视频：' + str(path))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if width <= 0 or height <= 0 or not 0 < fps <= 1000 or count <= 0:
            raise ValueError('视频元信息无效或不受支持。')
        info = VideoInfo(str(Path(path).resolve()), width, height, fps, count)
        if frame_limits and (info.duration > 180.05 or max(width, height) > 2560 or min(width, height) > 1440):
            raise ValueError('帧标记 Demo 限制为 3 分钟以内、最高 2560×1440（支持竖屏）。')
        return info
    finally:
        cap.release()


class FrameReader:
    """Decode sequentially for frame identity, cache at most 48 MiB.

    Backward cache misses reopen and decode from the beginning instead of relying
    on codec keyframe seeking. This prioritizes correctness over random-seek speed.
    Only call from the owning background worker.
    """
    def __init__(self, path):
        self.path = str(path)
        self.cap = cv2.VideoCapture(self.path)
        self.next_index = 0
        self.cache = OrderedDict()
        self.bytes = 0

    def read(self, index):
        if index in self.cache:
            self.cache.move_to_end(index)
            return self.cache[index]
        if index < self.next_index:
            self.cap.release()
            self.cap = cv2.VideoCapture(self.path)
            self.next_index = 0
        frame = None
        while self.next_index <= index:
            if self.next_index == index:
                ok, frame = self.cap.read()
            else:
                ok = self.cap.grab()
            if not ok:
                raise ValueError('第 {} 帧解码失败。'.format(self.next_index))
            self.next_index += 1
        self.cache[index] = frame
        self.bytes += frame.nbytes
        while self.bytes > 48 * 1024 * 1024 and len(self.cache) > 1:
            _, old = self.cache.popitem(last=False)
            self.bytes -= old.nbytes
        return frame

    def close(self):
        self.cap.release()
        self.cache.clear()


def find_ffmpeg():
    configured = os.environ.get('FFMPEG_EXE')
    if configured and Path(configured).is_file():
        return configured
    executable = shutil.which('ffmpeg')
    if executable:
        return executable
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    local = Path(__file__).resolve().parents[1] / '.local' / 'ffmpeg-path.txt'
    if local.exists():
        executable = local.read_text(encoding='utf-8-sig').strip()
        if Path(executable).is_file():
            return executable
    raise ValueError('未找到 FFmpeg。请安装 imageio-ffmpeg，或设置 FFMPEG_EXE。')


def transcode(source, destination, start=None, end=None, cancel=None, progress=None):
    info = inspect_video(source)
    destination = Path(destination)
    if Path(source).resolve() == destination.resolve() or destination.exists():
        raise ValueError('请选择不存在的新输出文件，不能覆盖源视频或已有文件。')
    if destination.suffix.lower() not in ('.mp4', '.mkv', '.avi'):
        raise ValueError('输出格式仅支持 MP4、MKV、AVI。')
    if start is not None and (end is None or not 0 <= start < end <= info.duration + 0.001):
        raise ValueError('需满足 0 ≤ 起点 < 终点 ≤ 视频时长。')
    duration = end - start if start is not None else info.duration
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.encoding-', suffix=destination.suffix, dir=str(destination.parent))
    os.close(fd)
    cmd = [find_ffmpeg(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(source)]
    if start is not None:
        cmd += ['-ss', str(start), '-t', str(duration)]
    cmd += ['-map', '0:v:0', '-map', '0:a:0?', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2']
    if destination.suffix.lower() == '.avi':
        cmd += ['-c:v', 'mpeg4', '-q:v', '3', '-c:a', 'libmp3lame']
    else:
        cmd += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac']
    if destination.suffix.lower() == '.mp4':
        cmd += ['-movflags', '+faststart']
    cmd += ['-progress', 'pipe:1', temporary]
    proc = None
    try:
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors,
                                    universal_newlines=True, creationflags=0x08000000 if os.name == 'nt' else 0)
            # A separate lightweight watcher makes cancel responsive even before progress arrives.
            import threading
            stop = threading.Event()
            def watch():
                while not stop.wait(0.1):
                    if cancel is not None and cancel.is_set():
                        if proc.poll() is None:
                            proc.terminate()
                        return
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            try:
                for line in proc.stdout:
                    if line.startswith('out_time_us=') and progress:
                        try:
                            progress(min(99, int(int(line.split('=')[1]) / 1000000 / duration * 100)))
                        except ValueError:
                            pass
                code = proc.wait()
            finally:
                stop.set()
                watcher.join()
            if cancel is not None and cancel.is_set():
                raise ValueError('操作已取消，未生成输出文件。')
            if code:
                errors.seek(0)
                raise ValueError('FFmpeg 处理失败：' + errors.read().decode('utf-8', errors='replace')[-1800:])
        inspect_video(temporary)
        if destination.exists():
            raise ValueError('输出文件已存在，请重新选择位置。')
        os.rename(temporary, str(destination))
        if progress:
            progress(100)
        return str(destination)
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if proc.stdout:
                proc.stdout.close()
        if os.path.exists(temporary):
            os.unlink(temporary)


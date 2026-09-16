"""Export only explicitly marked video frames at source resolution."""
from pathlib import Path
from .media import FrameReader
from .rendering import to_image


def export_images(info, indices, directory, extension='png', progress=None):
    if extension not in ('png', 'jpg'):
        raise ValueError('图片格式仅支持 PNG、JPG。')
    indices = sorted(set(indices))
    if any(type(index) is not int or not 0 <= index < info.frame_count for index in indices):
        raise ValueError('导出帧编号超出视频范围。')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    reader = FrameReader(info.path)
    try:
        for step, index in enumerate(sorted(indices)):
            path = directory / ('frame_{:06d}.{}'.format(index, extension))
            if path.exists():
                raise ValueError('图片已存在：' + str(path))
            image = to_image(reader.read(index))
            if not image.save(str(path), extension.upper(), 95):
                raise ValueError('图片保存失败：' + str(path))
            if progress:
                progress(int((step+1)/len(indices)*100))
    finally:
        reader.close()
    return len(indices)

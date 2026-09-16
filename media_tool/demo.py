"""Generate a deterministic local sample without downloading user media."""
from pathlib import Path
import cv2
import numpy as np


def generate_sample(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    video = directory / 'demo.mp4'
    if video.exists():
        return str(video)
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 24, (960, 540))
    if not writer.isOpened():
        raise ValueError('本地视频编码器无法创建示例。')
    try:
        for index in range(144):
            frame = np.full((540, 960, 3), (36, 29, 21), np.uint8)
            for x in range(0, 960, 60):
                cv2.line(frame, (x, 0), (x, 540), (53, 45, 33), 1)
            for y in range(0, 540, 60):
                cv2.line(frame, (0, y), (960, y), (53, 45, 33), 1)
            x = 80 + index*3
            cv2.rectangle(frame, (x, 210), (x+150, 320), (70, 165, 220), -1)
            cv2.circle(frame, (735, 250), 55, (140, 205, 80), -1)
            cv2.putText(frame, 'LOCAL DEMO / FRAME {:03d}'.format(index), (35, 50),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, (230, 230, 230), 2)
            cv2.putText(frame, '24 FPS  -  6 SECONDS', (35, 500), cv2.FONT_HERSHEY_SIMPLEX,
                        0.65, (180, 180, 180), 1)
            writer.write(frame)
    finally:
        writer.release()
    return str(video)

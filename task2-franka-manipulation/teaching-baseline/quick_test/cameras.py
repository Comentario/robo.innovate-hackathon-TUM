#!/usr/bin/python3
"""Brief simultaneous live capture; system Python avoids user-site NumPy conflicts."""
import concurrent.futures
import json
from pathlib import Path
import sys
import time
import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, '/home/nshenoy/roboinnovate_hackathon/ros2_stack_reference/sources/pyrealsense2_runtime')


def webcam(device):
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    try:
        if not cap.isOpened():
            raise RuntimeError('Cannot open ' + device)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 15)
        frames, first, frame = 0, None, None
        start = time.monotonic()
        while frames < 60 and time.monotonic() - start < 12:
            ok, frame = cap.read()
            if not ok:
                raise RuntimeError('Frame read failed: ' + device)
            frames += 1
            if first is None:
                first = frame.copy()
        elapsed = time.monotonic() - start
        cv2.imwrite(str(HERE / (Path(device).name + '.jpg')), frame)
        return dict(device=device, frames=frames, seconds=elapsed, fps=frames/elapsed,
                    shape=list(frame.shape), mean_pixel_change=float(cv2.absdiff(first, frame).mean()),
                    verified=frames == 60)
    finally:
        cap.release()


def realsense():
    import pyrealsense2 as rs
    pipe = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)
    config.enable_stream(rs.stream.depth, 640, 480, rs.format.z16, 15)
    profile = pipe.start(config)
    try:
        start = time.monotonic()
        numbers = set()
        for _ in range(60):
            frames = pipe.wait_for_frames(5000)
            color, depth = frames.get_color_frame(), frames.get_depth_frame()
            if not color or not depth:
                raise RuntimeError('Missing RealSense color/depth frame')
            numbers.add(color.get_frame_number())
        elapsed = time.monotonic() - start
        image = np.asanyarray(color.get_data())
        depths = np.asanyarray(depth.get_data())
        cv2.imwrite(str(HERE / 'realsense_color.jpg'), image)
        cv2.imwrite(str(HERE / 'realsense_depth.png'), depths)
        valid = float((depths > 0).mean())
        return dict(device='RealSense', serial=profile.get_device().get_info(rs.camera_info.serial_number),
                    color_frames=len(numbers), depth_frames=60, seconds=elapsed, fps=60/elapsed,
                    depth_nonzero_fraction=valid, verified=len(numbers) == 60 and valid > 0)
    finally:
        pipe.stop()


if __name__ == '__main__':
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        jobs = {'wrist_webcam': pool.submit(webcam, '/dev/video2'),
                'external_webcam': pool.submit(webcam, '/dev/video10'),
                'wrist_realsense': pool.submit(realsense)}
        for name, future in jobs.items():
            try:
                result = dict(name=name, **future.result())
            except Exception as exc:
                result = dict(name=name, verified=False, error=str(exc))
            results.append(result)
    (HERE / 'cameras.json').write_text(json.dumps(results, indent=2) + '\n')
    print(json.dumps(results, indent=2))
    sys.exit(0 if all(r['verified'] for r in results) else 1)

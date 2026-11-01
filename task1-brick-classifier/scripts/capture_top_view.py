"""Capture a top-view brick dataset with fixed camera settings and light records.

Meant for a camera looking down at bricks lying on a surface or a conveyor belt.
Every photo is saved with the camera settings and light measures of that moment,
so lighting changes can be checked afterwards.

Keys in the preview window:
  g  save GOOD_xxx.jpg    b  save BAD_xxx.jpg    m  save MIX_xxx.jpg
  space  save IMG_xxx.jpg (no label)
  s  camera driver settings    q  quit

Light measures (CIELAB L*, 0 = black, 100 = white), shown live and saved:
  frame_L     median L* of the whole image
  center_L    median L* of the central guide rectangle (where bricks go)
  border_L    median L* of a 5% frame border (usually background or belt)
  clipped     share of near-white pixels (should stay near 0)

Output: <output>/<session>/ with the photos, one JSON per photo and log.csv.
Usage:
  capture_top_view.py [--output Top_View_Dataset] [--exposure -5] [--focus 20] [--camera 0]
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.capture_bricks import (CLIP_LEVEL, HEIGHT, WIDTH, camera_properties, open_camera, read_frame,
                                    settings_line)

DEFAULT_OUTPUT = PROJECT_ROOT / "Top_View_Dataset"
PREFIXES = {ord("g"): "GOOD", ord("b"): "BAD", ord("m"): "MIX", ord(" "): "IMG"}
CENTER_SHARE = 0.5
BORDER_SHARE = 0.05
STATUS_EVERY = 15
MAX_CLIPPED_SHARE = 0.01
LOG_FIELDS = ["file", "label", "time", "frame_L", "center_L", "border_L", "clipped",
              "exposure", "gain", "white_balance_temperature", "focus"]


def light_measures(frame: np.ndarray) -> dict:
    small = cv2.resize(frame, (WIDTH // 4, HEIGHT // 4))
    L = cv2.cvtColor(small.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)[..., 0]
    h, w = L.shape
    ch, cw = int(h * (1 - CENTER_SHARE) / 2), int(w * (1 - CENTER_SHARE) / 2)
    bh, bw = max(1, int(h * BORDER_SHARE)), max(1, int(w * BORDER_SHARE))
    border = np.concatenate([L[:bh].ravel(), L[-bh:].ravel(), L[:, :bw].ravel(), L[:, -bw:].ravel()])
    return {
        "frame_L": round(float(np.median(L)), 1),
        "center_L": round(float(np.median(L[ch:h - ch, cw:w - cw])), 1),
        "border_L": round(float(np.median(border)), 1),
        "clipped": round(float((frame.max(axis=2) >= CLIP_LEVEL).mean()), 4),
    }


def preview(frame: np.ndarray, lines: list[str], light: dict) -> np.ndarray:
    image = cv2.resize(frame, (WIDTH // 2, HEIGHT // 2))
    h, w = image.shape[:2]
    ch, cw = int(h * (1 - CENTER_SHARE) / 2), int(w * (1 - CENTER_SHARE) / 2)
    cv2.rectangle(image, (cw, ch), (w - cw, h - ch), (0, 200, 255), 2)
    for i, text in enumerate(lines):
        color = (0, 0, 255) if i == 1 and light["clipped"] > MAX_CLIPPED_SHARE else (0, 0, 0)
        cv2.putText(image, text, (12, 28 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(image, text, (12, 28 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--exposure", type=float, help="override exposure (C920: -4 brighter ... -7 darker)")
    parser.add_argument("--focus", type=float, help="override manual focus (top view is usually farther)")
    args = parser.parse_args()

    session = args.output / time.strftime("%Y%m%d_%H%M%S")
    session.mkdir(parents=True, exist_ok=True)
    capture = open_camera(args.camera)
    if args.exposure is not None:
        capture.set(cv2.CAP_PROP_EXPOSURE, args.exposure)
    if args.focus is not None:
        capture.set(cv2.CAP_PROP_FOCUS, args.focus)
    with (session / "log.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, LOG_FIELDS).writeheader()

    counts: dict[str, int] = {}
    message = "bricks inside the orange rectangle; press s to check Auto is off"
    frames, settings, light = 0, settings_line(capture), {}
    print(f"saving to {session}")
    try:
        while True:
            frame = read_frame(capture)
            if frames % STATUS_EVERY == 0:
                settings, light = settings_line(capture), light_measures(frame)
            frames += 1
            lines = [settings,
                     f"frame L* {light['frame_L']}  center L* {light['center_L']}  border L* {light['border_L']}"
                     f"  clipped {light['clipped']:.1%}",
                     "g GOOD | b BAD | m MIX | space IMG | s settings | q quit", message]
            cv2.imshow("top view capture", preview(frame, lines, light))
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                capture.set(cv2.CAP_PROP_SETTINGS, 1)
            elif key in PREFIXES:
                prefix = PREFIXES[key]
                counts[prefix] = counts.get(prefix, 0) + 1
                path = session / f"{prefix}_{counts[prefix]:03d}.jpg"
                cv2.imwrite(str(path), frame)
                measures, camera = light_measures(frame), camera_properties(capture)
                record = {"file": path.name, "label": prefix.lower(), "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "resolution": list(frame.shape[1::-1]), **measures, "camera": camera}
                path.with_suffix(".json").write_text(json.dumps(record, indent=2), encoding="utf-8")
                with (session / "log.csv").open("a", newline="", encoding="utf-8") as handle:
                    csv.DictWriter(handle, LOG_FIELDS).writerow(
                        {**{k: record[k] for k in LOG_FIELDS[:7]},
                         **{k: camera[k] for k in ("exposure", "gain", "white_balance_temperature", "focus")}})
                message = f"saved {path.name}  center L* {measures['center_L']}  clipped {measures['clipped']:.1%}"
                print(message)
    finally:
        capture.release()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
    print(f"session finished: {sum(counts.values())} photos in {session}")


if __name__ == "__main__":
    main()

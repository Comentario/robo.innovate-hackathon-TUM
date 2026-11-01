"""Capture brick photos with fixed camera settings (Windows, DirectShow).

Keys in the preview window:
  s  open the camera driver settings (uncheck Auto for white balance,
     exposure and focus there)
  g  save a GOOD_xx.jpg photo      b  save a BAD_xx.jpg photo
  m  save a MIX_xx.jpg photo       q  quit

The preview reports the share of clipped (near-white) pixels so the wall can be
kept below saturation. Every photo is stored with the camera properties that
were active, so it is possible to check afterwards that nothing changed.
"""

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "Third_Dataset_Bricks"
WIDTH, HEIGHT = 1920, 1080
CLIP_LEVEL = 250
MAX_CLIPPED_SHARE = 0.01
PREFIXES = {ord("g"): "GOOD", ord("b"): "BAD", ord("m"): "MIX"}
WARMUP_FRAMES = 30
MIN_FRAME_MEAN = 25
MAX_BAD_FRAMES = 60

# Manual values chosen for the Logitech C920 at the hackathon table. Setting a
# value through DirectShow also switches that control from Auto to manual.
# PowerLine frequency (50 Hz) is not exposed by OpenCV; set it once with "s".
MANUAL_SETTINGS = [
    (cv2.CAP_PROP_AUTO_WB, 0),
    (cv2.CAP_PROP_WB_TEMPERATURE, 4520),
    (cv2.CAP_PROP_GAIN, 0),
    (cv2.CAP_PROP_EXPOSURE, -5),
    (cv2.CAP_PROP_AUTOFOCUS, 0),
    (cv2.CAP_PROP_FOCUS, 20),
    (cv2.CAP_PROP_BRIGHTNESS, 128),
    (cv2.CAP_PROP_CONTRAST, 128),
    (cv2.CAP_PROP_SATURATION, 128),
    (cv2.CAP_PROP_SHARPNESS, 128),
    (cv2.CAP_PROP_BACKLIGHT, 0),
]
PROPERTIES = {
    "auto_white_balance": cv2.CAP_PROP_AUTO_WB,
    "white_balance_temperature": cv2.CAP_PROP_WB_TEMPERATURE,
    "auto_exposure": cv2.CAP_PROP_AUTO_EXPOSURE,
    "exposure": cv2.CAP_PROP_EXPOSURE,
    "gain": cv2.CAP_PROP_GAIN,
    "brightness": cv2.CAP_PROP_BRIGHTNESS,
    "autofocus": cv2.CAP_PROP_AUTOFOCUS,
    "focus": cv2.CAP_PROP_FOCUS,
}


def camera_properties(capture: cv2.VideoCapture) -> dict:
    return {name: capture.get(prop) for name, prop in PROPERTIES.items()}


def apply_manual_settings(capture: cv2.VideoCapture) -> None:
    for prop, value in MANUAL_SETTINGS:
        capture.set(prop, value)


def open_camera(index: int, apply_settings: bool = True) -> cv2.VideoCapture:
    """Open the camera in MJPG at full HD, apply the manual settings and warm up.

    Uncompressed YUY2 at 1920x1080 overloads USB on the C920 (low frame rate,
    empty frames), and the first frames after a settings change can be black,
    so they are read and thrown away before returning.
    """
    capture = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    if not capture.isOpened():
        raise SystemExit(f"Could not open camera {index}")
    if apply_settings:
        apply_manual_settings(capture)
    for _ in range(WARMUP_FRAMES):
        capture.read()
    return capture


def read_frame(capture: cv2.VideoCapture) -> np.ndarray:
    """Next usable frame; occasional black frames are skipped."""
    for _ in range(MAX_BAD_FRAMES):
        ok, frame = capture.read()
        if ok and frame is not None and frame.mean() >= MIN_FRAME_MEAN:
            return frame
    raise SystemExit("Camera keeps sending empty or black frames")


def settings_line(capture: cv2.VideoCapture) -> str:
    p = camera_properties(capture)
    return (f"WB {p['white_balance_temperature']:.0f}  exp {p['exposure']:.0f}  "
            f"gain {p['gain']:.0f}  focus {p['focus']:.0f}")


def next_path(prefix: str) -> Path:
    index = 1
    while (OUTPUT_ROOT / f"{prefix}_{index:02d}.jpg").exists():
        index += 1
    return OUTPUT_ROOT / f"{prefix}_{index:02d}.jpg"


def draw_status(frame: np.ndarray, clipped: float, settings: str, message: str) -> np.ndarray:
    preview = cv2.resize(frame, (WIDTH // 2, HEIGHT // 2))
    color = (0, 0, 255) if clipped > MAX_CLIPPED_SHARE else (0, 160, 0)
    lines = [f"clipped (near-white) pixels: {clipped:.1%}", settings,
             "s settings | g GOOD | b BAD | m MIX | q quit", message]
    for i, text in enumerate(lines):
        y = 28 + i * 28
        cv2.putText(preview, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(preview, text, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    color if i == 0 else (0, 0, 0), 2, cv2.LINE_AA)
    return preview


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", type=int, default=0, help="camera index (0, 1, ...)")
    parser.add_argument("--keep-current", action="store_true",
                        help="do not apply MANUAL_SETTINGS at startup")
    args = parser.parse_args()

    capture = open_camera(args.camera, apply_settings=not args.keep_current)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    message = "check the values above; press s to verify Auto is off"
    frame_count = 0
    settings = settings_line(capture)
    while True:
        frame = read_frame(capture)
        frame_count += 1
        if frame_count % 30 == 0:
            settings = settings_line(capture)
        clipped = float((frame.max(axis=2) >= CLIP_LEVEL).mean())
        cv2.imshow("brick capture", draw_status(frame, clipped, settings, message))
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("s"):
            capture.set(cv2.CAP_PROP_SETTINGS, 1)
        elif key in PREFIXES:
            path = next_path(PREFIXES[key])
            cv2.imwrite(str(path), frame)
            metadata = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "resolution": list(frame.shape[1::-1]),
                        "clipped_share": round(clipped, 4), "camera": camera_properties(capture)}
            path.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            message = f"saved {path.name}"

    capture.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()

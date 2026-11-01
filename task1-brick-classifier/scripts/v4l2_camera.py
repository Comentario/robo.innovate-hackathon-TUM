"""Linux (V4L2) color camera for the web demo on the Jetson: Orbbec Gemini 2 or any UVC camera.

Device and mode: with device "auto" every /dev/video* node is listed with
`v4l2-ctl --list-formats-ext`; nodes whose name mentions Orbbec / Gemini are
preferred, depth and IR nodes drop out because they offer no color format, and
the largest color resolution is taken, up to `max_height` (e.g. 720: detection runs at
640 px anyway, and every per-pixel step is 2.25x cheaper than at 1080p), uncompressed
YUYV / UYVY before MJPG at the same size as long as it still gives MIN_FPS (no
decoding, and JPEG artifacts change color).

Camera settings belong to the operator: the page lists every control of the camera
(exposure, auto modes, brightness, white balance where the camera has it, ...) and
sets them live; what the operator changes is saved to `settings_path` and applied at
the next start, so every session (and every calibration) sees the same camera.
Nothing is tuned automatically: without saved settings the camera starts on a fixed
exposure of one lamp flicker period. `lock()` (a button in the page) can still choose
the exposure by measuring the image: each flicker-free exposure that fits 30 fps is
tried and the one whose brightest 1 % of pixels lands closest to TARGET_P99 is kept
(shorter, banded exposures only when even one flicker period is too bright).

Exposure: flicker-free exposures are whole lamp flicker periods (FLICKER_HZ mains:
lamps pulse at twice that), which removes the dark bands a rolling shutter shows under
mains lighting, up to MAX_EXPOSURE_S (fits 30 fps). The unit
of the exposure control is 100 us by the V4L2 standard, but the Gemini 2 uses
microseconds (maximum 33000 = one frame at 30 fps); it is told apart by that maximum.

Speed: in MJPG mode the frames are taken compressed and decoded on DECODERS threads,
so the 1080p JPEG decoding on the Jetson's CPU does not limit the frame rate.

Control names differ between cameras and kernels (the Gemini 2 does not use all
the standard ones), so they are found by pattern in `v4l2-ctl --list-ctrls-menus`.

Usage (check on the device):  python3 scripts/v4l2_camera.py [--device /dev/video4]
"""

import argparse
import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np

COLOR_FORMATS = {"YUYV": 2, "UYVY": 2, "MJPG": 1}  # higher is preferred at the same size
MIN_FPS = 30  # at the same size, a mode reaching this frame rate beats a slower uncompressed one
EXPOSURE_STEP_S = 0.5  # time for a new exposure to reach the frames
TARGET_P99 = 200  # brightest 1 % of the image just below clipping
BANDING_PENALTY = 40  # score cost of an exposure shorter than one flicker period (dark bands)
WARMUP_FRAMES = 15
MIN_FRAME_MEAN = 5
MAX_EXPOSURE_S = 0.030
FLICKER_HZ = 50  # mains frequency where the demo runs (Germany)
DECODERS = 3
SETTINGS_VERSION = 4  # {control: value} set by the operator; older files are ignored
EXPOSURE_MANUAL = 1  # V4L2 auto_exposure menu: 1 = manual
# First matching control name, by pattern, for each role.
ROLES = {
    "auto_exposure": r"^(auto_exposure|exposure_auto)$",
    "exposure": r"^exposure(_time)?_absolute$|^exposure$",
    "gain": r"^(analogue_|analog_)?gain$",
    "auto_white_balance": r"^white_balance_(automatic|temperature_auto)$|^auto_white_balance$",
    "white_balance": r"^white_balance_temperature$",
}


def v4l2(device: str, *args: str) -> str:
    result = subprocess.run(["v4l2-ctl", "-d", device, *args], capture_output=True, text=True, timeout=10)
    return result.stdout


def device_name(device: str) -> str:
    sys_name = Path("/sys/class/video4linux") / Path(device).name / "name"
    return sys_name.read_text().strip() if sys_name.exists() else ""


def color_modes(device: str) -> list[dict]:
    """Color formats of one node: [{format, width, height, fps}] (empty for depth / IR nodes)."""
    modes, fourcc, size = [], None, None
    for line in v4l2(device, "--list-formats-ext").splitlines():
        if m := re.search(r"\[\d+\]: '(\w+)'", line):
            fourcc = m.group(1)
        elif m := re.search(r"Size: Discrete (\d+)x(\d+)", line):
            size = (int(m.group(1)), int(m.group(2)))
        elif (m := re.search(r"\(([\d.]+) fps\)", line)) and fourcc in COLOR_FORMATS and size:
            modes.append({"format": fourcc, "width": size[0], "height": size[1], "fps": float(m.group(1))})
    return modes


def best_mode(modes: list[dict]) -> dict | None:
    """Largest size; at the same size an uncompressed format if it reaches MIN_FPS, then the highest fps."""
    if not modes:
        return None
    def key(m: dict) -> tuple:
        fast_enough = m["fps"] >= MIN_FPS
        return (m["width"] * m["height"], fast_enough, COLOR_FORMATS[m["format"]] if fast_enough else 0, m["fps"])
    return max(modes, key=key)


def find_color_camera(device: str = "auto", max_height: int | None = None) -> tuple[str, dict]:
    """(device path, mode) of the color camera at its largest resolution (up to max_height)."""
    candidates = [device] if device != "auto" else sorted(
        (str(p) for p in Path("/dev").glob("video*")), key=lambda p: int(re.sub(r"\D", "", p) or 0))
    found = []
    for path in candidates:
        mode = best_mode([m for m in color_modes(path) if max_height is None or m["height"] <= max_height])
        if mode:
            name = device_name(path)
            preferred = bool(re.search(r"orbbec|gemini", name, re.I))
            found.append((preferred, mode["width"] * mode["height"], path, mode, name))
    if not found:
        raise SystemExit(f"no color camera found ({device}); check the camera entitlement and `v4l2-ctl --list-devices`")
    preferred, _, path, mode, name = max(found, key=lambda f: (f[0], f[1]))
    print(f"camera: {path} ({name or 'unknown'}) {mode['width']}x{mode['height']} {mode['format']} {mode['fps']:.0f} fps")
    return path, mode


def parse_controls(text: str) -> dict[str, dict]:
    """`v4l2-ctl --list-ctrls-menus` -> {name: {type, value, min, max, step, default, flags, menu}}."""
    controls, last = {}, None
    for line in text.splitlines():
        if m := re.match(r"\s*(\w+)\s+0x[0-9a-f]+\s+\((\w+)\)\s*:(.*)", line):
            fields = dict(re.findall(r"(\w+)=(-?\d+)", m.group(3)))
            flags = re.search(r"flags=([\w,-]+)", m.group(3))
            if "value" not in fields:
                last = None
                continue
            last = controls[m.group(1)] = {"type": m.group(2), "flags": flags.group(1) if flags else "",
                                           **{k: int(fields[k]) for k in ("value", "min", "max", "step", "default")
                                              if k in fields}}
        elif last is not None and (m := re.match(r"\s+(-?\d+): (.+)", line)) and last["type"] in ("menu", "intmenu"):
            last.setdefault("menu", {})[m.group(1)] = m.group(2).strip()
    return controls


def roles(controls: dict) -> dict[str, str]:
    """Role -> control name on this camera."""
    return {role: next((n for n in controls if re.search(pattern, n)), None) for role, pattern in ROLES.items()}


class V4L2Camera:
    def __init__(self, device: str = "auto", settings_path: Path | None = None, max_height: int | None = None) -> None:
        self.device, self.mode = find_color_camera(device, max_height)
        self.name = device_name(self.device)
        self.settings_path = settings_path
        self.lock_message = ""
        self.capture = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        self.capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.mode["format"]))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.mode["width"])
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.mode["height"])
        self.capture.set(cv2.CAP_PROP_FPS, self.mode["fps"])
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.capture.isOpened():
            raise SystemExit(f"could not open {self.device}")
        for _ in range(WARMUP_FRAMES):
            self.capture.read()
        self.running = True
        self.decode_ms, self.grab_fps, self.last_frame = 0.0, 0.0, None
        self.raw = self.mode["format"] == "MJPG"
        if self.raw:
            # Compressed frames from the driver, decoded in parallel (cv2.imdecode releases the GIL).
            self.capture.set(cv2.CAP_PROP_CONVERT_RGB, 0)
            self.jobs: queue.Queue = queue.Queue(maxsize=DECODERS)
            self.latest, self.latest_seq, self.returned_seq = None, 0, 0
            self.ready = threading.Condition()
            threading.Thread(target=self.grab_loop, daemon=True).start()
            for _ in range(DECODERS):
                threading.Thread(target=self.decode_loop, daemon=True).start()
        self.saved = self.saved_controls()
        if self.saved:
            self.apply_saved()
            self.lock_message = "operator settings applied"
        else:
            self.start_default()

    # Controls -------------------------------------------------------------------

    def controls(self) -> dict[str, dict]:
        return parse_controls(v4l2(self.device, "--list-ctrls-menus"))

    def write(self, name: str, value: int) -> None:
        v4l2(self.device, "-c", f"{name}={value}")

    def save(self, changes: dict[str, int]) -> None:
        """Remember operator settings (control -> value) and keep them for the next start."""
        self.saved.update(changes)
        if self.settings_path is not None:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps({"device_name": self.name, "version": SETTINGS_VERSION,
                                                      "controls": self.saved}, indent=2), encoding="utf-8")

    def saved_controls(self) -> dict[str, int]:
        if self.settings_path is None or not self.settings_path.exists():
            return {}
        data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        if data.get("device_name") != self.name or data.get("version") != SETTINGS_VERSION:
            return {}  # another camera, or an older format: start from the default
        return {k: int(v) for k, v in data.get("controls", {}).items()}

    def apply_saved(self) -> None:
        # Automatic modes first: a manual value is ignored while its automatic mode is on.
        order = sorted(self.saved, key=lambda n: "auto" not in n)
        for name in order:
            self.write(name, self.saved[name])

    def start_default(self) -> None:
        """No operator settings yet: fixed one-flicker-period exposure (no dark bands), nothing automatic
        chosen by the program. The operator adjusts the rest in the page."""
        available = self.controls()
        names = roles(available)
        options = self.exposure_options(available)
        if names["exposure"] is None or not options:
            self.lock_message = "camera defaults (set the camera in the page)"
            return
        if names["auto_exposure"]:
            self.write(names["auto_exposure"], EXPOSURE_MANUAL)
        self.write(names["exposure"], options[0])
        self.lock_message = "default: fixed exposure, one flicker period; adjust it in Camera settings"

    def set_control(self, name: str, value: int) -> str:
        """Set one control from the page (clamped to its range) and keep it."""
        available = self.controls()
        if name not in available:
            return f"unknown camera control: {name}"
        control = available[name]
        value = int(min(max(value, control.get("min", value)), control.get("max", value)))
        self.write(name, value)
        self.save({name: value})
        self.lock_message = "operator settings applied"
        return f"{name} = {value}" + (f" ({value * self.exposure_unit(control) * 1000:.1f} ms)"
                                      if name == roles(available)["exposure"] else "")

    def reset_defaults(self) -> str:
        """Every writable control back to the camera default; operator settings forgotten."""
        available = self.controls()
        for name in sorted(available, key=lambda n: "auto" not in n):
            if "default" in available[name] and "read-only" not in available[name]["flags"]:
                self.write(name, available[name]["default"])
        self.saved = {}
        if self.settings_path is not None and self.settings_path.exists():
            self.settings_path.unlink()
        self.lock_message = "camera defaults"
        return "camera controls back to their defaults"

    @staticmethod
    def exposure_unit(control: dict) -> float:
        """Seconds per exposure step: 100 us by the standard, 1 us on cameras whose maximum
        only makes sense in microseconds (Gemini 2: 33000)."""
        return 1e-6 if control.get("max", 0) >= 20000 else 100e-6

    def max_exposure(self, available: dict) -> int | None:
        """Longest exposure (control units) that still fits the frame rate."""
        name = roles(available)["exposure"]
        if name is None:
            return None
        return min(available[name].get("max", 10**9), round(MAX_EXPOSURE_S / self.exposure_unit(available[name])))

    def exposure_options(self, available: dict) -> list[int]:
        """Flicker-free exposures (control units) that fit the frame rate: 10, 20, 30 ms at 50 Hz."""
        name = roles(available)["exposure"]
        if name is None:
            return []
        period = round(1 / (2 * FLICKER_HZ) / self.exposure_unit(available[name]))
        return list(range(period, self.max_exposure(available) + 1, period))

    def lock(self) -> str:
        """Optional (button in the page): choose the exposure by measuring the image, see the
        module docstring. Saved like an operator setting."""
        available = self.controls()
        names = roles(available)
        if names["exposure"] is None:
            return "camera has no exposure control"
        deadline = time.monotonic() + 5
        while self.last_frame is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if names["auto_exposure"]:
            self.write(names["auto_exposure"], EXPOSURE_MANUAL)
        options = self.exposure_options(available)
        shorter = [options[0] // 2, options[0] // 4] if options else [self.max_exposure(available)]
        scores = []
        for value, flicker_free in [(v, True) for v in options] + [(v, False) for v in shorter]:
            self.write(names["exposure"], value)
            time.sleep(EXPOSURE_STEP_S)
            if self.last_frame is None:
                continue
            gray = cv2.cvtColor(self.last_frame[::4, ::4], cv2.COLOR_BGR2GRAY)
            p99 = float(np.percentile(gray, 99))
            scores.append((abs(p99 - TARGET_P99) + (0 if flicker_free else BANDING_PENALTY), value, p99))
        value, p99 = min(scores)[1:] if scores else (options[0] if options else shorter[0], None)
        self.write(names["exposure"], value)
        self.save({**({names["auto_exposure"]: EXPOSURE_MANUAL} if names["auto_exposure"] else {}), names["exposure"]: value})
        unit = self.exposure_unit(available[names["exposure"]])
        self.lock_message = f"exposure chosen: {value * unit * 1000:.1f} ms" + \
            ("" if p99 is None else f" (brightest 1% at {p99:.0f}/255)")
        return self.lock_message

    def set_exposure(self, value: int) -> str:
        """Fixed exposure (control units): automatic exposure off, value kept."""
        available = self.controls()
        names = roles(available)
        if names["exposure"] is None:
            return "camera has no exposure control"
        if names["auto_exposure"]:
            self.write(names["auto_exposure"], EXPOSURE_MANUAL)
            self.save({names["auto_exposure"]: EXPOSURE_MANUAL})
        return self.set_control(names["exposure"], value)

    # Frames ---------------------------------------------------------------------

    def grab_loop(self) -> None:
        seq, last = 0, time.monotonic()
        while self.running:
            ok, buffer = self.capture.read()
            if not ok or buffer is None:
                continue
            seq += 1
            now = time.monotonic()
            self.grab_fps = 0.9 * self.grab_fps + 0.1 / max(1e-3, now - last)
            last = now
            while True:  # keep only the newest frames when the decoders fall behind
                try:
                    self.jobs.put_nowait((seq, buffer))
                    break
                except queue.Full:
                    try:
                        self.jobs.get_nowait()
                    except queue.Empty:
                        pass

    def decode_loop(self) -> None:
        while self.running:
            seq, buffer = self.jobs.get()
            start = time.monotonic()
            # Some OpenCV builds decode even with CONVERT_RGB off: then the frame is already an image.
            frame = buffer if buffer.ndim == 3 else cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            if frame is None or frame[::16, ::16].mean() < MIN_FRAME_MEAN:
                continue
            with self.ready:
                self.decode_ms = 0.9 * self.decode_ms + 0.1 * (time.monotonic() - start) * 1000
                if seq > self.latest_seq:
                    self.latest, self.latest_seq = frame, seq
                    self.last_frame = frame
                    self.ready.notify_all()

    def read(self) -> np.ndarray | None:
        if not self.raw:
            ok, frame = self.capture.read()
            if not ok or frame is None or frame[::16, ::16].mean() < MIN_FRAME_MEAN:
                return None
            self.last_frame = frame
            return frame
        with self.ready:
            self.ready.wait_for(lambda: self.latest_seq > self.returned_seq, timeout=1.0)
            if self.latest_seq == self.returned_seq:
                return None
            self.returned_seq = self.latest_seq
            return self.latest

    def properties(self) -> dict:
        now = self.controls()
        names = roles(now)
        info = {role: now[name]["value"] if name else None for role, name in names.items()}
        name = names["exposure"]
        unit = self.exposure_unit(now[name]) if name else None
        info["exposure_ms"] = round(info["exposure"] * unit * 1000, 2) if name and info["exposure"] is not None else None
        info["exposure_options"] = [{"value": v, "ms": round(v * unit * 1000, 1)} for v in self.exposure_options(now)]
        return {"device": self.device, "name": self.name, **self.mode, **info, "status": self.lock_message,
                "grab_fps": round(self.grab_fps, 1), "decode_ms": round(self.decode_ms, 1), "roles": names,
                "exposure_unit_ms": unit * 1000 if unit else None, "saved": self.saved,
                "controls": {n: c for n, c in now.items()}}

    def release(self) -> None:
        self.running = False
        self.capture.release()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--max-height", type=int)
    args = parser.parse_args()
    for path in sorted(Path("/dev").glob("video*")):
        print(path, device_name(str(path)), best_mode(color_modes(str(path))))
    camera = V4L2Camera(args.device, max_height=args.max_height)
    frames, start = 0, time.monotonic()
    while time.monotonic() - start < 5:
        frames += camera.read() is not None
    print(f"{frames / 5:.1f} fps read", camera.properties())
    camera.release()


if __name__ == "__main__":
    main()

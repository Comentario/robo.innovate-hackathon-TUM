"""Classify bricks as good or bad from the camera (or a saved photo), and log it.

One pipeline, models loaded once:
  frame -> Grounding DINO (row extent) -> split_brick_row (one box per brick)
  -> MobileSAM (brick mask) -> color features -> classifier.

Classifiers (--method):
  knn   1-nearest-neighbor against the labeled reference bricks (default);
  band  lightness band: good if LOW <= L* mode <= HIGH. L* mode is the most
        frequent lightness inside the mask (the brick base color, not moved by
        mortar stains). The band is fitted on the calibration, or given with
        --band LOW HIGH. Each brick shows its L* mode and how far it is from
        the band, so bricks outside the expected range are easy to spot.

Reference bricks come from one of:
  --calibrate            photograph the labeled sample bricks first, in the
                         same place and light as the test (recommended);
  --reference FILE       a calibration saved earlier (calibration.json);
  (default)              Third_Dataset_Bricks, built by evaluate_third_dataset.py.

Calibration keys (window "brick classifier"):
  space  capture; then g / b gives the label of each brick, left to right,
         and n skips a brick that should not be used
  u      undo the last calibration capture
  f      finish: checks the calibration and switches to classification
Classification keys:
  space  capture and classify; then g / b enters the true label of each brick
         for the log (n skips)
  c      new calibration without restarting (models and camera stay loaded)
Always: s camera driver settings, q quit. Closing the window also quits and
releases the camera.

A calibration is saved in outputs2/calibration/<session>/ (frames +
calibration.json). Classification captures are logged in outputs2/live/<session>/:
raw frame, result image, log.jsonl (per capture) and log.csv (per brick).

Photo mode: --image path/to/photo.jpg classifies a saved photo. With the default
reference, bricks from a photo with the same name are left out.
"""

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
from PIL import Image
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
from ultralytics import SAM

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analyze_second_dataset_colors import bgr_to_lab, brick_features
from scripts.capture_bricks import HEIGHT, WIDTH, camera_properties, open_camera, read_frame, settings_line
from scripts.evaluate_third_dataset import MIN_MASK_COVERAGE, PHOTO_GROUPS, box_region, table_reference
from scripts.run_grounding_dino import BOX_THRESHOLD, MAX_SIDE, MODEL_ID, PROMPT, TEXT_THRESHOLD, detect, normalize_prompt
from scripts.run_mobile_sam import MODEL_PATH, segment, to_corners
from scripts.split_brick_row import split_scene


REFERENCE_PATH = PROJECT_ROOT / "outputs2" / "third_dataset" / "evaluation" / "brick_features.json"
LOG_ROOT = PROJECT_ROOT / "outputs2" / "live"
CALIBRATION_ROOT = PROJECT_ROOT / "outputs2" / "calibration"

# Feature sets for the nearest-neighbor comparison. "raw" measures the brick
# color directly; "table" subtracts the lightness of the table strip under the
# bricks; "table_ratio" divides by it instead (rel_L: L* with the table as white).
# Light changes scale luminance, so dividing compensates small light changes
# between calibration and classification better than subtracting, especially
# for dark bricks.
FEATURE_OPTIONS = {"raw": ["L_med", "C_med"], "table": ["dL_wood", "C_med"], "table_ratio": ["rel_L", "C_med"]}
DEFAULT_REFERENCE_FEATURES = "table"
# The self-check cannot see light drift (the light is constant while calibrating),
# so table_ratio is kept unless another set is clearly better.
PREFERRED_FEATURES = "table_ratio"
PREFERENCE_MARGIN = 0.05
LOGGED_FEATURES = ["L_med", "L_mode", "dL_wood", "rel_L", "C_med", "C_mode"]
METHOD = "knn"
BAND_OVERRIDE: tuple[float, float] | None = None
# Fitted on calibration 20261024_202203 (scene L* ~53); only used without a calibration.
DEFAULT_BAND = (24.5, 27.5)
BAND_FEATURE = "L_mode"
# Confidence of the band rule grows with the distance to the nearest band edge.
BAND_CONFIDENCE_SCALE = 5.0
MIN_CALIBRATION_PER_CLASS = 3
FEATURE_OVERRIDE: str | None = None
CALIBRATION_WARN_ACCURACY = 0.9
# Calibration bricks closer than this in L* and in chroma are "the same color".
CONFLICT_TOLERANCE = 1.0
WATCHED_SETTINGS = ["white_balance_temperature", "exposure", "gain", "focus"]
THIRD_DATASET_ROOT = PROJECT_ROOT / "Third_Dataset_Bricks"
# Scene lightness: median L* of the table band at the bottom of the frame.
# Further than this from the reference lightness, colors are no longer comparable.
LIGHTNESS_TOLERANCE = 6.0
# Camera status (settings, lightness) is refreshed every this many preview frames;
# reading camera properties through DirectShow on every frame slows the preview.
STATUS_EVERY = 15

# A frame this dark is a camera glitch (e.g. right after settings change).
MIN_FRAME_MEAN = 25
# Detections covering most of the frame are not a single brick row.
MAX_BOX_AREA_SHARE = 0.6
# A detection whose MobileSAM mask fills this little of the box is background.
MIN_BRICK_COVERAGE = 0.25

GOOD_BGR = (214, 120, 42)
BAD_BGR = (52, 104, 235)
PENDING_BGR = (150, 150, 150)
CORRECT_BGR = (12, 163, 12)
ERROR_BGR = (59, 59, 208)


def add_relative_lightness(row: dict) -> dict:
    """Add rel_L: the brick L* computed with the table strip as reference white."""
    if "rel_L" not in row and usable(row, ["L_med", "dL_wood"]):
        table_L = row["L_med"] - row["dL_wood"]
        luminance_ratio = ((row["L_med"] + 16) / 116) ** 3 / ((table_L + 16) / 116) ** 3
        row["rel_L"] = float(116 * np.cbrt(luminance_ratio) - 16)
    return row


def histogram_mode(values: np.ndarray, width: float = 1.0) -> float:
    """Most frequent value (lightly smoothed histogram peak)."""
    bins = np.arange(np.floor(values.min()), np.ceil(values.max()) + width, width)
    counts, edges = np.histogram(values, bins=bins)
    counts = np.convolve(counts, np.ones(3) / 3, mode="same")
    peak = int(np.argmax(counts))
    return float((edges[peak] + edges[peak + 1]) / 2)


def fit_band(rows: list[dict], key: str) -> tuple[float, float]:
    """Interval [low, high] of `key` that classifies the most rows correctly."""
    values = sorted({r[key] for r in rows})
    best, band = -1.0, (values[0], values[-1])
    for i, low in enumerate(values):
        for high in values[i:]:
            score = np.mean([(low <= r[key] <= high) == (r["label"] == "good") for r in rows])
            if score > best:
                best, band = score, (low, high)
    return band


def usable(row: dict, keys: list[str]) -> bool:
    return all(isinstance(row.get(k), (int, float)) and math.isfinite(row[k]) for k in keys)


class Reference:
    """Labeled reference bricks and the feature set used to compare with them."""

    def __init__(self, rows: list[dict], feature_set: str, name: str) -> None:
        self.keys = FEATURE_OPTIONS[feature_set]
        self.feature_set = feature_set
        self.name = name
        self.camera: dict | None = None
        self.scene_lightness: float | None = None
        self.rows = [r for r in (add_relative_lightness(dict(r)) for r in rows) if usable(r, self.keys)]
        X = np.array([[r[k] for k in self.keys] for r in self.rows])
        self.center, self.spread = X.mean(axis=0), X.std(axis=0) + 1e-6
        self.z = (X - self.center) / self.spread
        self.labels = np.array([r["label"] for r in self.rows])

    @classmethod
    def third_dataset(cls, exclude_photo: str | None = None) -> "Reference":
        rows = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
        if exclude_photo:
            group = PHOTO_GROUPS.get(exclude_photo, exclude_photo)
            rows = [r for r in rows if PHOTO_GROUPS.get(r["photo"], r["photo"]) != group]
        reference = cls(rows, DEFAULT_REFERENCE_FEATURES, "Third_Dataset_Bricks")
        photos = sorted({r["photo"] for r in rows})
        reference.scene_lightness = float(np.median(
            [scene_lightness(cv2.imread(str(THIRD_DATASET_ROOT / f"{p}.jpg"))) for p in photos]))
        return reference

    @classmethod
    def load(cls, path: Path) -> "Reference":
        data = json.loads(path.read_text(encoding="utf-8"))
        reference = cls(data["rows"], FEATURE_OVERRIDE or data["feature_set"], str(path))
        reference.camera = data.get("camera")
        reference.scene_lightness = data.get("scene_lightness")
        return reference

    def predict(self, features: dict) -> dict:
        features = add_relative_lightness(dict(features))
        if not usable(features, self.keys):
            return {"prediction": "unknown", "nearest_reference": None, "distance_to_good": None,
                    "distance_to_bad": None, "confidence": 0.0}
        z = (np.array([features[k] for k in self.keys]) - self.center) / self.spread
        distances = np.linalg.norm(self.z - z, axis=1)
        nearest = int(np.argmin(distances))
        to_good = float(distances[self.labels == "good"].min())
        to_bad = float(distances[self.labels == "bad"].min())
        return {
            "prediction": str(self.labels[nearest]),
            "nearest_reference": f"{self.rows[nearest]['photo']}#{self.rows[nearest]['position']}",
            "distance_to_good": round(to_good, 3),
            "distance_to_bad": round(to_bad, 3),
            # 0.5 = undecided, 1.0 = clearly closer to the predicted class.
            "confidence": round(max(to_good, to_bad) / (to_good + to_bad + 1e-6), 3),
        }


class BandReference:
    """Lightness band rule: good if low <= L* mode <= high."""

    def __init__(self, low: float, high: float, name: str, key: str = BAND_FEATURE,
                 rows: list[dict] | None = None) -> None:
        self.low, self.high, self.key = low, high, key
        self.keys = [key]
        self.feature_set = f"band {key} [{low:.1f}, {high:.1f}]"
        self.name = name
        self.rows = rows or []
        self.camera: dict | None = None
        self.scene_lightness: float | None = None

    @classmethod
    def from_calibration(cls, path: Path) -> "BandReference":
        data = json.loads(path.read_text(encoding="utf-8"))
        rows = data["rows"]
        key = BAND_FEATURE if all(usable(r, [BAND_FEATURE]) for r in rows) else "L_med"
        if key != BAND_FEATURE:
            print(f"   note: {path} has no {BAND_FEATURE} (older calibration); the band uses L_med")
        low, high = BAND_OVERRIDE or fit_band(rows, key)
        reference = cls(low, high, str(path), key, rows)
        reference.camera = data.get("camera")
        reference.scene_lightness = data.get("scene_lightness")
        return reference

    def predict(self, features: dict) -> dict:
        value = features.get(self.key)
        if value is None or not math.isfinite(value):
            return {"prediction": "unknown", "nearest_reference": None, "distance_to_good": None,
                    "distance_to_bad": None, "confidence": 0.0, "band_offset": None}
        if value < self.low:
            offset = value - self.low
        elif value > self.high:
            offset = value - self.high
        else:
            offset = 0.0
        edge = min(value - self.low, self.high - value) if offset == 0 else abs(offset)
        return {
            "prediction": "good" if offset == 0 else "bad",
            "nearest_reference": f"band {self.low:.1f}-{self.high:.1f}",
            "distance_to_good": None,
            "distance_to_bad": None,
            "confidence": round(0.5 + min(edge, BAND_CONFIDENCE_SCALE) / (2 * BAND_CONFIDENCE_SCALE), 3),
            # 0 inside the band; negative = darker than the band, positive = lighter.
            "band_offset": round(offset, 2),
            "band_value": round(value, 2),
            "band_key": self.key,
        }


def load_reference(path: Path | None):
    """Reference for the selected method, from a calibration or the defaults."""
    if METHOD == "band":
        if path:
            return BandReference.from_calibration(path)
        low, high = BAND_OVERRIDE or DEFAULT_BAND
        print(f"   band without calibration: [{low}, {high}] (only valid with the same light; calibrate if possible)")
        return BandReference(low, high, "fixed band")
    return Reference.load(path) if path else None


class BrickClassifier:
    """Detection, segmentation and color classification with models loaded once."""

    def __init__(self, reference: Reference | None = None, exclude_photo: str | None = None) -> None:
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = AutoProcessor.from_pretrained(MODEL_ID)
        self.detector = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(self.device).eval()
        self.segmenter = SAM(str(MODEL_PATH))
        self.prompt = normalize_prompt(PROMPT)
        self.reference = reference or Reference.third_dataset(exclude_photo)

    def detect_boxes(self, frame: np.ndarray) -> list[dict]:
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        resized = image.copy()
        resized.thumbnail((MAX_SIDE, MAX_SIDE))
        scale = image.width / resized.width
        raw = detect(self.detector, self.processor, self.device, resized, self.prompt, BOX_THRESHOLD, TEXT_THRESHOLD)
        frame_area = frame.shape[0] * frame.shape[1]
        boxes = []
        for d in raw:
            x1, y1, x2, y2 = (round(v * scale) for v in d["box"])
            box = {"x": max(0, x1), "y": max(0, y1),
                   "width": min(frame.shape[1], x2) - max(0, x1),
                   "height": min(frame.shape[0], y2) - max(0, y1)}
            if box["width"] * box["height"] <= MAX_BOX_AREA_SHARE * frame_area:
                boxes.append(box)
        return boxes

    def measure(self, frame: np.ndarray) -> dict:
        """Find the bricks and measure their color, without classifying them."""
        timings = {}
        if frame.mean() < MIN_FRAME_MEAN:
            return {"bricks": [], "timings": timings, "raw_detections": 0, "warning": "frame too dark"}
        start = time.monotonic()
        raw_boxes = self.detect_boxes(frame)
        timings["detection_s"] = round(time.monotonic() - start, 2)
        if not raw_boxes:
            return {"bricks": [], "timings": timings, "raw_detections": 0}

        start = time.monotonic()
        boxes = [d["bbox_px"] for d in split_scene(frame, raw_boxes)["detections"]]
        timings["split_s"] = round(time.monotonic() - start, 2)
        if not boxes:
            return {"bricks": [], "timings": timings, "raw_detections": len(raw_boxes)}

        start = time.monotonic()
        label_map = segment(self.segmenter, frame, [to_corners(b) for b in boxes])
        timings["segmentation_s"] = round(time.monotonic() - start, 2)

        start = time.monotonic()
        table = table_reference(frame, boxes)
        bricks, discarded = [], []
        for index, bbox in enumerate(boxes, 1):
            x, y, w, h = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
            mask = label_map == index
            coverage = float(mask[y:y + h, x:x + w].mean())
            if coverage < MIN_BRICK_COVERAGE:
                discarded.append({"bbox_px": bbox, "mask_coverage": round(coverage, 3)})
                continue
            use_mask = coverage >= MIN_MASK_COVERAGE
            region = mask if use_mask else box_region(bbox, frame.shape[:2])
            features = add_relative_lightness(brick_features(frame[region], table))
            lab = bgr_to_lab(frame[region])
            features["L_mode"] = histogram_mode(lab[:, 0])
            features["C_mode"] = histogram_mode(np.hypot(lab[:, 1], lab[:, 2]))
            bricks.append({
                "position": len(bricks) + 1,
                "mask_index": index,
                "bbox_px": bbox,
                "region": "sam" if use_mask else "box",
                "mask_coverage": round(coverage, 3),
                "all_features": features,
                "true_label": None,
            })
        timings["color_s"] = round(time.monotonic() - start, 2)
        return {"bricks": bricks, "timings": timings, "raw_detections": len(raw_boxes),
                "discarded_not_brick": discarded, "label_map": label_map}

    def classify(self, frame: np.ndarray) -> dict:
        result = self.measure(frame)
        for brick in result["bricks"]:
            features = brick.pop("all_features")
            brick["features"] = {k: round(features[k], 3) if math.isfinite(features[k]) else None
                                 for k in LOGGED_FEATURES}
            brick.update(self.reference.predict(features))
        result["reference"] = self.reference.name
        result["feature_set"] = self.reference.feature_set
        return result


def brick_region(frame: np.ndarray, result: dict, brick: dict) -> np.ndarray:
    label_map = result.get("label_map")
    if brick["region"] == "sam" and label_map is not None:
        return label_map == brick["mask_index"]
    return box_region(brick["bbox_px"], frame.shape[:2])


def draw_text_lines(canvas: np.ndarray, bbox: dict, lines: list[str], color: tuple) -> None:
    for i, text in enumerate(lines):
        y = bbox["y"] + 40 + i * 34
        (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.85, 2)
        cv2.rectangle(canvas, (bbox["x"] + 6, y - h - 6), (bbox["x"] + 14 + w, y + 6), (255, 255, 255), -1)
        cv2.putText(canvas, text, (bbox["x"] + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.85, color, 2, cv2.LINE_AA)


def draw_result(frame: np.ndarray, result: dict, pending: int | None = None) -> np.ndarray:
    """Brick outlines colored by prediction; green/red once the true label is known."""
    canvas = frame.copy()
    for brick in result["bricks"]:
        if brick["true_label"] is None:
            color = GOOD_BGR if brick["prediction"] == "good" else BAD_BGR
        else:
            color = CORRECT_BGR if brick["true_label"] == brick["prediction"] else ERROR_BGR
        contours, _ = cv2.findContours(brick_region(frame, result, brick).astype(np.uint8),
                                       cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 6)
        lines = [f"{brick['position']}: {brick['prediction'].upper()}", f"conf {brick['confidence']:.2f}"]
        if brick.get("band_offset") is not None:
            offset = brick["band_offset"]
            where = "in band" if offset == 0 else f"{'below' if offset < 0 else 'above'} {abs(offset):.1f}"
            lines.append(f"{brick['band_key']} {brick['band_value']:.1f} {where}")
        if brick["true_label"] is not None:
            lines.append(f"true {brick['true_label']}")
        elif pending == brick["position"]:
            lines.append("true? g / b")
        draw_text_lines(canvas, brick["bbox_px"], lines, color)
    if not result["bricks"]:
        message = result.get("warning", "no bricks found")
        cv2.putText(canvas, message, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255), 3)
    return canvas


def draw_calibration(frame: np.ndarray, result: dict, pending: int | None = None) -> np.ndarray:
    """Brick outlines colored by the label given during calibration."""
    canvas = frame.copy()
    for brick in result["bricks"]:
        label = brick["true_label"]
        color = {"good": GOOD_BGR, "bad": BAD_BGR}.get(label, PENDING_BGR)
        contours, _ = cv2.findContours(brick_region(frame, result, brick).astype(np.uint8),
                                       cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 6)
        lines = [f"{brick['position']}: {label.upper() if label else '?'}"]
        if pending == brick["position"]:
            lines.append("g good / b bad / n skip")
        draw_text_lines(canvas, brick["bbox_px"], lines, color)
    if not result["bricks"]:
        message = result.get("warning", "no bricks found")
        cv2.putText(canvas, message, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 255), 3)
    return canvas


WINDOW = "brick classifier"
QUIT_KEY = ord("q")


def show(image: np.ndarray) -> None:
    cv2.imshow(WINDOW, image)


def wait_key(delay_ms: int) -> int:
    """cv2.waitKey that returns q when the window was closed with its X button.

    A plain waitKey(0) never returns once the window is gone, which left the
    process (and the camera) blocked until it was killed.
    """
    if delay_ms > 0:
        key = cv2.waitKey(delay_ms) & 0xFF
        return QUIT_KEY if window_closed() else key
    while True:
        key = cv2.waitKey(50) & 0xFF
        if window_closed():
            return QUIT_KEY
        if key != 0xFF:
            return key


def window_closed() -> bool:
    try:
        return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True


def close_windows() -> None:
    """Destroy the window and pump events so Windows really removes it."""
    cv2.destroyAllWindows()
    for _ in range(5):
        cv2.waitKey(1)


def overlay_lines(frame: np.ndarray, lines: list[str]) -> np.ndarray:
    preview = cv2.resize(frame, (WIDTH // 2, HEIGHT // 2))
    for i, text in enumerate(lines):
        cv2.putText(preview, text, (12, 28 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(preview, text, (12, 28 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2, cv2.LINE_AA)
    return preview


def ask_labels(frame: np.ndarray, result: dict, draw, allow_skip_brick: bool) -> bool:
    """Ask g/b for each brick, left to right. Returns False if q was pressed.

    In calibration (allow_skip_brick) n leaves that brick unlabeled and moves on;
    in classification n stops labeling the rest of the capture.
    """
    for brick in result["bricks"]:
        show(cv2.resize(draw(frame, result, pending=brick["position"]), (WIDTH // 2, HEIGHT // 2)))
        key = wait_key(0)
        while key not in (ord("g"), ord("b"), ord("n"), ord("q")):
            key = wait_key(0)
        if key == ord("q"):
            return False
        if key == ord("n"):
            if allow_skip_brick:
                continue
            break
        brick["true_label"] = "good" if key == ord("g") else "bad"
    return True


def scene_lightness(frame: np.ndarray) -> float:
    """Median L* of the table band at the bottom of the frame."""
    height, width = frame.shape[:2]
    band = frame[height - 120:height - 20, round(width * 0.15):round(width * 0.85)]
    lab = cv2.cvtColor(band.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    return float(np.median(lab[..., 0]))


def lightness_line(current: float, reference: float | None) -> str:
    if reference is None:
        return f"scene L* {current:.0f}  (reference lightness unknown)"
    difference = current - reference
    if difference < -LIGHTNESS_TOLERANCE:
        status = "TOO DARK"
    elif difference > LIGHTNESS_TOLERANCE:
        status = "TOO BRIGHT"
    else:
        status = "OK"
    return f"scene L* {current:.0f}  reference {reference:.0f}  -> {status}"


class CameraStatus:
    """Settings, settings drift and scene lightness, refreshed every STATUS_EVERY frames."""

    def __init__(self, capture: cv2.VideoCapture) -> None:
        self.capture = capture
        self.frames = 0
        self.lines: list[str] = []

    def update(self, frame: np.ndarray, reference: "Reference | None",
               lightness_reference: float | None = None, label: str = "") -> list[str]:
        if self.frames % STATUS_EVERY == 0:
            camera = camera_properties(self.capture)
            target = lightness_reference if lightness_reference is not None else (
                reference.scene_lightness if reference else None)
            self.lines = [settings_line(self.capture), lightness_line(scene_lightness(frame), target) + label]
            drift = settings_drift(reference, camera) if reference else []
            if drift:
                self.lines.append("WARNING settings differ from calibration: " + ", ".join(drift))
        self.frames += 1
        return self.lines


def label_conflicts(rows: list[dict]) -> list[tuple[dict, dict]]:
    """Pairs of calibration bricks with almost the same color but opposite labels.

    Either the same brick was labeled differently (a misclick) or two bricks that
    color cannot separate carry different labels; both deserve a second look.
    """
    pairs = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if (a["label"] != b["label"] and abs(a["L_med"] - b["L_med"]) < CONFLICT_TOLERANCE
                    and abs(a["C_med"] - b["C_med"]) < CONFLICT_TOLERANCE):
                pairs.append((a, b))
    return pairs


def settings_drift(reference: "Reference", camera: dict) -> list[str]:
    """Camera settings that differ from the ones used during calibration."""
    if not reference.camera:
        return []
    return [f"{key} {reference.camera[key]:g}->{camera[key]:g}" for key in WATCHED_SETTINGS
            if key in reference.camera and abs(reference.camera[key] - camera[key]) > 0.5]


def calibration_self_check(rows: list[dict]) -> dict:
    """Leave-one-capture-out 1-NN accuracy of each feature set on the calibration."""
    scores = {}
    rows = [add_relative_lightness(dict(r)) for r in rows]
    for name, keys in FEATURE_OPTIONS.items():
        valid = [r for r in rows if usable(r, keys)]
        correct = total = 0
        for capture in sorted({r["photo"] for r in valid}):
            train = [r for r in valid if r["photo"] != capture]
            if not {"good", "bad"} <= {r["label"] for r in train}:
                continue
            reference = Reference(train, name, "self-check")
            for r in (r for r in valid if r["photo"] == capture):
                total += 1
                correct += reference.predict(r)["prediction"] == r["label"]
        scores[name] = {"accuracy": round(correct / total, 3) if total else None, "checked_bricks": total}
    return scores


def band_self_check(rows: list[dict]) -> float | None:
    """Leave-one-capture-out accuracy of the lightness band rule."""
    correct = total = 0
    for capture in sorted({r["photo"] for r in rows}):
        train = [r for r in rows if r["photo"] != capture]
        if not {"good", "bad"} <= {r["label"] for r in train}:
            continue
        low, high = fit_band(train, BAND_FEATURE)
        for r in (r for r in rows if r["photo"] == capture):
            total += 1
            correct += (low <= r[BAND_FEATURE] <= high) == (r["label"] == "good")
    return round(correct / total, 3) if total else None


def choose_feature_set(scores: dict) -> str:
    best = max(scores, key=lambda n: scores[n]["accuracy"] or 0)
    preferred = scores[PREFERRED_FEATURES]["accuracy"] or 0
    if (scores[best]["accuracy"] or 0) - preferred <= PREFERENCE_MARGIN:
        return PREFERRED_FEATURES
    return best


def run_calibration(capture: cv2.VideoCapture, classifier: BrickClassifier) -> Path | None:
    """Photograph labeled sample bricks and save them as the reference."""
    root = CALIBRATION_ROOT / time.strftime("%Y%m%d_%H%M%S")
    (root / "frames").mkdir(parents=True, exist_ok=True)
    rows, capture_ids = [], []
    message = "place sample bricks, press space"
    status = CameraStatus(capture)
    third_lightness = Reference.third_dataset().scene_lightness
    print(f"CALIBRATION. space capture, u undo, f finish, q quit. saving to {root}")

    while True:
        frame = read_frame(capture)
        goods = sum(r["label"] == "good" for r in rows)
        bads = len(rows) - goods
        # Before the first capture the lightness is compared with the third
        # dataset; afterwards with the calibration captures themselves, so the
        # light can be kept constant during the whole calibration.
        if rows:
            target, label = float(np.median([r["scene_lightness"] for r in rows])), " (this calibration)"
        else:
            target, label = third_lightness, " (third dataset)"
        lines = status.update(frame, None, target, label)
        show(overlay_lines(frame, [
            f"CALIBRATION   good {goods}  bad {bads}   (need {MIN_CALIBRATION_PER_CLASS} of each)",
            "space capture | u undo | f finish | s settings | q quit", *lines, message]))
        key = wait_key(1)
        if key == ord("q"):
            return None
        if key == ord("s"):
            capture.set(cv2.CAP_PROP_SETTINGS, 1)
        elif key == ord("u") and capture_ids:
            last = capture_ids.pop()
            rows = [r for r in rows if r["photo"] != last]
            message = f"removed capture {last}"
        elif key == ord("f"):
            if goods < MIN_CALIBRATION_PER_CLASS or bads < MIN_CALIBRATION_PER_CLASS:
                message = f"need at least {MIN_CALIBRATION_PER_CLASS} good and {MIN_CALIBRATION_PER_CLASS} bad bricks"
                continue
            scores = calibration_self_check(rows)
            feature_set = choose_feature_set(scores)
            band = fit_band(rows, BAND_FEATURE)
            data = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "camera": camera_properties(capture),
                    "band_" + BAND_FEATURE: [band[0], band[1]], "band_self_check": band_self_check(rows),
                    "scene_lightness": round(float(np.median([r["scene_lightness"] for r in rows])), 1),
                    "feature_set": feature_set, "self_check": scores,
                    "good_bricks": goods, "bad_bricks": bads, "rows": rows}
            path = root / "calibration.json"
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"calibration saved: {path}")
            for name, s in scores.items():
                print(f"   self-check {name:5s}: accuracy {s['accuracy']} on {s['checked_bricks']} bricks")
            print(f"   using feature set: {feature_set}; scene lightness L* {data['scene_lightness']}")
            print(f"   band rule: good if {band[0]:.1f} <= {BAND_FEATURE} <= {band[1]:.1f}; "
                  f"self-check accuracy {data['band_self_check']}")
            for r in sorted(rows, key=lambda r: r[BAND_FEATURE]):
                inside = band[0] <= r[BAND_FEATURE] <= band[1]
                if inside != (r["label"] == "good"):
                    print(f"   OUTSIDE EXPECTATION: {r['photo']}#{r['position']} {r['label']} "
                          f"{BAND_FEATURE} {r[BAND_FEATURE]:.1f} ({'inside' if inside else 'outside'} the band)")
            conflicts = label_conflicts(rows)
            for a, b in conflicts:
                print(f"   CHECK LABELS: {a['photo']}#{a['position']} {a['label']} and "
                      f"{b['photo']}#{b['position']} {b['label']} have the same color "
                      f"(L* {a['L_med']:.1f}/{b['L_med']:.1f}, C* {a['C_med']:.1f}/{b['C_med']:.1f})")
            best = scores[feature_set]["accuracy"] or 0
            if best < CALIBRATION_WARN_ACCURACY:
                print(f"   WARNING: calibration bricks are not well separated ({best:.0%}). "
                      "Check the light and the labels, or add more captures.")
            return path
        elif key == ord(" "):
            result = classifier.measure(frame)
            if not result["bricks"]:
                message = result.get("warning", "no bricks found, try again")
                continue
            if not ask_labels(frame, result, draw_calibration, allow_skip_brick=True):
                return None
            capture_id = f"cal{len(capture_ids) + 1:03d}"
            cv2.imwrite(str(root / "frames" / f"{capture_id}.jpg"), frame)
            lightness = round(scene_lightness(frame), 1)
            added = 0
            for brick in result["bricks"]:
                if brick["true_label"] is None:
                    continue
                rows.append({"photo": capture_id, "position": brick["position"], "label": brick["true_label"],
                             "scene_lightness": lightness,
                             "bbox_px": brick["bbox_px"], "region": brick["region"],
                             "mask_coverage": brick["mask_coverage"], **brick["all_features"]})
                added += 1
            capture_ids.append(capture_id)
            cv2.imwrite(str(root / "frames" / f"{capture_id}_labels.jpg"), draw_calibration(frame, result))
            message = f"{capture_id}: added {added} bricks"


class SessionLog:
    """Raw frames, result images, log.jsonl (per capture) and log.csv (per brick)."""

    CSV_FIELDS = ["capture_id", "time", "position", "prediction", "true_label", "correct",
                  "confidence", "distance_to_good", "distance_to_bad", "nearest_reference",
                  *LOGGED_FEATURES, "band_offset", "region", "mask_coverage"]

    def __init__(self) -> None:
        self.root = LOG_ROOT / time.strftime("%Y%m%d_%H%M%S")
        (self.root / "frames").mkdir(parents=True, exist_ok=True)
        (self.root / "results").mkdir(parents=True, exist_ok=True)
        self.count = 0
        self.labeled = 0
        self.correct = 0
        with (self.root / "log.csv").open("w", newline="", encoding="utf-8") as handle:
            csv.DictWriter(handle, self.CSV_FIELDS).writeheader()

    def write(self, frame: np.ndarray, result: dict, source: str, camera: dict | None) -> str:
        self.count += 1
        capture_id = f"{self.count:04d}"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        cv2.imwrite(str(self.root / "frames" / f"{capture_id}.jpg"), frame)
        cv2.imwrite(str(self.root / "results" / f"{capture_id}_result.jpg"), draw_result(frame, result))
        record = {"capture_id": capture_id, "time": stamp, "source": source, "camera": camera,
                  "scene_lightness": round(scene_lightness(frame), 1),
                  "reference": result.get("reference"), "feature_set": result.get("feature_set"),
                  "raw_detections": result["raw_detections"], "timings": result["timings"],
                  "warning": result.get("warning"),
                  "discarded_not_brick": result.get("discarded_not_brick", []),
                  "bricks": result["bricks"]}
        with (self.root / "log.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        with (self.root / "log.csv").open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, self.CSV_FIELDS)
            for b in result["bricks"]:
                correct = None if b["true_label"] is None else b["true_label"] == b["prediction"]
                if correct is not None:
                    self.labeled += 1
                    self.correct += int(correct)
                writer.writerow({"capture_id": capture_id, "time": stamp, "position": b["position"],
                                 "prediction": b["prediction"], "true_label": b["true_label"],
                                 "correct": correct, "confidence": b["confidence"],
                                 "distance_to_good": b["distance_to_good"], "distance_to_bad": b["distance_to_bad"],
                                 "nearest_reference": b["nearest_reference"], **b["features"],
                                 "band_offset": b.get("band_offset"),
                                 "region": b["region"], "mask_coverage": b["mask_coverage"]})
        return capture_id

    def summary(self) -> str:
        if not self.labeled:
            return f"{self.count} captures, no labeled bricks yet"
        return (f"{self.count} captures, {self.correct}/{self.labeled} labeled bricks correct "
                f"({self.correct / self.labeled:.0%})")


def print_result(capture_id: str, result: dict) -> None:
    t = result["timings"]
    print(f"[{capture_id}] {len(result['bricks'])} bricks in {sum(t.values()):.1f}s {t}")
    if result.get("warning"):
        print(f"   WARNING: {result['warning']}")
    for d in result.get("discarded_not_brick", []):
        print(f"   discarded detection (mask covers {d['mask_coverage']:.0%} of its box): {d['bbox_px']}")
    for b in result["bricks"]:
        truth = f"  true {b['true_label']}" if b["true_label"] else ""
        band = ""
        if b.get("band_offset") is not None:
            band = f"  {b['band_key']} {b['band_value']:.1f} offset {b['band_offset']:+.1f}"
        print(f"   {b['position']}: {b['prediction']:4s} conf {b['confidence']:.2f}  "
              f"nearest {b['nearest_reference']}{band}{truth}")


def run_photo(path: Path, reference_path: Path | None) -> None:
    reference = load_reference(reference_path)
    classifier = BrickClassifier(reference=reference, exclude_photo=path.stem)
    frame = cv2.imread(str(path))
    if frame is None:
        raise SystemExit(f"Could not read {path}")
    log = SessionLog()
    result = classifier.classify(frame)
    capture_id = log.write(frame, result, source=str(path), camera=None)
    print(f"reference: {classifier.reference.name} ({classifier.reference.feature_set} features)")
    print_result(capture_id, result)
    print(f"log: {log.root}")


def run_camera(camera_index: int, calibrate: bool, reference_path: Path | None) -> None:
    print("loading models...")
    classifier = BrickClassifier(reference=load_reference(reference_path))
    capture = open_camera(camera_index)
    try:
        while True:
            if calibrate:
                path = run_calibration(capture, classifier)
                if path is None:
                    print("calibration cancelled")
                    return
                classifier.reference = load_reference(path)
            # classify_loop() returns True when the user asked for a new calibration.
            if not classify_loop(capture, classifier, camera_index):
                return
            calibrate = True
    finally:
        # Always free the camera, also after an error or Ctrl+C, so the next run can open it.
        capture.release()
        close_windows()


def classify_loop(capture: cv2.VideoCapture, classifier: BrickClassifier, camera_index: int) -> bool:
    """Classification session. Returns True if a new calibration was requested."""
    log = SessionLog()
    reference = classifier.reference
    lightness = f"{reference.scene_lightness:.0f}" if reference.scene_lightness is not None else "unknown"
    print(f"CLASSIFICATION. reference: {reference.name} ({reference.feature_set} features, "
          f"{len(reference.rows)} bricks, scene L* {lightness}). space = classify, q = quit. log: {log.root}")

    status = CameraStatus(capture)
    recalibrate = False
    while True:
        frame = read_frame(capture)
        lines = ["CLASSIFY   space classify | c recalibrate | s settings | q quit",
                 *status.update(frame, reference), log.summary()]
        show(overlay_lines(frame, lines))
        key = wait_key(1)
        if key == ord("q"):
            break
        if key == ord("c"):
            recalibrate = True
            break
        if key == ord("s"):
            capture.set(cv2.CAP_PROP_SETTINGS, 1)
        if key != ord(" "):
            continue

        camera = camera_properties(capture)
        result = classifier.classify(frame)
        keep_going = ask_labels(frame, result, draw_result, allow_skip_brick=False)
        capture_id = log.write(frame, result, source=f"camera {camera_index}", camera=camera)
        print_result(capture_id, result)
        print(f"   {log.summary()}")
        show(cv2.resize(draw_result(frame, result), (WIDTH // 2, HEIGHT // 2)))
        if wait_key(1500) == QUIT_KEY or not keep_going:
            break

    print(f"session finished: {log.summary()}\nlog: {log.root}")
    return recalibrate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", type=int, default=0, help="camera index (0, 1, ...)")
    parser.add_argument("--image", type=Path, help="classify a saved photo instead of the camera")
    parser.add_argument("--calibrate", action="store_true", help="photograph labeled sample bricks first")
    parser.add_argument("--reference", type=Path, help="calibration.json from an earlier calibration")
    parser.add_argument("--features", choices=sorted(FEATURE_OPTIONS),
                        help="override the feature set stored in the calibration")
    parser.add_argument("--method", choices=["knn", "band"], default="knn",
                        help="knn: nearest calibration brick; band: good if L* mode is inside a band")
    parser.add_argument("--band", type=float, nargs=2, metavar=("LOW", "HIGH"),
                        help="fixed L* mode band instead of the one fitted on the calibration")
    args = parser.parse_args()
    global FEATURE_OVERRIDE, METHOD, BAND_OVERRIDE
    FEATURE_OVERRIDE = args.features
    METHOD = args.method
    BAND_OVERRIDE = tuple(args.band) if args.band else None
    if args.image:
        run_photo(args.image, args.reference)
    else:
        run_camera(args.camera, args.calibrate, args.reference)


if __name__ == "__main__":
    main()

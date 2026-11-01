"""Capture a per-brick, per-face dataset (top view) for synthetic images and YOLO training.

One brick at a time on a FIXED background (e.g. the bare wooden table, the belt).
First photograph the empty background (k, several times); the brick mask of every
photo then comes from the difference to that background, refined with MobileSAM.
It does not depend on the YOLO detector, so the photos can teach YOLO new
backgrounds where it fails today (YOLO only runs as a check, logged per photo).

Choose the brick (n / p) and its label (g / b), choose the face that looks up
(1-6), then turn the brick little by little. In auto mode a photo is saved each
time the brick is still again after a change: rotate, stop, rotate, stop.

Face numbers (write them on the brick with chalk or tape once):
  1 top (large face)   2 bottom (large face)   3 long side A   4 long side B
  5 end A              6 end B
Keys in the preview window:
  k       save an empty background photo (do this first, keep the area empty)
  n / p   next / previous brick          g / b   label of the current brick
  1-6     face that looks up             a       auto capture on / off
  space   save one photo now             u       undo the last photo
  s       camera driver settings         q       quit

A photo is NOT saved when: the brick has no label, there is no background yet,
the image is blurry, nothing differs from the background, the changed area touches
the image border (hand or object entering), or the background itself changed
(light or camera moved: take new k photos).

Output: <output>/<session>/
  brick_NN/face_F/img_NNN.jpg  + img_NNN_mask.png (brick mask) + img_NNN.json
  background/bg_NNN.jpg        bricks.json (label per brick)    log.csv
Usage:
  capture_brick_faces.py [--output Brick_Faces_Dataset] [--bricks 10] [--target 24]
                         [--exposure -5] [--focus 20] [--camera 0] [--no-sam] [--no-yolo]
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

from scripts.capture_bricks import HEIGHT, WIDTH, camera_properties, open_camera, read_frame, settings_line
from scripts.capture_top_view import MAX_CLIPPED_SHARE, light_measures
from scripts.run_mobile_sam import MODEL_PATH

DEFAULT_OUTPUT = PROJECT_ROOT / "Brick_Faces_Dataset"
YOLO_WEIGHTS = PROJECT_ROOT / "outputs2" / "yolo_runs" / "brick_seg_v2" / "weights" / "best.pt"
YOLO_CONFIDENCE = 0.5
FACE_NAMES = {1: "top", 2: "bottom", 3: "side_A", 4: "side_B", 5: "end_A", 6: "end_B"}
# Auto capture: the scene must be still for STILL_FRAMES frames (mean gray change
# below STILL_DIFF) and differ from the last saved photo by at least NEW_DIFF.
STILL_DIFF = 1.5
STILL_FRAMES = 8
NEW_DIFF = 4.0
MIN_SHARPNESS = 40.0
# Background difference (CIELAB distance, computed at 1/4 resolution). Brick and wood
# can differ by only ~7, so the threshold is low; it rises above the camera noise
# measured on the frame border when that noise is higher.
DIFF_SCALE = 4
MIN_DIFF = 5.0
NOISE_MARGIN = 2.0
MIN_BRICK_SHARE = 0.01
BORDER_PX = 6
# The background "changed" when the frame border differs from it by this much.
MAX_BORDER_DIFF = 6.0
# MobileSAM refinement is kept when it agrees with the difference mask.
MIN_SAM_IOU = 0.75
STATUS_EVERY = 15
LOG_FIELDS = ["file", "brick", "label", "face", "face_name", "time", "mode", "sharpness", "mask_source",
              "sam_iou", "angle", "length_px", "width_px", "yolo_detections", "yolo_iou",
              "frame_L", "center_L", "border_L", "clipped", "exposure", "gain", "white_balance_temperature", "focus"]


def small_gray(frame: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, (WIDTH // 8, HEIGHT // 8)), cv2.COLOR_BGR2GRAY), (5, 5), 0)


def sharpness(frame: np.ndarray) -> float:
    return float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def small_lab(frame: np.ndarray) -> np.ndarray:
    small = cv2.resize(frame, (frame.shape[1] // DIFF_SCALE, frame.shape[0] // DIFF_SCALE), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0).astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)


def iou(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.logical_and(a, b).sum() / max(1, np.logical_or(a, b).sum()))


def difference_mask(frame: np.ndarray, background: np.ndarray) -> tuple[np.ndarray | None, str]:
    """Brick mask from the difference to the empty background, or None and the reason."""
    distance = np.linalg.norm(small_lab(frame) - background, axis=2)
    h, w = distance.shape
    border = np.concatenate([distance[:BORDER_PX].ravel(), distance[-BORDER_PX:].ravel(),
                             distance[:, :BORDER_PX].ravel(), distance[:, -BORDER_PX:].ravel()])
    if float(np.median(border)) > MAX_BORDER_DIFF:
        return None, f"background changed (border {np.median(border):.1f}): take new k photos"
    threshold = max(MIN_DIFF, float(np.percentile(border, 99)) + NOISE_MARGIN)
    changed = (distance > threshold).astype(np.uint8)
    changed = cv2.morphologyEx(changed, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    changed = cv2.morphologyEx(changed, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(changed)
    if count < 2:
        return None, "nothing differs from the background"
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[biggest, cv2.CC_STAT_AREA] < MIN_BRICK_SHARE * h * w:
        return None, "changed area too small for a brick"
    x, y, bw, bh = stats[biggest, :4]
    if x <= BORDER_PX or y <= BORDER_PX or x + bw >= w - BORDER_PX or y + bh >= h - BORDER_PX:
        return None, "changed area touches the border (hand or object?): not saved"
    # Outer outline only: holes of a perforated face show the background but belong to the brick.
    contours, _ = cv2.findContours((labels == biggest).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    small = np.zeros((h, w), np.uint8)
    cv2.drawContours(small, contours, -1, 1, cv2.FILLED)
    return cv2.resize(small, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST).astype(bool), "ok"


def sam_refine(sam, frame: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, str, float | None]:
    """MobileSAM mask from the box of the difference mask, kept when both agree."""
    if sam is None:
        return mask, "difference", None
    ys, xs = np.nonzero(mask)
    box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]
    result = sam(frame, bboxes=[box], verbose=False)[0]
    if result.masks is None:
        return mask, "difference", None
    refined = result.masks.data[0].cpu().numpy().astype(bool)
    contours, _ = cv2.findContours(refined.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros(mask.shape, np.uint8)
    cv2.drawContours(filled, contours, -1, 1, cv2.FILLED)
    agreement = iou(filled.astype(bool), mask)
    return (filled.astype(bool), "sam", round(agreement, 3)) if agreement >= MIN_SAM_IOU else (mask, "difference", round(agreement, 3))


def yolo_check(model, frame: np.ndarray, mask: np.ndarray) -> dict:
    """How the current YOLO detector does on this photo (detections, best mask IoU)."""
    if model is None:
        return {}
    result = model.predict(frame, conf=YOLO_CONFIDENCE, retina_masks=True, verbose=False)[0]
    if result.masks is None:
        return {"yolo_detections": 0, "yolo_iou": 0.0}
    masks = result.masks.data.cpu().numpy().astype(bool)
    return {"yolo_detections": len(masks), "yolo_iou": round(max(iou(m, mask) for m in masks), 3)}


def outline(mask: np.ndarray) -> dict:
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea)
    (cx, cy), (w, h), angle = cv2.minAreaRect(contour)
    if w < h:
        w, h, angle = h, w, angle + 90
    x, y, bw, bh = cv2.boundingRect(contour)
    polygon = cv2.approxPolyDP(contour, 2.0, True).reshape(-1, 2)
    return {"bbox_px": {"x": x, "y": y, "width": bw, "height": bh}, "angle": round(float(angle) % 180, 1),
            "length_px": round(float(w), 1), "width_px": round(float(h), 1), "polygon": polygon.tolist()}


class Session:
    def __init__(self, root: Path, bricks: int) -> None:
        self.root = root
        self.labels = {b: None for b in range(1, bricks + 1)}
        self.rows: list[dict] = []
        self.saved: list[list[Path]] = []
        self.backgrounds: list[np.ndarray] = []

    def count(self, brick: int, face: int) -> int:
        return sum(1 for r in self.rows if r["brick"] == brick and r["face"] == face)

    def background(self) -> np.ndarray | None:
        return np.median(np.stack(self.backgrounds[-5:]), axis=0) if self.backgrounds else None

    @staticmethod
    def next_index(folder: Path, prefix: str) -> int:
        numbers = [int(p.stem.split("_")[1]) for p in folder.glob(f"{prefix}_*.jpg")]
        return max(numbers, default=0) + 1

    def write(self) -> None:
        (self.root / "bricks.json").write_text(json.dumps(
            {f"brick_{b:02d}": label for b, label in self.labels.items()}, indent=2), encoding="utf-8")
        with (self.root / "log.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, LOG_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.rows)


def preview(frame: np.ndarray, lines: list[str], warn: set[int], overlay: np.ndarray | None) -> np.ndarray:
    image = cv2.resize(frame, (WIDTH // 2, HEIGHT // 2))
    if overlay is not None:
        contours, _ = cv2.findContours(cv2.resize(overlay.astype(np.uint8), (WIDTH // 2, HEIGHT // 2)),
                                       cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(image, contours, -1, (0, 220, 0), 2)
    for i, text in enumerate(lines):
        color = (0, 0, 255) if i in warn else (0, 0, 0)
        cv2.putText(image, text, (12, 28 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(image, text, (12, 28 + i * 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2, cv2.LINE_AA)
    return image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bricks", type=int, default=10, help="number of physical bricks")
    parser.add_argument("--target", type=int, default=24, help="photos wanted per face (shown as progress)")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--exposure", type=float, help="override exposure (C920: -4 brighter ... -7 darker)")
    parser.add_argument("--focus", type=float, help="override manual focus")
    parser.add_argument("--no-sam", action="store_true", help="keep the background-difference mask, no MobileSAM")
    parser.add_argument("--no-yolo", action="store_true", help="do not log the YOLO check")
    args = parser.parse_args()

    from ultralytics import SAM, YOLO
    sam = None if args.no_sam else SAM(str(MODEL_PATH))
    yolo = None if args.no_yolo else YOLO(str(YOLO_WEIGHTS))
    session = Session(args.output / time.strftime("%Y%m%d_%H%M%S"), args.bricks)
    session.root.mkdir(parents=True, exist_ok=True)
    capture = open_camera(args.camera)
    if args.exposure is not None:
        capture.set(cv2.CAP_PROP_EXPOSURE, args.exposure)
    if args.focus is not None:
        capture.set(cv2.CAP_PROP_FOCUS, args.focus)
    session.write()

    brick, face, auto = 1, 1, False
    previous, last_saved, still = None, None, 0
    frames, settings, light = 0, settings_line(capture), {}
    overlay = None
    message = "empty the area and press k (2-3 times) for the background; then g / b, face 1-6, a for auto"
    print(f"saving to {session.root}")

    def save(frame: np.ndarray, mode: str) -> str:
        nonlocal overlay
        if session.labels[brick] is None:
            return f"brick {brick} has no label: press g or b first"
        background = session.background()
        if background is None:
            return "no background yet: empty the area and press k"
        sharp = sharpness(frame)
        if sharp < MIN_SHARPNESS:
            return f"too blurry ({sharp:.0f} < {MIN_SHARPNESS:.0f}): hold still"
        mask, reason = difference_mask(frame, background)
        if mask is None:
            return reason
        mask, source, sam_iou = sam_refine(sam, frame, mask)
        folder = session.root / f"brick_{brick:02d}" / f"face_{face}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"img_{session.next_index(folder, 'img'):03d}.jpg"
        mask_path = path.with_name(path.stem + "_mask.png")
        cv2.imwrite(str(path), frame)
        cv2.imwrite(str(mask_path), mask.astype(np.uint8) * 255)
        overlay = mask
        measures, camera = light_measures(frame), camera_properties(capture)
        record = {"file": str(path.relative_to(session.root)).replace("\\", "/"), "brick": brick,
                  "label": session.labels[brick], "face": face, "face_name": FACE_NAMES[face],
                  "time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": mode, "sharpness": round(sharp, 1),
                  "mask_source": source, "sam_iou": sam_iou, **outline(mask), **yolo_check(yolo, frame, mask),
                  **measures, "camera": camera}
        path.with_suffix(".json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        session.rows.append({**record, **{k: camera[k] for k in ("exposure", "gain", "white_balance_temperature", "focus")}})
        session.saved.append([path, mask_path, path.with_suffix(".json")])
        session.write()
        yolo_note = (f"  YOLO {record['yolo_detections']} det, IoU {record['yolo_iou']:.2f}"
                     if "yolo_detections" in record else "")
        return f"saved {record['file']} ({session.count(brick, face)}/{args.target}) mask {source}{yolo_note}"

    try:
        while True:
            frame = read_frame(capture)
            gray = small_gray(frame).astype(np.int16)
            change = float(np.abs(gray - previous).mean()) if previous is not None else 99.0
            previous = gray
            still = still + 1 if change < STILL_DIFF else 0
            if frames % STATUS_EVERY == 0:
                settings, light = settings_line(capture), light_measures(frame)
            frames += 1

            if auto and still == STILL_FRAMES:
                novelty = float(np.abs(gray - last_saved).mean()) if last_saved is not None else 99.0
                if novelty >= NEW_DIFF:
                    message = save(frame, "auto")
                    if message.startswith("saved"):
                        last_saved = gray

            label = session.labels[brick] or "NO LABEL (g / b)"
            lines = [settings,
                     f"light: center L* {light['center_L']}  border L* {light['border_L']}  clipped {light['clipped']:.1%}"
                     f"   backgrounds {len(session.backgrounds)}",
                     f"BRICK {brick}/{args.bricks}  {label}   FACE {face} {FACE_NAMES[face]}   "
                     f"{session.count(brick, face)}/{args.target} photos   AUTO {'ON' if auto else 'off'}"
                     f"   {'still' if still >= STILL_FRAMES else 'moving'}",
                     "k background | n/p brick | g/b label | 1-6 face | a auto | space save | u undo | q quit",
                     message]
            warn = {1} if light["clipped"] > MAX_CLIPPED_SHARE or not session.backgrounds else set()
            if session.labels[brick] is None:
                warn.add(2)
            if not message.startswith(("saved", "brick", "face", "auto", "background", "removed")):
                warn.add(4)
            cv2.imshow("brick faces capture", preview(frame, lines, warn, overlay))
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("s"):
                capture.set(cv2.CAP_PROP_SETTINGS, 1)
            elif key == ord("k"):
                folder = session.root / "background"
                folder.mkdir(exist_ok=True)
                path = folder / f"bg_{session.next_index(folder, 'bg'):03d}.jpg"
                cv2.imwrite(str(path), frame)
                path.with_suffix(".json").write_text(json.dumps(
                    {"file": path.name, "time": time.strftime("%Y-%m-%d %H:%M:%S"), **light_measures(frame),
                     "camera": camera_properties(capture)}, indent=2), encoding="utf-8")
                session.backgrounds.append(small_lab(frame))
                message = f"background saved: {path.name} ({len(session.backgrounds)} so far; the last 5 are used)"
            elif key in (ord("n"), ord("p")):
                brick = min(args.bricks, brick + 1) if key == ord("n") else max(1, brick - 1)
                face, auto, overlay, last_saved = 1, False, None, None
                message = f"brick {brick}: label {session.labels[brick] or 'not set (g / b)'}; auto capture off"
            elif key in (ord("g"), ord("b")):
                session.labels[brick] = "good" if key == ord("g") else "bad"
                session.write()
                message = f"brick {brick} is {session.labels[brick]}"
            elif ord("1") <= key <= ord("6"):
                face, auto, overlay, last_saved = key - ord("0"), False, None, None
                message = f"face {face} ({FACE_NAMES[face]}) up: {session.count(brick, face)} photos so far; auto off"
            elif key == ord("a"):
                auto, last_saved = not auto, None
                message = "auto capture ON: turn the brick a little, stop, wait for the save" if auto else "auto capture off"
            elif key == ord(" "):
                message = save(frame, "manual")
                if message.startswith("saved"):
                    last_saved = gray
            elif key == ord("u"):
                if session.saved:
                    for f in session.saved.pop():
                        f.unlink(missing_ok=True)
                    removed = session.rows.pop()
                    session.write()
                    overlay, last_saved = None, None
                    message = f"removed {removed['file']}"
                else:
                    message = "nothing to undo"
    finally:
        capture.release()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
    print(f"session finished: {len(session.rows)} photos, {len(session.backgrounds)} backgrounds in {session.root}")
    for b, label in session.labels.items():
        counts = [session.count(b, f) for f in FACE_NAMES]
        if any(counts):
            print(f"  brick {b:2d} {label or '-':4s} faces 1-6: {counts}")
    yolo_rows = [r for r in session.rows if "yolo_detections" in r]
    if yolo_rows:
        good = sum(r["yolo_detections"] == 1 and r["yolo_iou"] >= 0.8 for r in yolo_rows)
        print(f"  current YOLO on this background: {good}/{len(yolo_rows)} photos with exactly one good detection")


if __name__ == "__main__":
    main()

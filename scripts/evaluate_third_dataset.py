"""Evaluate color classifiers on Third_Dataset_Bricks (fixed camera settings).

Bricks come from split_brick_row.py + run_mobile_sam.py. The color region is
the MobileSAM mask, or the shrunken box when the mask covers too little of it.
Labels come from the photo name (GOOD/BAD) or, for MIX photos, from the "G"
marks written on the good bricks (read by hand, listed in MIX_GOOD_POSITIONS).
The marks are never used by the classifiers.

Protocol: leave-one-photo-out. Each photo is classified with a model built only
from the other photos, which is the closest setting to the live test. Near-
duplicate photos (same bricks, same order) are held out together (PHOTO_GROUPS)
so a brick cannot be matched with its own copy.
"""

import json
import sys
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.analyze_second_dataset_colors import BOX_MARGIN_RATIO, brick_features, srgb_to_linear
from scripts.predict_good_prototype import confusion, fit_prototype, score


IMAGE_ROOT = PROJECT_ROOT / "Third_Dataset_Bricks"
DETECTIONS_PATH = PROJECT_ROOT / "outputs2" / "third_dataset" / "row_split" / "detections_clean.json"
MASK_ROOT = PROJECT_ROOT / "outputs2" / "third_dataset" / "mobile_sam"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "third_dataset" / "evaluation"

MIN_MASK_COVERAGE = 0.55

# 1-based positions (left to right) of bricks marked "G" in each mixed photo.
MIX_GOOD_POSITIONS = {
    "MIX_01": [1],
    "MIX_02": [1, 5],
    "MIX_03": [1, 5],
    "MIX_04": [1, 2, 6],
    "MIX_05": [1, 5, 6],
    "MIX_06": [2, 6, 7],
    "MIX_07": [1, 3, 7, 8],
    "MIX_08": [2, 4, 8, 9],
}

# Near-duplicate photos, held out as one fold.
PHOTO_GROUPS = {"BAD_02": "BAD_01", "BAD_04": "BAD_03"}

VARIANTS = {
    "raw_L_C": ["L_med", "C_med"],
    "raw_L_a_b": ["L_med", "a_med", "b_med"],
    "raw_L_C_h": ["L_med", "C_med", "h_med"],
    "table_L_C": ["dL_wood", "C_med"],
    "raw_L_C_spread": ["L_med", "C_med", "L_iqr", "C_iqr"],
}
PROTOTYPE_QUANTILES = (0.9, 1.0)

GOOD_COLOR = "#2a78d6"
BAD_COLOR = "#eb6834"
TEXT_COLOR = "#52514e"
CORRECT_BGR = (12, 163, 12)
ERROR_BGR = (59, 59, 208)


def labels_for(photo: str, count: int) -> list[str]:
    if photo.startswith("GOOD"):
        return ["good"] * count
    if photo.startswith("BAD"):
        return ["bad"] * count
    good = MIX_GOOD_POSITIONS[photo]
    return ["good" if i in good else "bad" for i in range(1, count + 1)]


def table_reference(image: np.ndarray, boxes: list[dict]) -> np.ndarray:
    """Median linear RGB of the table strip just below the bricks."""
    y = max(b["y"] + b["height"] for b in boxes)
    x1 = min(b["x"] for b in boxes)
    x2 = max(b["x"] + b["width"] for b in boxes)
    pixels = image[y + 25:min(image.shape[0], y + 140), x1:x2].reshape(-1, 3).astype(np.float32)
    return np.median(srgb_to_linear(pixels[:, ::-1]), axis=0)


def box_region(bbox: dict, shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, bool)
    mx, my = round(bbox["width"] * BOX_MARGIN_RATIO), round(bbox["height"] * BOX_MARGIN_RATIO)
    mask[bbox["y"] + my:bbox["y"] + bbox["height"] - my, bbox["x"] + mx:bbox["x"] + bbox["width"] - mx] = True
    return mask


def measure() -> list[dict]:
    detections = json.loads(DETECTIONS_PATH.read_text(encoding="utf-8"))
    rows = []
    for name, record in sorted(detections.items()):
        photo = Path(name).stem
        image = cv2.imread(str(IMAGE_ROOT / name))
        label_map = cv2.imread(str(MASK_ROOT / f"{photo}_labels.png"), cv2.IMREAD_GRAYSCALE)
        boxes = [d["bbox_px"] for d in record["detections"]]
        reference = table_reference(image, boxes)
        labels = labels_for(photo, len(boxes))
        for index, (bbox, label) in enumerate(zip(boxes, labels), 1):
            box = box_region(bbox, image.shape[:2])
            mask = label_map == index
            x, y, w, h = bbox["x"], bbox["y"], bbox["width"], bbox["height"]
            coverage = float(mask[y:y + h, x:x + w].mean())
            region = mask if coverage >= MIN_MASK_COVERAGE else box
            rows.append({
                "photo": photo, "position": index, "label": label, "bbox_px": bbox,
                "region": "sam" if coverage >= MIN_MASK_COVERAGE else "box",
                "mask_coverage": round(coverage, 3),
                **brick_features(image[region], reference),
            })
    return rows


def standardize(train: np.ndarray, test: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center, spread = train.mean(axis=0), train.std(axis=0) + 1e-6
    return (train - center) / spread, (test - center) / spread


def leave_one_photo_out(rows: list[dict], keys: list[str], method: str, quantile: float = 0.9) -> list[dict]:
    """Prototype (one class, good only) or 1-nearest-neighbor (both classes)."""
    predictions = []
    fold = {r["photo"]: PHOTO_GROUPS.get(r["photo"], r["photo"]) for r in rows}
    for held_out in sorted(set(fold.values())):
        train = [r for r in rows if fold[r["photo"]] != held_out]
        test = [r for r in rows if fold[r["photo"]] == held_out]
        if method == "prototype":
            from scripts import predict_good_prototype as proto
            proto.GOOD_ACCEPT_QUANTILE = quantile
            prototype = fit_prototype([r for r in train if r["label"] == "good"], keys)
            predictions += [{**r, **score(r, prototype)} for r in test]
        else:
            Xtr = np.array([[r[k] for k in keys] for r in train])
            Xte = np.array([[r[k] for k in keys] for r in test])
            Xtr, Xte = standardize(Xtr, Xte)
            for r, x in zip(test, Xte):
                distances = np.linalg.norm(Xtr - x, axis=1)
                nearest = train[int(np.argmin(distances))]
                predictions.append({**r, "predicted": nearest["label"],
                                    "nearest": f"{nearest['photo']}#{nearest['position']}"})
    return predictions


def separability(rows: list[dict], keys: list[str]) -> float:
    """AUC of the distance to the all-data good mean (bad should be farther)."""
    X = np.array([[r[k] for k in keys] for r in rows])
    good = np.array([r["label"] == "good" for r in rows])
    center, spread = X[good].mean(axis=0), X[good].std(axis=0) + 1e-6
    d = np.linalg.norm((X - center) / spread, axis=1)
    return float((d[~good][:, None] > d[good][None, :]).mean())


def draw(image: np.ndarray, predictions: list[dict], label_map: np.ndarray) -> np.ndarray:
    canvas = image.copy()
    for p in predictions:
        correct = p["predicted"] == p["label"]
        color = CORRECT_BGR if correct else ERROR_BGR
        region = (label_map == p["position"]) if p["region"] == "sam" else box_region(p["bbox_px"], image.shape[:2])
        contours, _ = cv2.findContours(region.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 5 if correct else 9)
        b = p["bbox_px"]
        lines = ["OK" if correct else "ERROR", f"pred {p['predicted']}", f"true {p['label']}"]
        if "ratio" in p:
            lines.append(f"d/thr {p['ratio']:.2f}")
        for i, text in enumerate(lines):
            y = b["y"] + 40 + i * 32
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)
            cv2.rectangle(canvas, (b["x"] + 6, y - h - 6), (b["x"] + 14 + w, y + 6), (255, 255, 255), -1)
            cv2.putText(canvas, text, (b["x"] + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)
    return canvas


def draw_labels(image: np.ndarray, rows: list[dict]) -> np.ndarray:
    """Ground-truth check image: label assigned to each brick."""
    canvas = image.copy()
    for r in rows:
        b = r["bbox_px"]
        color = (214, 120, 42) if r["label"] == "good" else (52, 104, 235)
        cv2.rectangle(canvas, (b["x"], b["y"]), (b["x"] + b["width"], b["y"] + b["height"]), color, 5)
        text = f"{r['position']} {r['label']}"
        cv2.rectangle(canvas, (b["x"] + 6, b["y"] + 12), (b["x"] + 150, b["y"] + 50), (255, 255, 255), -1)
        cv2.putText(canvas, text, (b["x"] + 10, b["y"] + 42), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)
    return canvas


def plot_feature_space(rows: list[dict], path: Path) -> None:
    pairs = [("L_med", "C_med"), ("a_med", "b_med"), ("L_med", "h_med")]
    names = {"L_med": "L* median", "C_med": "Chroma C* median", "a_med": "a* median",
             "b_med": "b* median", "h_med": "Hue angle (deg)"}
    figure, axes = plt.subplots(1, 3, figsize=(16, 5))
    for axis, (xk, yk) in zip(axes, pairs):
        for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
            subset = [r for r in rows if r["label"] == label]
            axis.scatter([r[xk] for r in subset], [r[yk] for r in subset], s=46, c=color, marker=marker,
                         edgecolors="white", linewidths=1.2, label=label, zorder=3)
        axis.set_xlabel(names[xk], color=TEXT_COLOR, fontsize=9)
        axis.set_ylabel(names[yk], color=TEXT_COLOR, fontsize=9)
        axis.spines[["top", "right"]].set_visible(False)
        axis.spines[["left", "bottom"]].set_color("#b5b4ad")
        axis.tick_params(colors=TEXT_COLOR, labelsize=8)
        axis.grid(color="#e8e7e2", linewidth=0.6)
        axis.set_axisbelow(True)
    axes[0].legend(frameon=False, fontsize=9)
    figure.suptitle("Third dataset (fixed camera): every brick in every photo", color="#0b0b0b", fontsize=11)
    figure.tight_layout()
    figure.savefig(path, dpi=130, facecolor="#fcfcfb")
    plt.close(figure)


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = measure()
    (OUTPUT_ROOT / "brick_features.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    plot_feature_space(rows, OUTPUT_ROOT / "feature_space.png")

    for photo in sorted({r["photo"] for r in rows}):
        image = cv2.imread(str(IMAGE_ROOT / f"{photo}.jpg"))
        cv2.imwrite(str(OUTPUT_ROOT / f"{photo}_labels.jpg"), draw_labels(image, [r for r in rows if r["photo"] == photo]))

    results, all_predictions = [], {}
    for name, keys in VARIANTS.items():
        for method, quantile in [("prototype", q) for q in PROTOTYPE_QUANTILES] + [("1nn", None)]:
            tag = f"{name}|{method}" + (f"_q{quantile}" if quantile else "")
            predictions = leave_one_photo_out(rows, keys, method, quantile or 0.9)
            all_predictions[tag] = predictions
            errors = [f"{p['photo']}#{p['position']}({p['label'][0]})" for p in predictions if p["predicted"] != p["label"]]
            results.append({"model": tag, "features": keys, **confusion(predictions),
                            "auc": round(separability(rows, keys), 3), "errors": errors})
    results.sort(key=lambda r: (-r["accuracy"], -r["bad_recall"]))
    (OUTPUT_ROOT / "comparison.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    best = results[0]["model"]
    for photo in sorted({r["photo"] for r in rows}):
        image = cv2.imread(str(IMAGE_ROOT / f"{photo}.jpg"))
        label_map = cv2.imread(str(MASK_ROOT / f"{photo}_labels.png"), cv2.IMREAD_GRAYSCALE)
        cv2.imwrite(str(OUTPUT_ROOT / f"{photo}_prediction.jpg"),
                    draw(image, [p for p in all_predictions[best] if p["photo"] == photo], label_map))

    goods = sum(r["label"] == "good" for r in rows)
    print(f"{len(rows)} brick views ({goods} good, {len(rows) - goods} bad), "
          f"{sum(r['region'] == 'box' for r in rows)} measured with box fallback")
    print(f"{'model':36s} acc   good ok  bad rej  auc   errors")
    for r in results:
        g = r["good_accepted"] + r["good_rejected"]
        b = r["bad_rejected"] + r["bad_accepted"]
        print(f"{r['model']:36s} {r['accuracy']:.2f}  {r['good_accepted']:2d}/{g}    {r['bad_rejected']:2d}/{b}   "
              f"{r['auc']:.2f}  {' '.join(r['errors'][:8])}")
    print(f"\nprediction overlays use: {best}")


if __name__ == "__main__":
    main()

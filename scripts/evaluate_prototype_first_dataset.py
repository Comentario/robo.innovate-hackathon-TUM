"""Check whether prototype V4 holds on the first dataset (standing bricks).

Each clean scene of Initial_Dataset_Bricks_LEGO is measured with two regions
(the shrunken corrected box and the MobileSAM mask) and two light references
(the wooden table below the bricks and the wall above them). Then:

- transfer: the prototype fitted on Second_Dataset_Bricks is applied as is;
- leave-one-brick-out: a prototype is fitted on the good bricks of this dataset
  while one whole physical brick (all its photos) is held out.

Physical identities follow the left-to-right order seen in the labeled photos
(6B_L100_S, 3B_L100_S); 7B adds an unlabeled brick that is skipped.
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


IMAGE_ROOT = PROJECT_ROOT / "Initial_Dataset_Bricks_LEGO"
DETECTIONS_PATH = PROJECT_ROOT / "outputs2" / "grounding_dino_clean" / "detections_clean.json"
MASK_ROOT = PROJECT_ROOT / "outputs2" / "first_dataset" / "mobile_sam"
SECOND_DATASET_PROTOTYPE = PROJECT_ROOT / "outputs2" / "second_dataset" / "prototype_a" / "prototype.json"
SECOND_DATASET_FEATURES = PROJECT_ROOT / "outputs2" / "second_dataset" / "color_analysis" / "brick_features.json"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "first_dataset" / "prototype_v4"

SIX = ["B", "C", "D", "E", "F", "G"]
SCENE_BRICKS = {
    **{f"1B_{c}_NS": ["Y1"] for c in ("L0", "L100", "L50")},
    **{f"3B_{c}_NS": ["X1", "X2", "X3"] for c in ("L0", "L100", "L20", "L60")},
    **{f"5B_{c}_NS": SIX[1:] for c in ("L100", "L20", "L60", "L80", "NL")},
    **{f"6B_{c}_NS": SIX for c in ("L0", "L100", "L20", "L60")},
    **{f"7B_{c}_NS": ["A"] + SIX for c in ("0", "L100", "L20", "L60")},
}
LABELS = {"B": "bad", "C": "bad", "D": "bad", "E": "bad", "F": "good", "G": "good",
          "X1": "bad", "X2": "bad", "X3": "good", "Y1": "good"}

V4 = ["dL_wood", "C_med"]
CONFIGS = {
    "V4_box_table": ("box", "table", V4),
    "V4_sam_table": ("sam", "table", V4),
    "V4_box_wall": ("box", "wall", V4),
    "V4_sam_wall": ("sam", "wall", V4),
    "V0_box_table": ("box", "table", ["dL_wood", "C_med", "L_iqr", "C_iqr"]),
    "V0_sam_table": ("sam", "table", ["dL_wood", "C_med", "L_iqr", "C_iqr"]),
}

GOOD_COLOR = "#2a78d6"
BAD_COLOR = "#eb6834"
TEXT_COLOR = "#52514e"
CORRECT_BGR = (12, 163, 12)
ERROR_BGR = (59, 59, 208)


def reference_rgb(image: np.ndarray, boxes: list[dict], which: str) -> np.ndarray:
    """Median linear RGB of the table strip below or the wall band above the bricks."""
    height, width = image.shape[:2]
    x1 = max(min(b["x"] for b in boxes), round(width * 0.12))
    x2 = max(b["x"] + b["width"] for b in boxes)
    if which == "table":
        y1 = max(b["y"] + b["height"] for b in boxes) + 25
        y2 = height - 20
    else:
        y1 = round(height * 0.08)
        y2 = min(b["y"] for b in boxes) - 40
    pixels = image[y1:y2, x1:x2].reshape(-1, 3).astype(np.float32)
    return np.median(srgb_to_linear(pixels[:, ::-1]), axis=0)


def box_region(bbox: dict, shape: tuple[int, int]) -> np.ndarray:
    mask = np.zeros(shape, bool)
    mx, my = round(bbox["width"] * BOX_MARGIN_RATIO), round(bbox["height"] * BOX_MARGIN_RATIO)
    mask[bbox["y"] + my:bbox["y"] + bbox["height"] - my, bbox["x"] + mx:bbox["x"] + bbox["width"] - mx] = True
    return mask


def measure_scenes() -> list[dict]:
    """One row per (scene, brick, region, reference) with V0/V4 features."""
    detections = json.loads(DETECTIONS_PATH.read_text(encoding="utf-8"))
    rows = []
    for scene, bricks in SCENE_BRICKS.items():
        record = detections[f"{scene}.jpg"]
        if len(record["detections"]) != len(bricks):
            raise ValueError(f"{scene}: {len(record['detections'])} boxes for {len(bricks)} bricks")
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        labels_map = cv2.imread(str(MASK_ROOT / f"{scene}_labels.png"), cv2.IMREAD_GRAYSCALE)
        boxes = [d["bbox_px"] for d in record["detections"]]
        references = {which: reference_rgb(image, boxes, which) for which in ("table", "wall")}
        for index, (detection, brick) in enumerate(zip(record["detections"], bricks), 1):
            if brick not in LABELS:
                continue
            regions = {"box": box_region(detection["bbox_px"], image.shape[:2]),
                       "sam": labels_map == index}
            for region_name, region in regions.items():
                for reference_name, reference in references.items():
                    rows.append({
                        "scene": scene, "condition": scene.split("_")[1], "brick": brick,
                        "label": LABELS[brick], "region": region_name, "reference": reference_name,
                        "pixels": int(region.sum()), "bbox_px": detection["bbox_px"],
                        **brick_features(image[region], reference),
                    })
    return rows


def leave_one_brick_out(rows: list[dict], keys: list[str]) -> list[dict]:
    predictions = []
    for brick in sorted({r["brick"] for r in rows}):
        prototype = fit_prototype([r for r in rows if r["brick"] != brick and r["label"] == "good"], keys)
        predictions += [{**r, **score(r, prototype)} for r in rows if r["brick"] == brick]
    return predictions


def per_brick(predictions: list[dict]) -> dict:
    return {b: f"{sum(p['predicted'] == 'good' for p in predictions if p['brick'] == b)}"
               f"/{sum(p['brick'] == b for p in predictions)} accepted ({LABELS[b]})"
            for b in sorted({p["brick"] for p in predictions})}


def draw(image: np.ndarray, predictions: list[dict], labels_map: np.ndarray | None) -> np.ndarray:
    canvas = image.copy()
    for p in predictions:
        correct = p["predicted"] == p["label"]
        color = CORRECT_BGR if correct else ERROR_BGR
        b = p["bbox_px"]
        if labels_map is not None:
            region = (labels_map == p["index"]).astype(np.uint8)
        else:
            region = box_region(b, image.shape[:2]).astype(np.uint8)
        contours, _ = cv2.findContours(region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 5 if correct else 8)
        lines = [f"{p['brick']} {'OK' if correct else 'ERROR'}", f"pred {p['predicted']}",
                 f"true {p['label']}", f"d/thr {p['ratio']:.2f}"]
        for i, text in enumerate(lines):
            y = b["y"] + 40 + i * 32
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 2)
            cv2.rectangle(canvas, (b["x"] + 6, y - h - 6), (b["x"] + 14 + w, y + 6), (255, 255, 255), -1)
            cv2.putText(canvas, text, (b["x"] + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.75, color, 2, cv2.LINE_AA)
    return canvas


def style_axis(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#b5b4ad")
    axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axis.grid(color="#e8e7e2", linewidth=0.6)
    axis.set_axisbelow(True)


def plot_feature_space(first_rows: list[dict], second_rows: list[dict], prototype: dict, path: Path) -> None:
    """Same V4 axes for both datasets, so the camera/scene shift is visible."""
    panels = [("Second dataset (top faces)", second_rows),
              ("First dataset, box region, table reference",
               [r for r in first_rows if r["region"] == "box" and r["reference"] == "table"]),
              ("First dataset, MobileSAM mask, table reference",
               [r for r in first_rows if r["region"] == "sam" and r["reference"] == "table"])]
    figure, axes = plt.subplots(1, 3, figsize=(16, 5), sharex=True, sharey=True)
    center, spread, threshold = (np.array(prototype[k]) if k != "threshold" else prototype[k]
                                 for k in ("center", "spread", "threshold"))
    for axis, (title, rows) in zip(axes, panels):
        ellipse = plt.matplotlib.patches.Ellipse(center, 2 * threshold * spread[0], 2 * threshold * spread[1],
                                                 fill=False, edgecolor="#0b0b0b", linewidth=1.2, linestyle="--")
        axis.add_patch(ellipse)
        for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
            subset = [r for r in rows if r["label"] == label]
            axis.scatter([r["dL_wood"] for r in subset], [r["C_med"] for r in subset], s=46, c=color,
                         marker=marker, edgecolors="white", linewidths=1.2, label=label, zorder=3)
        axis.set_title(title, color="#0b0b0b", fontsize=10)
        axis.set_xlabel("L* minus table (wood) L*", color=TEXT_COLOR, fontsize=9)
        style_axis(axis)
    axes[0].set_ylabel("Chroma C* median", color=TEXT_COLOR, fontsize=9)
    axes[0].legend(frameon=False, fontsize=9)
    figure.text(0.5, 0.005, "Dashed ellipse: acceptance region of the second-dataset prototype",
                ha="center", color=TEXT_COLOR, fontsize=9)
    figure.tight_layout(rect=(0, 0.03, 1, 1))
    figure.savefig(path, dpi=130, facecolor="#fcfcfb")
    plt.close(figure)


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = measure_scenes()
    for row in rows:
        row["index"] = SCENE_BRICKS[row["scene"]].index(row["brick"]) + 1
    (OUTPUT_ROOT / "brick_features.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    transfer_prototype = json.loads(SECOND_DATASET_PROTOTYPE.read_text(encoding="utf-8"))
    results = {}
    for region in ("box", "sam"):
        subset = [r for r in rows if r["region"] == region and r["reference"] == "table"]
        predictions = [{**r, **score(r, transfer_prototype)} for r in subset]
        results[f"transfer_V4_{region}_table"] = {**confusion(predictions), "per_brick": per_brick(predictions)}

    best_predictions = {}
    for name, (region, reference, keys) in CONFIGS.items():
        subset = [r for r in rows if r["region"] == region and r["reference"] == reference]
        predictions = leave_one_brick_out(subset, keys)
        best_predictions[name] = predictions
        results[f"lobo_{name}"] = {**confusion(predictions), "per_brick": per_brick(predictions)}

    (OUTPUT_ROOT / "comparison.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    second_rows = [r for r in json.loads(SECOND_DATASET_FEATURES.read_text(encoding="utf-8"))
                   if r["face"] == "top" and not r["tentative"]]
    plot_feature_space(rows, second_rows, transfer_prototype, OUTPUT_ROOT / "feature_space_v4.png")

    for name in ("V4_box_table", "V4_sam_table"):
        for scene in SCENE_BRICKS:
            scene_predictions = [p for p in best_predictions[name] if p["scene"] == scene]
            image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
            labels_map = (cv2.imread(str(MASK_ROOT / f"{scene}_labels.png"), cv2.IMREAD_GRAYSCALE)
                          if name.startswith("V4_sam") else None)
            cv2.imwrite(str(OUTPUT_ROOT / f"{scene}_{name}.jpg"), draw(image, scene_predictions, labels_map))

    print(f"{'evaluation':28s} acc   good ok  bad rej")
    for name, r in results.items():
        goods = r["good_accepted"] + r["good_rejected"]
        bads = r["bad_rejected"] + r["bad_accepted"]
        print(f"{name:28s} {r['accuracy']:.2f}  {r['good_accepted']:2d}/{goods}    {r['bad_rejected']:2d}/{bads}")
    for name in ("transfer_V4_box_table", "lobo_V4_box_table", "lobo_V4_sam_table"):
        print(f"\n{name}:")
        for brick, text in results[name]["per_brick"].items():
            print(f"  {brick:3s} {text}")


if __name__ == "__main__":
    main()

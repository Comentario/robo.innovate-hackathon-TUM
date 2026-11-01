"""Extract and compare color features of good and bad bricks (Second_Dataset_Bricks).

Brick regions are the corrected Grounding DINO boxes from
clean_grounding_dino_fragments.py, shrunk by a margin. The hand-written grid
below only assigns labels: each box takes the label of the grid cell that
contains its center. Perspective (FRONT) views mix several faces and are
excluded.
"""

import json
from pathlib import Path

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_ROOT = PROJECT_ROOT / "Second_Dataset_Bricks"
DETECTION_ROOT = PROJECT_ROOT / "outputs2" / "second_dataset" / "grounding_dino_clean"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "second_dataset" / "color_analysis"

BOX_MARGIN_RATIO = 0.12
WOOD_RING_PX = 60
HOLE_L_DROP = 18.0
LIME_L_RISE = 10.0
LIME_MAX_CHROMA_RATIO = 0.8
STAIN_HUE_SHIFT_DEG = 15.0
PATCH_MIN_DEV = 1.5
PATCH_SIGMAS = 3.0
TRIM_QUANTILE = 0.2

GOOD_COLOR = "#2a78d6"
BAD_COLOR = "#eb6834"
TEXT_COLOR = "#52514e"

# Grid layouts in row-major order: G = good, B = bad, None = empty cell.
# Labels for mixed scenes come from the "G" marks written on the good bricks.
SCENES = {
    "4B_GOOD_TOP": {"face": "top", "grid": [["G"], ["G"], ["G"], ["G"]]},
    "4B_GOOD_SIDE": {"face": "end", "grid": [["G"], ["G"], ["G"], ["G"]]},
    "6B_BAD_TOP_H": {"face": "top", "grid": [["B", "B"], ["B", "B"], ["B", "B"]]},
    "6B_BAD_TOP_V": {"face": "top", "grid": [["B", "B", "B"], ["B", "B", "B"]]},
    "6B_BAD_SIDE": {"face": "end", "grid": [["B"]] * 6},
    "4X2_MIXED_TPG": {
        "face": "top",
        "grid": [["G", "G"], ["G", "G"], ["B", "B"], ["B", "B"], ["B", "B"]],
    },
    "3X3_MIX_LG": {"face": "top", "grid": [["B", "B", "G"]] * 3},
    "3X3_MIX_MG": {"face": "top", "grid": [["B", "G", "B"]] * 3},
    # Blurred photo; labels inferred from the name (top and last column good).
    "10B_MIX_LG_TG": {
        "face": "top",
        "grid": [[None, "G", None], ["B", "B", "G"], ["B", "B", "G"], ["B", "B", "G"]],
        "tentative": True,
    },
}

FEATURES = {
    "L_med": "L* median",
    "a_med": "a* median",
    "b_med": "b* median",
    "C_med": "Chroma C* median",
    "h_med": "Hue angle h (deg)",
    "L_iqr": "L* IQR (texture)",
    "C_iqr": "C* IQR",
    "L_iqr_v2": "L* IQR without color patches",
    "C_iqr_v2": "C* IQR without color patches",
    "L_iqr_v3": "L* IQR, 20% most atypical removed",
    "C_iqr_v3": "C* IQR, 20% most atypical removed",
    "patch_frac": "Color-patch pixel fraction",
    "lime_frac": "Pale/lime pixel fraction",
    "dark_frac": "Dark pixel fraction",
    "stain_frac": "Yellow-shift pixel fraction",
    "dL_wood": "L* minus wood L*",
    "da_wood": "a* minus wood a*",
    "db_wood": "b* minus wood b*",
    "wb_L": "L* (wood white balance)",
    "wb_a": "a* (wood white balance)",
    "wb_b": "b* (wood white balance)",
    "wb_C": "C* (wood white balance)",
    "wb_h": "Hue (wood white balance)",
    "dL_scene": "L* minus scene brick median",
    "dC_scene": "C* minus scene brick median",
    "dh_scene": "Hue minus scene brick median",
}


def bgr_to_lab(pixels_bgr: np.ndarray) -> np.ndarray:
    """Convert uint8 BGR pixels (N, 3) to standard CIELAB."""
    image = pixels_bgr.reshape(1, -1, 3).astype(np.float32) / 255.0
    return cv2.cvtColor(image, cv2.COLOR_BGR2LAB).reshape(-1, 3)


def srgb_to_linear(values: np.ndarray) -> np.ndarray:
    values = values / 255.0
    return np.where(values <= 0.04045, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)


def linear_to_bgr8(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, 0.0, 1.0)
    srgb = np.where(values <= 0.0031308, values * 12.92, 1.055 * values ** (1 / 2.4) - 0.055)
    return np.round(srgb * 255.0).astype(np.uint8)


def load_boxes(scene: str) -> list[dict]:
    record = json.loads((DETECTION_ROOT / f"{scene}.json").read_text(encoding="utf-8"))
    return [d["bbox_px"] for d in record["detections"]]


def label_bricks(scene: str, boxes: list[dict]) -> list[dict]:
    """Give every corrected box the label of the grid cell holding its center."""
    x1 = min(b["x"] for b in boxes)
    y1 = min(b["y"] for b in boxes)
    x2 = max(b["x"] + b["width"] for b in boxes)
    y2 = max(b["y"] + b["height"] for b in boxes)
    grid = SCENES[scene]["grid"]
    rows, cols = len(grid), len(grid[0])

    bricks, used_cells = [], set()
    for box in boxes:
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        row = min(rows - 1, int((cy - y1) / (y2 - y1) * rows))
        col = min(cols - 1, int((cx - x1) / (x2 - x1) * cols))
        label = grid[row][col]
        if label is None or (row, col) in used_cells:
            raise ValueError(f"{scene}: box {box} does not map to one labeled cell")
        used_cells.add((row, col))
        bricks.append({
            "row": row, "col": col, "label": "good" if label == "G" else "bad",
            "x1": box["x"], "y1": box["y"],
            "x2": box["x"] + box["width"], "y2": box["y"] + box["height"],
        })
    return sorted(bricks, key=lambda b: (b["row"], b["col"]))


def brick_mask(brick: dict, shape: tuple[int, int]) -> np.ndarray:
    """Inner part of a corrected box, away from joints and neighbors."""
    mask = np.zeros(shape, np.uint8)
    mx = round((brick["x2"] - brick["x1"]) * BOX_MARGIN_RATIO)
    my = round((brick["y2"] - brick["y1"]) * BOX_MARGIN_RATIO)
    mask[brick["y1"] + my:brick["y2"] - my, brick["x1"] + mx:brick["x2"] - mx] = 1
    return mask


def wood_reference(image: np.ndarray, boxes: list[dict]) -> np.ndarray:
    """Median linear RGB of the table ring around the brick arrangement."""
    height, width = image.shape[:2]
    x1 = min(b["x"] for b in boxes); y1 = min(b["y"] for b in boxes)
    x2 = max(b["x"] + b["width"] for b in boxes); y2 = max(b["y"] + b["height"] for b in boxes)
    outer = np.zeros((height, width), np.uint8)
    outer[max(0, y1 - WOOD_RING_PX * 3):min(height, y2 + WOOD_RING_PX * 3),
          max(0, x1 - WOOD_RING_PX * 3):min(width, x2 + WOOD_RING_PX * 3)] = 1
    outer[max(0, y1 - WOOD_RING_PX):min(height, y2 + WOOD_RING_PX),
          max(0, x1 - WOOD_RING_PX):min(width, x2 + WOOD_RING_PX)] = 0
    pixels = image[outer.astype(bool)].astype(np.float32)
    return np.median(srgb_to_linear(pixels[:, ::-1]), axis=0)


def hue_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.degrees(np.arctan2(b, a))


def brick_features(pixels_bgr: np.ndarray, wood_rgb_lin: np.ndarray) -> dict:
    """Robust color statistics of one brick region."""
    lab = bgr_to_lab(pixels_bgr)
    L, a, b = lab[:, 0], lab[:, 1], lab[:, 2]
    C = np.hypot(a, b)
    h = hue_deg(a, b)
    L_med, C_med, h_med = np.median(L), np.median(C), np.median(h)

    # Holes and deep shadows are excluded from color statistics, but counted.
    solid = L > L_med - HOLE_L_DROP
    lime = (L > L_med + LIME_L_RISE) & (C < LIME_MAX_CHROMA_RATIO * C_med)
    stain = h > h_med + STAIN_HUE_SHIFT_DEG

    rgb_lin = srgb_to_linear(pixels_bgr[:, ::-1].astype(np.float32))
    balanced = rgb_lin / np.maximum(wood_rgb_lin, 1e-4) * 0.5
    wb_lab = bgr_to_lab(linear_to_bgr8(balanced)[:, ::-1])[solid]
    wood_lab = bgr_to_lab(linear_to_bgr8(wood_rgb_lin.reshape(1, 3))[:, ::-1])[0]

    Ls, as_, bs = L[solid], a[solid], b[solid]
    wb_a, wb_b = np.median(wb_lab[:, 1]), np.median(wb_lab[:, 2])

    # Spread without local patches. V2 drops chromatic outliers (a*/b* far from
    # the brick median) and lime; V3 drops the TRIM_QUANTILE most atypical pixels.
    da, db = as_ - np.median(as_), bs - np.median(bs)
    chroma_dev = np.hypot(da, db)
    patch_limit = max(PATCH_MIN_DEV, PATCH_SIGMAS * 1.4826 * np.median(chroma_dev))
    v2_keep = (chroma_dev <= patch_limit) & ~lime[solid]
    full_dev = np.sqrt((Ls - np.median(Ls)) ** 2 + da ** 2 + db ** 2)
    v3_keep = full_dev <= np.quantile(full_dev, 1 - TRIM_QUANTILE)
    Cs = C[solid]
    return {
        "L_med": float(np.median(Ls)),
        "a_med": float(np.median(as_)),
        "b_med": float(np.median(bs)),
        "C_med": float(np.median(C[solid])),
        "h_med": float(np.median(h[solid])),
        "L_iqr": float(np.subtract(*np.percentile(Ls, [75, 25]))),
        "C_iqr": float(np.subtract(*np.percentile(C[solid], [75, 25]))),
        "L_iqr_v2": float(np.subtract(*np.percentile(Ls[v2_keep], [75, 25]))),
        "C_iqr_v2": float(np.subtract(*np.percentile(Cs[v2_keep], [75, 25]))),
        "L_iqr_v3": float(np.subtract(*np.percentile(Ls[v3_keep], [75, 25]))),
        "C_iqr_v3": float(np.subtract(*np.percentile(Cs[v3_keep], [75, 25]))),
        "patch_frac": float(1 - v2_keep.mean()),
        "lime_frac": float(lime.mean()),
        "dark_frac": float((~solid).mean()),
        "stain_frac": float((stain & solid).mean()),
        "dL_wood": float(np.median(Ls) - wood_lab[0]),
        "da_wood": float(np.median(as_) - wood_lab[1]),
        "db_wood": float(np.median(bs) - wood_lab[2]),
        "wb_L": float(np.median(wb_lab[:, 0])),
        "wb_a": float(wb_a),
        "wb_b": float(wb_b),
        "wb_C": float(np.hypot(wb_a, wb_b)),
        "wb_h": float(hue_deg(wb_a, wb_b)),
    }


def auc(good: np.ndarray, bad: np.ndarray) -> float:
    """Probability that a random good value exceeds a random bad value."""
    wins = (good[:, None] > bad[None, :]).sum() + 0.5 * (good[:, None] == bad[None, :]).sum()
    return float(wins / (len(good) * len(bad)))


PROTOTYPE_FEATURE_SETS = {
    "L_raw": ["L_med"],
    "L_wood": ["dL_wood"],
    "L_scene": ["dL_scene"],
    "L_wood+texture": ["dL_wood", "L_iqr", "C_iqr"],
    "wb_L_C+texture": ["wb_L", "wb_C", "L_iqr", "C_iqr"],
    "L_wood+C+texture": ["dL_wood", "C_med", "L_iqr", "C_iqr"],
}
GOOD_ACCEPT_QUANTILE = 0.9
ACCEPT_MARGIN = 1.0


def evaluate_prototypes(rows: list[dict]) -> list[dict]:
    """One-class 'distance to the good prototype', leave-one-scene-out.

    Good bricks of the other scenes give a per-feature center and spread; a
    brick is accepted when its standardized distance is within the largest
    training good distance (times a margin). The same physical bricks appear
    in several scenes, so this is optimistic compared with leave-one-brick-out.
    """
    results = []
    scenes = sorted({r["scene"] for r in rows})
    for name, keys in PROTOTYPE_FEATURE_SETS.items():
        confusion = {"good_ok": 0, "good_rejected": 0, "bad_rejected": 0, "bad_accepted": 0}
        distances, labels = [], []
        for held_out in scenes:
            train = [r for r in rows if r["scene"] != held_out and r["label"] == "good"]
            test = [r for r in rows if r["scene"] == held_out]
            X = np.array([[r[k] for k in keys] for r in train])
            center, spread = X.mean(axis=0), X.std(axis=0) + 1e-6
            train_distance = np.linalg.norm((X - center) / spread, axis=1)
            limit = np.quantile(train_distance, GOOD_ACCEPT_QUANTILE) * ACCEPT_MARGIN
            for row in test:
                distance = float(np.linalg.norm((np.array([row[k] for k in keys]) - center) / spread))
                accepted = distance <= limit
                distances.append(distance)
                labels.append(row["label"])
                if row["label"] == "good":
                    confusion["good_ok" if accepted else "good_rejected"] += 1
                else:
                    confusion["bad_accepted" if accepted else "bad_rejected"] += 1
        d = np.array(distances); is_bad = np.array(labels) == "bad"
        total = sum(confusion.values())
        results.append({
            "feature_set": name, "features": keys,
            "accuracy": round((confusion["good_ok"] + confusion["bad_rejected"]) / total, 3),
            "auc_distance": round(auc(d[is_bad], d[~is_bad]), 3),
            **confusion,
        })
    return results


def draw_layout(image: np.ndarray, boxes: list[dict], bricks: list[dict]) -> np.ndarray:
    canvas = image.copy()
    for box in boxes:
        cv2.rectangle(canvas, (box["x"], box["y"]),
                      (box["x"] + box["width"], box["y"] + box["height"]), (200, 200, 200), 1)
    for brick in bricks:
        color = (214, 120, 42) if brick["label"] == "good" else (52, 104, 235)
        overlay = canvas.copy()
        overlay[brick["mask"].astype(bool)] = color
        canvas = cv2.addWeighted(overlay, 0.25, canvas, 0.75, 0)
        cv2.rectangle(canvas, (brick["x1"], brick["y1"]), (brick["x2"], brick["y2"]), color, 3)
        cv2.putText(canvas, f"{brick['brick_id']} {brick['label']}",
                    (brick["x1"] + 10, brick["y1"] + 40), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, color, 3, cv2.LINE_AA)
    return canvas


def style_axis(axis) -> None:
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#b5b4ad")
    axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axis.grid(color="#e8e7e2", linewidth=0.6)
    axis.set_axisbelow(True)


def scatter_by_label(axis, rows: list[dict], x_key: str, y_key: str) -> None:
    for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
        subset = [r for r in rows if r["label"] == label]
        axis.scatter([r[x_key] for r in subset], [r[y_key] for r in subset], s=46,
                     c=color, marker=marker, edgecolors="white", linewidths=1.2,
                     label=label, zorder=3)
    axis.set_xlabel(FEATURES.get(x_key, x_key), color=TEXT_COLOR, fontsize=9)
    axis.set_ylabel(FEATURES.get(y_key, y_key), color=TEXT_COLOR, fontsize=9)
    style_axis(axis)


def plot_scatter_panels(rows: list[dict], path: Path) -> None:
    pairs = [("L_med", "C_med"), ("L_med", "h_med"), ("a_med", "b_med"),
             ("wb_L", "wb_C"), ("wb_L", "wb_h"), ("L_iqr", "lime_frac")]
    figure, axes = plt.subplots(2, 3, figsize=(15, 9))
    for axis, (x_key, y_key) in zip(axes.ravel(), pairs):
        scatter_by_label(axis, rows, x_key, y_key)
    axes[0, 0].legend(frameon=False, fontsize=9)
    figure.suptitle("Top-face bricks, all scenes (circle = good, triangle = bad)",
                    color="#0b0b0b", fontsize=12)
    figure.tight_layout()
    figure.savefig(path, dpi=130, facecolor="#fcfcfb")
    plt.close(figure)


def plot_per_scene(rows: list[dict], x_key: str, y_key: str, path: Path) -> None:
    scenes = sorted({r["scene"] for r in rows})
    cols = 3
    figure, axes = plt.subplots(-(-len(scenes) // cols), cols, figsize=(15, 4 * -(-len(scenes) // cols)),
                                squeeze=False)
    for axis in axes.ravel():
        axis.axis("off")
    for axis, scene in zip(axes.ravel(), scenes):
        axis.axis("on")
        scatter_by_label(axis, [r for r in rows if r["scene"] == scene], x_key, y_key)
        axis.set_title(scene, color="#0b0b0b", fontsize=10)
    axes[0, 0].legend(frameon=False, fontsize=9)
    figure.tight_layout()
    figure.savefig(path, dpi=130, facecolor="#fcfcfb")
    plt.close(figure)


def plot_auc(ranking: list[dict], path: Path) -> None:
    figure, axis = plt.subplots(figsize=(9, 7))
    names = [FEATURES[r["feature"]] for r in ranking][::-1]
    values = [r["separability"] for r in ranking][::-1]
    axis.barh(names, values, color=GOOD_COLOR, height=0.6)
    for y, value in enumerate(values):
        axis.text(value + 0.005, y, f"{value:.2f}", va="center", fontsize=8, color=TEXT_COLOR)
    axis.axvline(0.5, color="#b5b4ad", linewidth=1)
    axis.set_xlim(0.5, 1.02)
    axis.set_xlabel("Separability = max(AUC, 1 - AUC); 0.5 = none, 1.0 = perfect",
                    color=TEXT_COLOR, fontsize=9)
    axis.set_title("Single-feature separability, top-face bricks", color="#0b0b0b", fontsize=11)
    style_axis(axis)
    figure.tight_layout()
    figure.savefig(path, dpi=130, facecolor="#fcfcfb")
    plt.close(figure)


def save_montage(crops: list[tuple[str, np.ndarray]], path: Path, tile=(260, 120)) -> None:
    """Grid of brick crops, good row first, for visual inspection."""
    rows = []
    for label in ("good", "bad"):
        tiles = [cv2.resize(c, tile) for l, c in crops if l == label]
        for start in range(0, len(tiles), 8):
            chunk = tiles[start:start + 8]
            chunk += [np.full((tile[1], tile[0], 3), 252, np.uint8)] * (8 - len(chunk))
            rows.append(np.hstack(chunk))
        rows.append(np.full((12, tile[0] * 8, 3), 252, np.uint8))
    cv2.imwrite(str(path), np.vstack(rows))


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows, crops = [], []
    for scene, config in SCENES.items():
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        boxes = load_boxes(scene)
        wood = wood_reference(image, boxes)

        bricks = []
        for number, cell in enumerate(label_bricks(scene, boxes), 1):
            mask = brick_mask(cell, image.shape[:2])
            features = brick_features(image[mask.astype(bool)], wood)
            bricks.append({**cell, "brick_id": f"{scene}#{number:02d}", "mask": mask, **features})
            crop = image[cell["y1"]:cell["y2"], cell["x1"]:cell["x2"]]
            if crop.shape[0] > crop.shape[1]:
                crop = cv2.rotate(crop, cv2.ROTATE_90_CLOCKWISE)
            if config["face"] == "top":
                crops.append((cell["label"], crop))

        scene_L = np.median([b["L_med"] for b in bricks])
        scene_C = np.median([b["C_med"] for b in bricks])
        scene_h = np.median([b["h_med"] for b in bricks])
        for brick in bricks:
            brick["dL_scene"] = brick["L_med"] - scene_L
            brick["dC_scene"] = brick["C_med"] - scene_C
            brick["dh_scene"] = brick["h_med"] - scene_h

        cv2.imwrite(str(OUTPUT_ROOT / f"{scene}_layout.jpg"), draw_layout(image, boxes, bricks))
        for brick in bricks:
            brick.pop("mask")
            rows.append({"scene": scene, "face": config["face"],
                         "tentative": config.get("tentative", False), **brick})

    (OUTPUT_ROOT / "brick_features.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    top = [r for r in rows if r["face"] == "top" and not r["tentative"]]
    ranking = []
    for feature in FEATURES:
        good = np.array([r[feature] for r in top if r["label"] == "good"])
        bad = np.array([r[feature] for r in top if r["label"] == "bad"])
        value = auc(good, bad)
        ranking.append({
            "feature": feature, "auc_good_higher": round(value, 3),
            "separability": round(max(value, 1 - value), 3),
            "good_median": round(float(np.median(good)), 2),
            "bad_median": round(float(np.median(bad)), 2),
            "good_range": [round(float(good.min()), 2), round(float(good.max()), 2)],
            "bad_range": [round(float(bad.min()), 2), round(float(bad.max()), 2)],
        })
    ranking.sort(key=lambda r: -r["separability"])
    (OUTPUT_ROOT / "feature_ranking.json").write_text(json.dumps(ranking, indent=2), encoding="utf-8")

    # Mixed scenes share one illumination: rank features inside each scene.
    within = {}
    for scene in ("4X2_MIXED_TPG", "3X3_MIX_LG", "3X3_MIX_MG"):
        subset = [r for r in rows if r["scene"] == scene]
        within[scene] = {
            feature: round(max(v := auc(
                np.array([r[feature] for r in subset if r["label"] == "good"]),
                np.array([r[feature] for r in subset if r["label"] == "bad"])), 1 - v), 3)
            for feature in FEATURES
        }
    (OUTPUT_ROOT / "within_scene_separability.json").write_text(
        json.dumps(within, indent=2), encoding="utf-8")

    plot_scatter_panels(top, OUTPUT_ROOT / "scatter_top_faces.png")
    plot_per_scene([r for r in rows if r["face"] == "top"], "L_med", "C_med",
                   OUTPUT_ROOT / "scatter_per_scene_L_C.png")
    plot_per_scene(rows, "wb_L", "wb_h", OUTPUT_ROOT / "scatter_per_scene_wbL_wbh.png")
    plot_auc(ranking, OUTPUT_ROOT / "feature_separability.png")
    save_montage(crops, OUTPUT_ROOT / "montage_top_faces.jpg")

    print(f"{len(rows)} brick regions ({len(top)} top-face, non-tentative)")
    print(f"{'feature':12s} {'sep':>5s} {'good med':>9s} {'bad med':>8s}  good range / bad range")
    for item in ranking:
        print(f"{item['feature']:12s} {item['separability']:5.2f} {item['good_median']:9.2f} "
              f"{item['bad_median']:8.2f}  {item['good_range']} / {item['bad_range']}")
    prototypes = evaluate_prototypes(top)
    (OUTPUT_ROOT / "prototype_evaluation.json").write_text(
        json.dumps(prototypes, indent=2), encoding="utf-8")
    print("\ngood-prototype distance, leave-one-scene-out (top faces):")
    for item in prototypes:
        print(f"  {item['feature_set']:18s} acc={item['accuracy']:.2f} auc={item['auc_distance']:.2f} "
              f"good ok/rej={item['good_ok']}/{item['good_rejected']} "
              f"bad rej/acc={item['bad_rejected']}/{item['bad_accepted']}")

    print("\nwithin-scene separability (top 5 per mixed scene):")
    for scene, values in within.items():
        best = sorted(values.items(), key=lambda kv: -kv[1])[:5]
        print(f"  {scene}: " + ", ".join(f"{k}={v:.2f}" for k, v in best))


if __name__ == "__main__":
    main()

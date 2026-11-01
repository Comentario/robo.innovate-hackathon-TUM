"""Classify bricks with a single good-brick prototype (prototype A).

Each brick is described by its lightness relative to the wood table and its
chroma (variant V4; the spread variants are kept for comparison in VARIANTS).
The prototype is the mean and spread
of the good bricks; a brick is accepted as good when its standardized distance
to that mean is within the GOOD_ACCEPT_QUANTILE of the training good distances.

Evaluation is leave-one-scene-out on top faces. The same physical bricks appear
in several scenes, so the result is optimistic compared with leaving whole
bricks out. A final prototype fitted on every labeled top face is also saved.
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
FEATURES_PATH = PROJECT_ROOT / "outputs2" / "second_dataset" / "color_analysis" / "brick_features.json"
OUTPUT_ROOT = PROJECT_ROOT / "outputs2" / "second_dataset" / "prototype_a"

# V4 (lightness relative to the wood + chroma) won the variant comparison.
FEATURE_KEYS = ["dL_wood", "C_med"]
FEATURE_NAMES = {
    "dL_wood": "L* minus wood",
    "C_med": "chroma",
    "L_iqr": "L* spread",
    "C_iqr": "chroma spread",
    "L_iqr_v2": "L* spread w/o patches",
    "C_iqr_v2": "chroma spread w/o patches",
    "L_iqr_v3": "L* spread trimmed",
    "C_iqr_v3": "chroma spread trimmed",
}
# Spread variants compared with the same leave-one-scene-out protocol.
VARIANTS = {
    "V0_current": ["dL_wood", "C_med", "L_iqr", "C_iqr"],
    "V1_no_chroma_spread": ["dL_wood", "C_med", "L_iqr"],
    "V2_spread_without_patches": ["dL_wood", "C_med", "L_iqr_v2", "C_iqr_v2"],
    "V3_spread_trimmed_20pct": ["dL_wood", "C_med", "L_iqr_v3", "C_iqr_v3"],
    "V4_color_only": ["dL_wood", "C_med"],
}
GOOD_ACCEPT_QUANTILE = 0.9

GOOD_COLOR = "#2a78d6"
BAD_COLOR = "#eb6834"
TEXT_COLOR = "#52514e"
CORRECT_BGR = (12, 163, 12)
ERROR_BGR = (59, 59, 208)


def fit_prototype(goods: list[dict], keys: list[str] = FEATURE_KEYS) -> dict:
    """Mean, spread and acceptance radius of the good bricks."""
    X = np.array([[r[k] for k in keys] for r in goods])
    center, spread = X.mean(axis=0), X.std(axis=0) + 1e-6
    distances = np.linalg.norm((X - center) / spread, axis=1)
    return {
        "features": keys,
        "center": center.tolist(),
        "spread": spread.tolist(),
        "threshold": float(np.quantile(distances, GOOD_ACCEPT_QUANTILE)),
        "good_count": len(goods),
    }


def score(row: dict, prototype: dict) -> dict:
    """Distance to the prototype and the per-feature standardized offsets."""
    x = np.array([row[k] for k in prototype["features"]])
    z = (x - np.array(prototype["center"])) / np.array(prototype["spread"])
    distance = float(np.linalg.norm(z))
    return {
        "distance": round(distance, 3),
        "threshold": round(prototype["threshold"], 3),
        "ratio": round(distance / prototype["threshold"], 3),
        "predicted": "good" if distance <= prototype["threshold"] else "bad",
        "z_scores": {k: round(float(v), 2) for k, v in zip(prototype["features"], z)},
        "main_reason": prototype["features"][int(np.argmax(np.abs(z)))],
    }


def confusion(rows: list[dict]) -> dict:
    counts = {"good_accepted": 0, "good_rejected": 0, "bad_rejected": 0, "bad_accepted": 0}
    for r in rows:
        if r["label"] == "good":
            counts["good_accepted" if r["predicted"] == "good" else "good_rejected"] += 1
        else:
            counts["bad_rejected" if r["predicted"] == "bad" else "bad_accepted"] += 1
    total = sum(counts.values())
    goods = counts["good_accepted"] + counts["good_rejected"]
    bads = counts["bad_rejected"] + counts["bad_accepted"]
    return {
        **counts,
        "total": total,
        "accuracy": round((counts["good_accepted"] + counts["bad_rejected"]) / total, 3) if total else None,
        "good_recall": round(counts["good_accepted"] / goods, 3) if goods else None,
        "bad_recall": round(counts["bad_rejected"] / bads, 3) if bads else None,
    }


def leave_one_scene_out(top: list[dict], keys: list[str]) -> list[dict]:
    predictions = []
    for held_out in sorted({r["scene"] for r in top}):
        prototype = fit_prototype(
            [r for r in top if r["scene"] != held_out and r["label"] == "good"], keys)
        for r in (r for r in top if r["scene"] == held_out):
            predictions.append({**r, "evaluation": "leave_one_scene_out", **score(r, prototype)})
    return predictions


def compare_variants(top: list[dict]) -> list[dict]:
    """Same protocol for every spread variant; AUC ranks bad above good distances."""
    results = []
    for name, keys in VARIANTS.items():
        predictions = leave_one_scene_out(top, keys)
        ratios = np.array([p["ratio"] for p in predictions])
        is_bad = np.array([p["label"] == "bad" for p in predictions])
        wins = (ratios[is_bad][:, None] > ratios[~is_bad][None, :]).mean()
        results.append({
            "variant": name, "features": keys, **confusion(predictions),
            "auc": round(float(wins), 3),
            "errors": [p["brick_id"] for p in predictions if p["predicted"] != p["label"]],
        })
    return results


def draw_predictions(image: np.ndarray, rows: list[dict]) -> np.ndarray:
    """Outline each brick green (correct) or red (error) with its prediction."""
    canvas = image.copy()
    for r in rows:
        correct = r["predicted"] == r["label"]
        color = CORRECT_BGR if correct else ERROR_BGR
        cv2.rectangle(canvas, (r["x1"], r["y1"]), (r["x2"], r["y2"]), color, 6 if correct else 9)
        lines = [
            f"{'OK' if correct else 'ERROR'}  pred {r['predicted']} / true {r['label']}",
            f"d={r['distance']:.2f} thr={r['threshold']:.2f}",
        ]
        if r["predicted"] == "bad":
            lines.append(f"reason: {FEATURE_NAMES[r['main_reason']]} "
                         f"(z={r['z_scores'][r['main_reason']]:+.1f})")
        for i, text in enumerate(lines):
            y = r["y1"] + 40 + i * 34
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
            cv2.rectangle(canvas, (r["x1"] + 8, y - h - 6), (r["x1"] + 16 + w, y + 6), (255, 255, 255), -1)
            cv2.putText(canvas, text, (r["x1"] + 12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2, cv2.LINE_AA)
    return canvas


def plot_distances(rows: list[dict], path: Path) -> None:
    """Distance / threshold per brick, one row per scene; 1.0 is the boundary."""
    scenes = sorted({r["scene"] for r in rows})
    figure, axis = plt.subplots(figsize=(11, 0.7 * len(scenes) + 1.8))
    rng = np.random.default_rng(0)
    for label, color, marker in (("good", GOOD_COLOR, "o"), ("bad", BAD_COLOR, "^")):
        subset = [r for r in rows if r["label"] == label]
        y = [scenes.index(r["scene"]) + rng.uniform(-0.18, 0.18) for r in subset]
        axis.scatter([r["ratio"] for r in subset], y, s=60, c=color, marker=marker,
                     edgecolors="white", linewidths=1.2, label=f"true {label}", zorder=3)
    axis.axvline(1.0, color="#0b0b0b", linewidth=1.2)
    axis.text(1.03, -0.45, "threshold (left = accepted as good)",
              fontsize=8, color=TEXT_COLOR, va="center")
    axis.set_yticks(range(len(scenes)), scenes)
    axis.set_xlabel("Distance to good prototype / acceptance threshold", color=TEXT_COLOR, fontsize=9)
    axis.set_title("Prototype A, leave-one-scene-out (top faces)", color="#0b0b0b", fontsize=11)
    axis.spines[["top", "right"]].set_visible(False)
    axis.spines[["left", "bottom"]].set_color("#b5b4ad")
    axis.tick_params(colors=TEXT_COLOR, labelsize=8)
    axis.grid(axis="x", color="#e8e7e2", linewidth=0.6)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, fontsize=9, loc="lower right")
    figure.tight_layout()
    figure.savefig(path, dpi=130, facecolor="#fcfcfb")
    plt.close(figure)


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = json.loads(FEATURES_PATH.read_text(encoding="utf-8"))
    top = [r for r in rows if r["face"] == "top" and not r["tentative"]]
    tentative = [r for r in rows if r["face"] == "top" and r["tentative"]]

    variants = compare_variants(top)
    (OUTPUT_ROOT / "variant_comparison.json").write_text(json.dumps(variants, indent=2), encoding="utf-8")
    print(f"{'variant':28s} acc   auc   good ok  bad rej")
    for v in variants:
        print(f"{v['variant']:28s} {v['accuracy']:.2f}  {v['auc']:.2f}  "
              f"{v['good_accepted']:2d}/{v['good_accepted'] + v['good_rejected']}    "
              f"{v['bad_rejected']:2d}/{v['bad_rejected'] + v['bad_accepted']}")
    print()

    predictions = leave_one_scene_out(top, FEATURE_KEYS)
    final_prototype = fit_prototype([r for r in top if r["label"] == "good"])
    for r in tentative:
        predictions.append({**r, "evaluation": "final_prototype_tentative_labels", **score(r, final_prototype)})

    evaluated = [p for p in predictions if p["evaluation"] == "leave_one_scene_out"]
    metrics = {
        "leave_one_scene_out": confusion(evaluated),
        "per_scene": {s: confusion([p for p in evaluated if p["scene"] == s])
                      for s in sorted({p["scene"] for p in evaluated})},
        "tentative_10B": confusion([p for p in predictions if p["tentative"]]),
    }

    (OUTPUT_ROOT / "prototype.json").write_text(json.dumps(final_prototype, indent=2), encoding="utf-8")
    (OUTPUT_ROOT / "predictions.json").write_text(json.dumps(predictions, indent=2), encoding="utf-8")
    (OUTPUT_ROOT / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    plot_distances(evaluated, OUTPUT_ROOT / "distance_to_prototype.png")
    for scene in sorted({p["scene"] for p in predictions}):
        image = cv2.imread(str(IMAGE_ROOT / f"{scene}.jpg"))
        cv2.imwrite(str(OUTPUT_ROOT / f"{scene}_prediction.jpg"),
                    draw_predictions(image, [p for p in predictions if p["scene"] == scene]))

    m = metrics["leave_one_scene_out"]
    print(f"leave-one-scene-out: acc={m['accuracy']} good recall={m['good_recall']} "
          f"bad recall={m['bad_recall']}  ({m})")
    for scene, c in metrics["per_scene"].items():
        print(f"  {scene:16s} acc={c['accuracy']} good {c['good_accepted']}/{c['good_accepted'] + c['good_rejected']} "
              f"bad {c['bad_rejected']}/{c['bad_rejected'] + c['bad_accepted']}")
    t = metrics["tentative_10B"]
    print(f"10B (tentative labels, final prototype): acc={t['accuracy']} {t}")
    print("\nerrors:")
    for p in evaluated:
        if p["predicted"] != p["label"]:
            print(f"  {p['brick_id']:18s} true={p['label']:4s} d/thr={p['ratio']:.2f} z={p['z_scores']}")


if __name__ == "__main__":
    main()

"""Classify a brick from both of its solid faces instead of one capture.

Uses an ordered calibration (4 captures per brick: face A twice, face B twice,
brick by brick; see the capture plan). Each face is the mean of its captures;
contaminated captures (stains >= 12%) are left out.

Rules compared, all evaluated leave-one-BRICK-out (fit on 9 bricks, test the
10th), so the score estimates a brick never seen:
  one face, band            each face classified alone (baseline)
  both faces in band (AND)  good only if both faces are inside the band
  band on brick mean        band on the mean L* of the two faces
  band on darker / lighter face   band on the min / max face L*
  1-NN on (min, max) face L*      nearest training brick in that 2-D space

Usage: evaluate_two_face_rules.py <calibration folder> [--extra cal037=9]
  --extra assigns captures that break the 4-per-brick order to a brick.
"""

import argparse
import json
from pathlib import Path

import numpy as np

STAIN_LIMIT = 0.12
KEY = "L_mode"


def fit_band(values: list[float], labels: list[str]) -> tuple[float, float]:
    """Interval with the best balanced accuracy (good inside, bad outside)."""
    candidates = sorted(set(values))
    good = [v for v, l in zip(values, labels) if l == "good"]
    bad = [v for v, l in zip(values, labels) if l == "bad"]
    best, band = -1.0, (candidates[0], candidates[-1])
    for i, low in enumerate(candidates):
        for high in candidates[i:]:
            score = (np.mean([low <= v <= high for v in good]) if good else 0) / 2 + \
                    (np.mean([not low <= v <= high for v in bad]) if bad else 0) / 2
            if score > best:
                best, band = score, (low, high)
    return band


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("--extra", nargs="*", default=[], help="capture=brick overrides, e.g. cal037=9")
    args = parser.parse_args()

    rows = json.loads((args.calibration / "calibration.json").read_text(encoding="utf-8"))["rows"]
    overrides = {k: int(v) for k, v in (item.split("=") for item in args.extra)}

    # Assign brick and face from the capture order; overrides do not shift the count.
    ordered = sorted({r["photo"] for r in rows})
    regular = [p for p in ordered if p not in overrides]
    position = {p: i for i, p in enumerate(regular)}
    faces: dict[tuple[int, str], list[float]] = {}
    labels: dict[int, str] = {}
    for r in rows:
        if r.get("stain_share", 0.0) >= STAIN_LIMIT:
            continue
        if r["photo"] in overrides:
            brick, face = overrides[r["photo"]], "B"
        else:
            i = position[r["photo"]]
            brick, face = i // 4 + 1, "A" if i % 4 < 2 else "B"
        faces.setdefault((brick, face), []).append(r[KEY])
        labels[brick] = r["label"]

    bricks = sorted(labels)
    face_value = {k: float(np.mean(v)) for k, v in faces.items()}
    per_brick = {b: [face_value[(b, f)] for f in "AB" if (b, f) in face_value] for b in bricks}

    print("brick  label  face A   face B")
    for b in bricks:
        a, bb = face_value.get((b, "A")), face_value.get((b, "B"))
        print(f"  {b:2d}   {labels[b]:4s}  {a if a is not None else '-':>6}   {bb if bb is not None else '-':>6}")

    results = {}

    def evaluate(name, decide):
        correct = [decide([x for x in bricks if x != b], b) == labels[b] for b in bricks]
        results[name] = correct
        wrong = [b for b, ok in zip(bricks, correct) if not ok]
        print(f"{name:34s} {sum(correct)}/{len(correct)} bricks ({np.mean(correct):.0%})   wrong: {wrong}")

    # Baseline: every face classified alone, scored per face.
    face_correct = []
    for b in bricks:
        train = [x for x in bricks if x != b]
        low, high = fit_band([v for x in train for v in per_brick[x]], [labels[x] for x in train for _ in per_brick[x]])
        face_correct += [(low <= v <= high) == (labels[b] == "good") for v in per_brick[b]]
    print(f"\n{'one face, band (per face)':34s} {sum(face_correct)}/{len(face_correct)} faces ({np.mean(face_correct):.0%})")

    def and_rule(train, b):
        low, high = fit_band([v for x in train for v in per_brick[x]], [labels[x] for x in train for _ in per_brick[x]])
        return "good" if all(low <= v <= high for v in per_brick[b]) else "bad"

    def band_on(stat):
        def decide(train, b):
            low, high = fit_band([stat(per_brick[x]) for x in train], [labels[x] for x in train])
            return "good" if low <= stat(per_brick[b]) <= high else "bad"
        return decide

    def knn_min_max(train, b):
        X = np.array([[min(per_brick[x]), max(per_brick[x])] for x in train])
        center, spread = X.mean(axis=0), X.std(axis=0) + 1e-6
        z = (np.array([min(per_brick[b]), max(per_brick[b])]) - center) / spread
        return labels[train[int(np.argmin(np.linalg.norm((X - center) / spread - z, axis=1)))]]

    evaluate("both faces in band (AND)", and_rule)
    evaluate("band on brick mean", band_on(lambda v: float(np.mean(v))))
    evaluate("band on darker face (min)", band_on(min))
    evaluate("band on lighter face (max)", band_on(max))
    evaluate("band on face difference", band_on(lambda v: max(v) - min(v)))
    evaluate("1-NN on (min, max) face L*", knn_min_max)


if __name__ == "__main__":
    main()

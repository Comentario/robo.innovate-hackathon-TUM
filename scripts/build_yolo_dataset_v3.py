"""YOLO segmentation dataset v3: previous datasets + one-brick photos on wood and carpet.

  standing  outputs2/yolo_dataset       (front view, train / val as before)
  top       outputs2/yolo_dataset_top   (top view on dark carpet, train / val as before)
  wood, carpet  Brick_Faces_Dataset/brick_faces_* with masks from label_brick_faces.py;
            bricks B09 and B10 of each package go to val, the rest to train
  background  empty-table photos (Brick_Faces_Dataset/*/background), train, no label:
            they teach the detector that bare wood is not a brick

Everything is copied into one folder with a data.yaml without absolute paths, so the
folder can be zipped and trained on another machine (train_brick_detector.py --data).
Output: outputs2/yolo_dataset_v3/
Usage: build_yolo_dataset_v3.py
"""

import json
import shutil
import sys
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

OUTPUTS = PROJECT_ROOT / "outputs2"
FACES_DATASET = PROJECT_ROOT / "Brick_Faces_Dataset"
FACES_LABELS = OUTPUTS / "brick_faces_labels"
OUTPUT = OUTPUTS / "yolo_dataset_v3"
VAL_BRICKS = {"B09", "B10"}


def add(image: Path, label_lines: list[str], split: str, name: str, counts: dict) -> None:
    shutil.copy2(image, OUTPUT / "images" / split / f"{name}{image.suffix}")
    (OUTPUT / "labels" / split / f"{name}.txt").write_text("\n".join(label_lines) + ("\n" if label_lines else ""),
                                                          encoding="utf-8")
    counts[split] = counts.get(split, 0) + 1


def main() -> None:
    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    for kind in ("images", "labels"):
        for split in ("train", "val"):
            (OUTPUT / kind / split).mkdir(parents=True)
    summary = {}

    for source, folder in (("standing", OUTPUTS / "yolo_dataset"), ("top", OUTPUTS / "yolo_dataset_top")):
        counts = summary.setdefault(source, {})
        for split in ("train", "val"):
            for image in sorted((folder / "images" / split).iterdir()):
                label = folder / "labels" / split / f"{image.stem}.txt"
                lines = label.read_text(encoding="utf-8").split("\n") if label.exists() else []
                add(image, [l for l in lines if l.strip()], split, f"{source}_{image.stem}", counts)

    for package in sorted(p for p in FACES_DATASET.glob("brick_faces_*") if p.is_dir()):
        source = package.name.split("_")[2]
        counts = summary.setdefault(source, {})
        for r in json.loads((FACES_LABELS / package.name / "labels.json").read_text(encoding="utf-8")):
            if r["status"] != "ok":
                continue
            image = package / r["file"]
            h, w = cv2.imread(str(image)).shape[:2]
            polygon = " ".join(f"{x / w:.5f} {y / h:.5f}" for x, y in r["polygon"])
            split = "val" if r["brick_id"] in VAL_BRICKS else "train"
            add(image, [f"0 {polygon}"], split, f"{source}_{image.stem}", counts)

    counts = summary.setdefault("background", {})
    for image in sorted(FACES_DATASET.glob("*/background/*.jpg")):
        add(image, [], "train", f"background_{image.parent.parent.name}_{image.stem}", counts)

    (OUTPUT / "data.yaml").write_text("# paths are relative to this file's folder\n"
                                      "train: images/train\nval: images/val\nnames:\n  0: brick\n", encoding="utf-8")
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for source, counts in summary.items():
        print(f"{source:10s} train {counts.get('train', 0):4d}  val {counts.get('val', 0):3d}")
    print(f"output: {OUTPUT}")


if __name__ == "__main__":
    main()

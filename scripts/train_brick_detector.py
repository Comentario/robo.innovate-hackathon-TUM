"""Train the small brick detector (YOLO11n-seg) on outputs2/yolo_dataset.

The dataset comes from build_yolo_dataset.py (one class: brick, labels made by
the Grounding DINO + MobileSAM pipeline and reviewed). Training runs on the GPU
when available; batch 8 fits a 4 GB laptop GPU at 640 px.

Results go to outputs2/yolo_runs/<name>/ (weights/best.pt, curves, val images).

Usage: train_brick_detector.py [--epochs 100] [--name brick_seg] [--batch 8] [--data dataset.yaml]
"""

import argparse
from pathlib import Path

from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA = PROJECT_ROOT / "outputs2" / "yolo_dataset" / "data.yaml"
RUNS = PROJECT_ROOT / "outputs2" / "yolo_runs"
BASE_WEIGHTS = PROJECT_ROOT / "models" / "yolo11n-seg.pt"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--name", default="brick_seg")
    parser.add_argument("--data", type=Path, default=DATA,
                        help="dataset yaml, e.g. outputs2/yolo_dataset_combined.yaml (standing + top view)")
    args = parser.parse_args()

    model = YOLO(str(BASE_WEIGHTS))
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=30,
        # Windows: dataloader workers in subprocesses are fragile and slow to start.
        workers=0,
        project=str(RUNS),
        name=args.name,
        exist_ok=True,
        seed=0,
        plots=True,
    )
    metrics = model.val(data=str(args.data), split="val", project=str(RUNS), name=f"{args.name}_val", exist_ok=True)
    print(f"box mAP50 {metrics.box.map50:.3f}  mAP50-95 {metrics.box.map:.3f}")
    print(f"mask mAP50 {metrics.seg.map50:.3f}  mAP50-95 {metrics.seg.map:.3f}")
    print(f"weights: {RUNS / args.name / 'weights' / 'best.pt'}")


if __name__ == "__main__":
    main()

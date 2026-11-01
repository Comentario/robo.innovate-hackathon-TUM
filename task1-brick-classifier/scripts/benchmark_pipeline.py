"""Time each pipeline step on this machine (CPU or GPU) with saved photos.

Steps: Grounding DINO detection, row split, MobileSAM segmentation, color
features. Each photo is processed WARMUP times without timing, then RUNS times;
the median per step and the implied frames per second are reported.

Usage: benchmark_pipeline.py [photo ...] [--runs N] [--cpu]
Without photos, a few Third_Dataset_Bricks and live captures are used.
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

WARMUP = 2
DEFAULT_PHOTOS = [
    PROJECT_ROOT / "Third_Dataset_Bricks" / "MIX_07.jpg",
    PROJECT_ROOT / "Third_Dataset_Bricks" / "GOOD_03.jpg",
    PROJECT_ROOT / "outputs2" / "live" / "20261024_203017" / "frames" / "0006.jpg",
]


def timed(function, *args):
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    start = time.perf_counter()
    result = function(*args)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    return result, time.perf_counter() - start


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("photos", nargs="*", type=Path)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--cpu", action="store_true", help="hide the GPU to measure the CPU")
    args = parser.parse_args()
    if args.cpu:
        torch.cuda.is_available = lambda: False

    from scripts.live_brick_classifier import BrickClassifier
    from scripts.run_mobile_sam import segment, to_corners
    from scripts.split_brick_row import split_scene

    device = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    # Grounding DINO uses the GPU through BrickClassifier; ultralytics picks it by itself.
    classifier = BrickClassifier()
    print(f"device: {device}  (torch {torch.__version__})")

    times = {"detection": [], "split": [], "segmentation": [], "color": [], "total classify": []}
    for path in args.photos or DEFAULT_PHOTOS:
        frame = cv2.imread(str(path))
        for run in range(WARMUP + args.runs):
            raw, t_det = timed(classifier.detect_boxes, frame)
            split, t_split = timed(split_scene, frame, raw)
            boxes = [d["bbox_px"] for d in split["detections"]]
            _, t_seg = timed(segment, classifier.segmenter, frame, [to_corners(b) for b in boxes])
            _, t_all = timed(classifier.classify, frame)
            if run >= WARMUP:
                times["detection"].append(t_det)
                times["split"].append(t_split)
                times["segmentation"].append(t_seg)
                times["total classify"].append(t_all)
                times["color"].append(max(0.0, t_all - t_det - t_split - t_seg))
        print(f"  {path.name}: {len(boxes)} bricks")

    print(f"\nmedian over {len(times['detection'])} runs:")
    for step, values in times.items():
        median = statistics.median(values)
        print(f"  {step:15s} {median * 1000:8.0f} ms   (~{1 / median:5.1f} per second)")


if __name__ == "__main__":
    main()

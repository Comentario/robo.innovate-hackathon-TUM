"""Collect what the Jetson app needs into jetson/bundle/ (the Docker build context of jetson/).

A Wendy app builds from its own folder, so the code and the few weights and data
files the demo uses are copied there (the datasets are not):
  bundle/scripts/                    every scripts/*.py (web_demo.py and what it imports)
  bundle/models/yolo11n-cls.pt       base weights for retraining the network on the Jetson
  bundle/seed/outputs2/              copied to the persistent volume at the first start:
    yolo_runs/<detector>/weights/best.pt      brick detector
    classifier_runs/<network>/weights/best.pt neural network (the reference demo network)
    classifier_crops/                         base crops for retraining
    calibration/<session>/                    calibration.json + crops (no frames)
    top_view/reference/calibration.json       fallback reference

The network and the calibrations were made with the C920: with the Gemini 2 make a
new calibration in the page; the network then retrains on the Jetson with it.

Usage: stage_jetson_app.py [--detector brick_seg_v3] [--network web_20261026_172444]
Then:  cd jetson && wendy run   (see jetson/README.md)
"""

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = PROJECT_ROOT / "outputs2"
BUNDLE = PROJECT_ROOT / "jetson" / "bundle"


def copy(src: Path, dst: Path) -> None:
    if not src.exists():
        raise SystemExit(f"missing: {src.relative_to(PROJECT_ROOT)}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--detector", default="brick_seg_v3", help="run in outputs2/yolo_runs")
    parser.add_argument("--network", default="web_20261026_172444", help="run in outputs2/classifier_runs")
    parser.add_argument("--extra-network", nargs="*", default=["gemini_20261027"],
                        help="more runs to bundle, not used unless chosen with --nn-weights")
    args = parser.parse_args()

    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    for path in sorted((PROJECT_ROOT / "scripts").glob("*.py")):
        copy(path, BUNDLE / "scripts" / path.name)
    copy(PROJECT_ROOT / "models" / "yolo11n-cls.pt", BUNDLE / "models" / "yolo11n-cls.pt")

    seed = BUNDLE / "seed" / "outputs2"
    for run in (f"yolo_runs/{args.detector}", f"classifier_runs/{args.network}",
                *(f"classifier_runs/{name}" for name in args.extra_network)):
        copy(OUTPUTS / run / "weights" / "best.pt", seed / run / "weights" / "best.pt")
    copy(OUTPUTS / "classifier_crops", seed / "classifier_crops")
    copy(OUTPUTS / "top_view" / "reference" / "calibration.json", seed / "top_view" / "reference" / "calibration.json")
    for path in sorted((OUTPUTS / "calibration").glob("*/calibration.json")):
        copy(path, seed / "calibration" / path.parent.name / "calibration.json")
        if (path.parent / "crops").exists():
            copy(path.parent / "crops", seed / "calibration" / path.parent.name / "crops")

    size = sum(p.stat().st_size for p in BUNDLE.rglob("*") if p.is_file())
    print(f"{BUNDLE.relative_to(PROJECT_ROOT)}: {size / 1e6:.1f} MB "
          f"(detector {args.detector}, network {args.network}, also bundled: {', '.join(args.extra_network) or '-'})")


if __name__ == "__main__":
    sys.exit(main())

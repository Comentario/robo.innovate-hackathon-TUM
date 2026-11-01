"""Fixed text-only SAM 3 experiment using the unchanged cached adapter.

Run only inside the immutable Docker image from a frozen default-queue job.
The input mount deliberately excludes evaluation references. No candidate
filtering, deduplication, geometry, mask repair or prompt adaptation occurs.
"""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time


PROMPTS = [
    {"id": "stack", "text": "stack of LEGO bricks"},
    {"id": "brick", "text": "LEGO brick"},
    {"id": "brick_2x4", "text": "2x4 LEGO brick"},
    {"id": "top_surface", "text": "top surface of a LEGO brick"},
]
IMAGE = "sha256:ae4ae0cfc9d41eadf32bf9ac689252fccd3a1f804bb69d088b65e47d91cad317"


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def raw_overlay(rgb, records):
    """Draw original-resolution raw contours, SAM boxes, IDs and scores only."""
    import cv2
    import numpy as np

    canvas = rgb.copy()
    height, width = rgb.shape[:2]
    for index, record in enumerate(records):
        color = tuple(int(v) for v in cv2.cvtColor(
            np.uint8([[[index*47 % 180, 220, 255]]]), cv2.COLOR_HSV2RGB)[0, 0])
        contours, _ = cv2.findContours(record["mask"].astype(np.uint8),
                                       cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 1, cv2.LINE_AA)
        x1, y1, x2, y2 = record["sam_bbox_xyxy"]
        cv2.rectangle(canvas, (round(x1), round(y1)), (round(x2), round(y2)), color, 1)
        text = f"{record['raw_id']} {record['score']:.3f}"
        # Label placement does not modify a mask, box or detection record.
        x = max(0, min(width-1, round(x1)))
        y = max(12, min(height-2, round(y1)-3))
        cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .35, (0, 0, 0), 2)
        cv2.putText(canvas, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, .35, color, 1)
    return canvas


def main():
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise SystemExit("SAM inference must run through the frozen default Pueue queue job")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    config = json.loads(args.config.read_text())
    if (config["prompts"] != PROMPTS or config["docker_image"] != IMAGE
            or config["expected_images"] != 18 or config["confidence_threshold"] != .5
            or config["resolution"] != 1008 or config["deduplication"] is not False
            or config["precision"] != "CUDA BF16 autocast"):
        raise ValueError("Configuration differs from the authorized fixed SAM 3 experiment")
    if platform.python_version() != "3.12.11":
        raise RuntimeError("The pinned SAM 3 container Python 3.12.11 is required; no runtime fallback")
    upstream = args.config.parent / "upstream"
    pins = json.loads((upstream / "provenance.json").read_text())
    metadata = json.loads((upstream / "checkpoint.json").read_text())
    if sha256(upstream / "sam3_candidates.py") != pins["sha256"]["sam3_candidates.py"]:
        raise ValueError("Frozen SAM adapter hash differs from the recorded source")
    if args.checkpoint.stat().st_size != metadata["bytes"]:
        raise ValueError("Cached checkpoint size differs from pinned metadata")
    checkpoint_hash = sha256(args.checkpoint)
    if checkpoint_hash != metadata["sha256"] or checkpoint_hash != metadata["expected_lfs_sha256"]:
        raise ValueError("Cached checkpoint SHA-256 differs from pinned metadata")
    images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if len(images) != config["expected_images"]:
        raise ValueError(f"Expected all 18 uploaded images, found {len(images)}")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "adapter_raw").mkdir(exist_ok=True)

    import cv2
    import numpy as np
    import torch
    from PIL import Image
    import sam3_candidates

    if Path(sam3_candidates.__file__).resolve() != (upstream / "sam3_candidates.py").resolve():
        raise RuntimeError("Inference did not import the frozen unchanged adapter")
    cv2.setNumThreads(2)
    torch.set_num_threads(2)
    model = sam3_candidates.Sam3Candidates(args.checkpoint, metadata["model_revision"])
    versions = {}
    for name in ("sam3", "torch", "torchvision", "numpy", "opencv-python", "opencv-python-headless", "Pillow", "triton"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    provenance = {
        "experiment": config["experiment"], "docker_image": IMAGE,
        "python": platform.python_version(), "versions": versions,
        "opencv_runtime": cv2.__version__, "network": "disabled by Docker launcher",
        "config": config, "config_sha256": sha256(args.config),
        "adapter_sha256": sha256(upstream / "sam3_candidates.py"),
        "source_adapter_provenance": pins, "checkpoint_metadata": metadata,
        "checkpoint_sha256_verified": checkpoint_hash,
        "input_sha256": {p.name: sha256(p) for p in images},
        "model": model.provenance, "images": [],
        "notes": [
            "One image encoding per image; unchanged adapter resets prompts for each independent query.",
            "All returned raw masks/boxes/scores retained, including empty masks; no candidates_from_raw call.",
            "Processor confidence threshold 0.5 is unchanged; no additional filtering or suppression.",
            "Masks are original-resolution adapter PNGs copied byte-for-byte, not repaired or refined.",
            "Inference receives only RGB, fixed text prompts, checkpoint and pinned software metadata.",
        ],
    }
    peak_allocated = model.provenance["peak_allocated_bytes"]
    peak_reserved = model.provenance["peak_reserved_bytes"]
    write_json(args.output / "runtime_manifest.json", provenance)
    for image_path in images:
        rgb = np.asarray(Image.open(image_path).convert("RGB"))
        height, width = rgb.shape[:2]
        raw_folder = args.output / "adapter_raw" / image_path.stem
        raw, timing = model.segment(rgb, [p["text"] for p in PROMPTS], raw_folder)
        counts = {}
        for prompt in PROMPTS:
            destination = args.output / prompt["id"] / image_path.stem
            destination.mkdir(parents=True, exist_ok=True)
            records = [r for r in raw if r["concept"] == prompt["text"]]
            detections = []
            for record in records:
                mask = record["mask"]
                if mask.dtype != np.bool_ or mask.shape != (height, width):
                    raise RuntimeError("Raw SAM output mask is not original-resolution binary data")
                filename = f"{record['raw_id']}.png"
                source = raw_folder / filename
                target = destination / filename
                shutil.copy2(source, target)
                if sha256(source) != sha256(target):
                    raise RuntimeError("Raw mask copy changed its bytes")
                detections.append({"id": record["raw_id"],
                    "box_xyxy": record["sam_bbox_xyxy"], "score": record["score"],
                    "mask": filename, "mask_sha256": sha256(target)})
            write_json(destination / "raw.json", {
                "image": image_path.name, "prompt_id": prompt["id"], "prompt": prompt["text"],
                "width": width, "height": height, "detections": detections,
                "original_adapter_manifest": str(Path("../../adapter_raw") / image_path.stem / "raw.json"),
            })
            Image.fromarray(raw_overlay(rgb, records)).save(destination / "overlay.png")
            counts[prompt["id"]] = len(detections)
        peak_allocated = max(peak_allocated, timing["peak_allocated_bytes"])
        peak_reserved = max(peak_reserved, timing["peak_reserved_bytes"])
        provenance["images"].append({"image": image_path.name, "width": width, "height": height,
                                      "counts": counts, "timing": timing})
        write_json(args.output / "runtime_manifest.json", provenance)
        print("IMAGE_DONE", image_path.name, json.dumps(counts), flush=True)
        del raw, rgb
    provenance.update(seconds=time.monotonic()-started,
                      maximum_peak_allocated_bytes=peak_allocated,
                      maximum_peak_reserved_bytes=peak_reserved)
    write_json(args.output / "runtime_manifest.json", provenance)
    hashes = {str(p.relative_to(args.output)): sha256(p)
              for p in sorted(args.output.rglob("*")) if p.is_file()}
    write_json(args.output / "artifact_hashes.json", hashes)
    write_json(args.output / "run_complete.json", {
        "complete": True, "images": len(images), "prompts": len(PROMPTS),
        "image_prompt_outputs": len(images)*len(PROMPTS),
        "runtime_manifest_sha256": sha256(args.output / "runtime_manifest.json"),
        "artifact_hashes_sha256": sha256(args.output / "artifact_hashes.json"),
    })
    print("SAM3_COMPLETE", args.output, flush=True)


if __name__ == "__main__":
    main()

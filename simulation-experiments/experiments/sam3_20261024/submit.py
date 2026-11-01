"""Freeze the bounded SAM 3 experiment and submit one default-queue job.

Inference runs offline in the exact cached image. Evaluation runs afterwards
as a separate host process; its reference mount is never visible to Docker.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess


EXPERIMENT = Path(__file__).resolve().parent
ROOT = EXPERIMENT.parents[1]
HOST_PYTHON = "/home/faps/miniforge3/envs/unitree_sim_env/bin/python"
IMAGE = "sha256:ae4ae0cfc9d41eadf32bf9ac689252fccd3a1f804bb69d088b65e47d91cad317"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=Path, default=ROOT / "resources/realsense_d435i_lego")
    parser.add_argument("--reference", type=Path,
                        default=ROOT / "experiments/detection_20261024/reference/annotations.json")
    parser.add_argument("--snapshot-only", action="store_true")
    args = parser.parse_args()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--", str(EXPERIMENT.relative_to(ROOT))],
        cwd=ROOT, text=True)
    if dirty:
        parser.error("Commit the scoped experiment source/configuration before freezing a job")
    config = json.loads((EXPERIMENT / "config.json").read_text())
    frozen = json.loads((EXPERIMENT / "input_freeze.json").read_text())
    metadata = json.loads((EXPERIMENT / "upstream/checkpoint.json").read_text())
    if config["docker_image"] != IMAGE:
        parser.error("Only the exact authorized cached Docker image is allowed")
    checkpoint = Path(metadata["local_path"]).resolve(strict=True)
    if checkpoint.stat().st_size != metadata["bytes"]:
        parser.error("Cached checkpoint size mismatch; no download or fallback is permitted")
    images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if len(images) != config["expected_images"]:
        parser.error("The experiment requires all 18 uploaded images")
    if not (EXPERIMENT / "evaluation.py").is_file():
        parser.error("Independent evaluation.py must be ready before submission")
    if not (EXPERIMENT / "protocol.json").is_file():
        parser.error("Frozen independent protocol.json must be ready before submission")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    snapshot = ROOT / "runs" / f"{stamp}-sam3-fixed-prompts"
    inference = snapshot / "inference"
    scoring = snapshot / "scoring_only"
    output = snapshot / "output"
    (inference / "images").mkdir(parents=True)
    scoring.mkdir()
    output.mkdir()
    shutil.copy2(EXPERIMENT / "run_inference.py", inference / "run_inference.py")
    shutil.copy2(EXPERIMENT / "config.json", inference / "config.json")
    shutil.copytree(EXPERIMENT / "upstream", inference / "upstream",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for source in images:
        shutil.copy2(source, inference / "images" / source.name)
    shutil.copy2(EXPERIMENT / "evaluation.py", scoring / "evaluation.py")
    shutil.copy2(args.reference, scoring / "annotations.json")
    shutil.copy2(EXPERIMENT / "protocol.json", scoring / "protocol.json")
    shutil.copy2(EXPERIMENT / "input_freeze.json", snapshot / "input_freeze.json")
    image_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((inference / "images").iterdir())}
    if image_hashes != frozen["images"]:
        parser.error("Copied images differ from the frozen exact 18-image reference inventory")
    if hashlib.sha256((inference / "config.json").read_bytes()).hexdigest() != frozen["config_sha256"]:
        parser.error("Copied configuration differs from the predeclared frozen configuration")
    if hashlib.sha256((scoring / "annotations.json").read_bytes()).hexdigest() != frozen["reference_sha256"]:
        parser.error("Copied scoring annotations differ from the frozen independent reference")
    if hashlib.sha256((inference / "upstream/sam3_candidates.py").read_bytes()).hexdigest() != frozen["source_adapter_sha256"]:
        parser.error("Copied adapter differs from the frozen unchanged upstream source")
    # Preserve the submission mechanism itself outside the inference mount.
    shutil.copy2(EXPERIMENT / "submit.py", snapshot / "submit.py")
    docker = ["docker", "run", "--rm", "--pull=never", "--gpus", "all",
        "--user", f"{os.getuid()}:{os.getgid()}", "--entrypoint", "python",
        "--network=none", "--read-only", "--tmpfs", "/tmp:rw,nosuid,nodev,size=2g",
        "--mount", f"type=bind,source={inference},target=/experiment,readonly",
        "--mount", f"type=bind,source={checkpoint},target=/checkpoint/sam3.pt,readonly",
        "--mount", f"type=bind,source={output},target=/output",
        "--env", "PYTHONPATH=/experiment/upstream:/app/src", "--env", "ROBO_PUEUE_JOB=1",
        "--env", "PYTHONDONTWRITEBYTECODE=1", "--env", "HOME=/tmp",
        "--env", "XDG_CACHE_HOME=/tmp/cache", "--env", "HF_HOME=/tmp/hf",
        "--env", "TORCH_HOME=/tmp/torch", "--env", "TRITON_CACHE_DIR=/tmp/triton",
        "--env", "OMP_NUM_THREADS=2", IMAGE, "/experiment/run_inference.py",
        "--config", "/experiment/config.json", "--images", "/experiment/images",
        "--checkpoint", "/checkpoint/sam3.pt", "--output", "/output/predictions"]
    evaluation = [HOST_PYTHON, str(scoring / "evaluation.py"),
                  "--predictions", str(output / "predictions"),
                  "--reference", str(scoring / "annotations.json"),
                  "--output", str(output / "evaluation")]
    launch = ["#!/usr/bin/env bash", "set -euo pipefail",
              f"cd {shlex.quote(str(snapshot))}", "export ROBO_PUEUE_JOB=1",
              "export OMP_NUM_THREADS=2", shlex.join(docker),
              "test -f output/predictions/run_complete.json", shlex.join(evaluation),
              "test -f output/evaluation/evaluation.json",
              "printf '%s' '{\"complete\":true}' > run_complete.json", ""]
    (snapshot / "launch.sh").write_text("\n".join(launch))
    manifest = {
        "created_utc": stamp, "docker_image": IMAGE, "network": "none",
        "checkpoint_host_path": str(checkpoint), "checkpoint_expected_sha256": metadata["sha256"],
        "inference_mount": "inference/ read-only; scoring_only/ is not mounted",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "sha256": {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(snapshot.rglob("*")) if p.is_file()},
    }
    (snapshot / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Snapshot:", snapshot, flush=True)
    if not args.snapshot_only:
        result = subprocess.run(["pueue", "add", "--label", "robo26-sam3-fixed-prompts",
                                  shlex.join(["bash", str(snapshot / "launch.sh")])],
                                 check=True, capture_output=True, text=True)
        print(result.stdout.strip())
        (snapshot / "submission.txt").write_text(result.stdout)


if __name__ == "__main__":
    main()

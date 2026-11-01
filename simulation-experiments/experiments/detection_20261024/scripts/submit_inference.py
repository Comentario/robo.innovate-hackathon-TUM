"""Freeze this bounded inference experiment and submit to default Pueue."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

EXPERIMENT = Path(__file__).resolve().parents[1]
ROOT = EXPERIMENT.parents[1]
PYTHON = Path("/home/faps/miniforge3/envs/unitree_sim_env/bin/python")
parser = argparse.ArgumentParser()
parser.add_argument("--input-dir", type=Path, default=ROOT / "resources/realsense_d435i_lego")
parser.add_argument("--domain", choices=("real", "sim"), default="real")
args = parser.parse_args()
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
snapshot = ROOT / "runs" / f"{stamp}-detection-{args.domain}"
snapshot.mkdir(parents=True)
for directory in ("scripts", "models", ".deps"):
    shutil.copytree(EXPERIMENT / directory, snapshot / directory, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
shutil.copytree(args.input_dir, snapshot / "images")
output = snapshot / "predictions"
launch = ["#!/usr/bin/env bash", "set -eo pipefail",
          "source /home/faps/miniforge3/etc/profile.d/conda.sh",
          "conda activate /home/faps/miniforge3/envs/unitree_sim_env", "set -u",
          f"cd {shlex.quote(str(snapshot))}",
          f"export PYTHONPATH={shlex.quote(str(snapshot / '.deps'))}",
          f"export YOLO_CONFIG_DIR={shlex.quote(str(snapshot / 'yolo_config'))}",
          "export PYTHONDONTWRITEBYTECODE=1", "export ROBO_PUEUE_JOB=1", "export OMP_NUM_THREADS=2",
          shlex.join([str(PYTHON), str(snapshot / "scripts/run_inference.py"), "--input-dir", str(snapshot / "images"),
                      "--weights-dir", str(snapshot / "models"), "--output-dir", str(output), "--domain", args.domain]),
          "test -f predictions/run_complete.json", ""]
(snapshot / "launch.sh").write_text("\n".join(launch))
manifest = {"created_utc": stamp, "domain": args.domain, "python": str(PYTHON),
            "studwise_commit": "3aef8aade8cb74a04780d5e809e49dfa1fc57a47",
            "source_image_directory": str(args.input_dir.resolve()),
            "sha256": {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(snapshot.rglob("*")) if p.is_file()}}
(snapshot / "manifest.json").write_text(json.dumps(manifest, indent=2))
result = subprocess.run(["pueue", "add", "--label", f"robo26-detector-{args.domain}",
                         shlex.join(["bash", str(snapshot / "launch.sh")])], check=True, capture_output=True, text=True)
print("Snapshot:", snapshot)
print(result.stdout.strip())
(snapshot / "submission.txt").write_text(result.stdout)

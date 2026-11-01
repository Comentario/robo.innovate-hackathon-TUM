"""Freeze one geometric perception version and queue its fixed evaluation."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PYTHON = Path("/home/faps/miniforge3/envs/unitree_sim_env/bin/python")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--config", type=Path, required=True)
parser.add_argument("--tag", required=True)
parser.add_argument("--split", choices=["development", "heldout"], default="development")
args = parser.parse_args()
if not (ROOT/"perception/algorithm.py").is_file():
    parser.error("Geometric baseline implementation is not ready")
status = subprocess.run(["git", "status", "--porcelain", "--", "perception"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
if status:
    parser.error("Commit the scoped perception source/protocol/config before freezing an evaluated version")
commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
snapshot = ROOT/"runs"/f"{stamp}-known-layout-{args.tag}-{args.split}"
snapshot.mkdir(parents=True)
shutil.copytree(ROOT/"perception", snapshot/"perception", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
inputs = snapshot/"evaluation_input"
(inputs/"images").mkdir(parents=True)
regs = json.loads((ROOT/f"perception/evaluation/registrations_{args.split}.json").read_text())
names = {r["file"] for r in regs["images"]}
(inputs/"registrations.json").write_text(json.dumps(regs, indent=2)+"\n")
references = json.loads((ROOT/"experiments/detection_20261024/reference/annotations.json").read_text())
references["images"] = [r for r in references["images"] if r["file"] in names]
(inputs/"reference.json").write_text(json.dumps(references, indent=2)+"\n")
missing = json.loads((ROOT/"perception/evaluation/missing_reference.json").read_text())
missing["instances"] = [r for r in missing["instances"] if r["file"] in names]
(inputs/"missing_reference.json").write_text(json.dumps(missing, indent=2)+"\n")
for name in names:
    shutil.copy2(ROOT/"resources/realsense_d435i_lego"/name, inputs/"images"/name)
config = args.config.resolve()
dest_config = snapshot/"effective_config.json"
shutil.copy2(config, dest_config)
launch = ["#!/usr/bin/env bash", "set -eo pipefail", "source /home/faps/miniforge3/etc/profile.d/conda.sh",
          "conda activate /home/faps/miniforge3/envs/unitree_sim_env", "set -u", f"cd {shlex.quote(str(snapshot))}",
          f"export PYTHONPATH={shlex.quote(str(snapshot))}", "export PYTHONDONTWRITEBYTECODE=1", "export ROBO_PUEUE_JOB=1",
          "export OMP_NUM_THREADS=2", "export OPENBLAS_NUM_THREADS=2",
          shlex.join([str(PYTHON), str(snapshot/"perception/evaluation/run_batch.py"), "--config", str(dest_config)]),
          "test -f run_complete.json", ""]
(snapshot/"launch.sh").write_text("\n".join(launch))
manifest = {"git_commit": commit, "tag": args.tag, "split": args.split, "created_utc": stamp, "python": str(PYTHON),
            "sha256": {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(snapshot.rglob("*")) if p.is_file()}}
(snapshot/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
job = subprocess.run(["pueue", "add", "--label", f"robo26-geometry-{args.tag}-{args.split}", shlex.join(["bash", str(snapshot/"launch.sh")])],
                     check=True, text=True, capture_output=True)
(snapshot/"submission.txt").write_text(job.stdout)
print("Snapshot:", snapshot)
print("Source commit:", commit)
print(job.stdout.strip())

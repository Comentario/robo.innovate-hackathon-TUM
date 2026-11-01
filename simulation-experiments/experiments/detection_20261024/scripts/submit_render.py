#!/usr/bin/env python3
"""Freeze the existing runtime/scene and queue one full-stack render experiment."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = ROOT / "experiments/detection_20261024"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_benchmark import geometry

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--geometry", type=Path, default=EXPERIMENT / "simulation/geometry_spec.json")
parser.add_argument("--python", type=Path, default=Path("/home/faps/miniforge3/envs/unitree_sim_env/bin/python"))
parser.add_argument("--snapshot-only", action="store_true")
args = parser.parse_args()
spec, bricks = geometry(args.geometry)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
snapshot = ROOT / "runs" / f"{stamp}-detection-full360-render"
scriptdir = snapshot / "experiments/detection_20261024/scripts"
scriptdir.mkdir(parents=True)
for directory in ("challenge2", "configs", ".deps"):
    shutil.copytree(ROOT / directory, snapshot / directory,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
for name in ("render_benchmark.py", "submit_render.py"):
    shutil.copy2(EXPERIMENT / "scripts" / name, scriptdir / name)
geometry_path = snapshot / "geometry.json"
geometry_path.write_text(json.dumps(spec, indent=2))
output = EXPERIMENT / "simulation" / "render_runs" / stamp
prefix = args.python.resolve().parent.parent
conda_sh = prefix.parent.parent / "etc/profile.d/conda.sh"
command = [str(args.python), str(scriptdir / "render_benchmark.py"),
           "--geometry", str(geometry_path), "--output", str(output),
           "--headless", "--enable_cameras", "--device", "cpu"]
launch = "\n".join([
    "#!/usr/bin/env bash", "set -eo pipefail",
    f"source {shlex.quote(str(conda_sh))}",
    f"conda activate {shlex.quote(str(prefix))}", "set -u",
    f"cd {shlex.quote(str(snapshot))}",
    f"export PYTHONPATH={shlex.quote(str(snapshot / '.deps')+':'+str(snapshot))}",
    "export PYTHONDONTWRITEBYTECODE=1", "export ROBO_PUEUE_JOB=1",
    shlex.join(command), f"test -f {shlex.quote(str(output / 'run_complete.json'))}", "",
])
(snapshot / "launch.sh").write_text(launch)
manifest = {"created_utc":stamp,"output":str(output),"python":str(args.python),
            "required_brick_count":360,"geometry":spec,"sha256":{
                str(p.relative_to(snapshot)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(snapshot.rglob("*")) if p.is_file()}}
(snapshot / "manifest.json").write_text(json.dumps(manifest, indent=2))
print("Snapshot:", snapshot, flush=True)
print("Output:", output, flush=True)
if not args.snapshot_only:
    result = subprocess.run(["pueue", "add", "--label", "robo26-detection-full360-render",
                             shlex.join(["bash",str(snapshot / "launch.sh")])],
                             check=True,text=True,capture_output=True)
    print(result.stdout.strip(),flush=True)
    (snapshot / "submission.txt").write_text(result.stdout)

#!/usr/bin/env python3
"""Freeze source/config/dependencies and submit to the default Pueue queue."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from challenge2.layout import load_config

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--config", type=Path, default=ROOT / "configs/workcell.json")
parser.add_argument("--python", type=Path, default=Path("/home/faps/miniforge3/envs/unitree_sim_env/bin/python"))
parser.add_argument("--mode", choices=["smoke", "preview", "train", "evaluate"], default="smoke")
parser.add_argument("--steps", type=int, default=60)
parser.add_argument("--timesteps", type=int, default=100000)
parser.add_argument("--checkpoint", type=Path)
parser.add_argument("--recipe", choices=["mixed", "single_shade"])
parser.add_argument("--cells", type=int)
parser.add_argument("--layers", type=int)
parser.add_argument("--tool", choices=["parallel", "paper"])
parser.add_argument("--snapshot-only", action="store_true")
parser.add_argument("--capture", action="store_true", help="Verify CUDA and save rendered workcell images")
args = parser.parse_args()
cfg = load_config(args.config)
if args.recipe:
    cfg["recipe"] = args.recipe
if args.cells:
    cfg["source_cells"] = args.cells
if args.layers:
    cfg["source_layers"] = args.layers
if args.tool:
    cfg["tool"]["kind"] = args.tool
if cfg["tool"]["kind"] == "paper":
    parser.error("Paper tool physics requires validated CAD and a Franka mount; comparison interface is reserved but not runnable.")
if args.mode == "evaluate" and not args.checkpoint:
    parser.error("evaluate requires --checkpoint")
if args.steps <= 0 or args.timesteps <= 0:
    parser.error("steps/timesteps must be positive")
if not args.python.is_file():
    parser.error(f"Isaac Python does not exist: {args.python}")
if not (ROOT / ".deps/bricksim").is_dir():
    parser.error("Install the pinned BrickSim wheel using scripts/setup_dependencies.sh")
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
snapshot = ROOT / "runs" / f"{stamp}-{args.mode}"
snapshot.mkdir(parents=True)
for directory in ("challenge2", "scripts", ".deps"):
    shutil.copytree(ROOT / directory, snapshot / directory, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
(snapshot / "configs").mkdir()
(snapshot / "configs/workcell.json").write_text(json.dumps(cfg, indent=2)+"\n")
load_config(snapshot / "configs/workcell.json")
forward = ["--mode", args.mode, "--steps", str(args.steps), "--timesteps", str(args.timesteps), "--device", "cpu"]
if args.mode != "preview":
    forward.append("--headless")
if args.capture:
    forward += ["--capture", "--enable_cameras"]
if args.checkpoint:
    dest = snapshot / args.checkpoint.name
    shutil.copy2(args.checkpoint, dest)
    forward += ["--checkpoint", str(dest)]
prefix = args.python.resolve().parent.parent
conda_sh = prefix.parent.parent / "etc/profile.d/conda.sh"
if not conda_sh.is_file():
    parser.error(f"Expected Conda activation script: {conda_sh}")
launch = "\n".join([
    "#!/usr/bin/env bash", "set -eo pipefail",
    f"source {shlex.quote(str(conda_sh))}", f"conda activate {shlex.quote(str(prefix))}",
    "set -u",
    f"cd {shlex.quote(str(snapshot))}",
    f"export PYTHONPATH={shlex.quote(str(snapshot / '.deps') + ':' + str(snapshot))}",
    "export PYTHONDONTWRITEBYTECODE=1", "export ROBO_PUEUE_JOB=1",
    shlex.join([str(args.python), str(snapshot / "scripts/run.py"), *forward]),
    # Kit may turn an unhandled Python exception into a zero process exit.
    # Require our own completion marker before Pueue can report success.
    "test -f run_complete.json", "",
])
(snapshot / "launch.sh").write_text(launch)
files = {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(snapshot.rglob("*")) if p.is_file()}
manifest = {"created_utc": stamp, "python": str(args.python), "brick_sim_commit": "cbd5de3238e6ac12f44ef699e1507a9f16bdafc3", "sha256": files}
(snapshot / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
print(f"Snapshot: {snapshot}", flush=True)
if not args.snapshot_only:
    result = subprocess.run(["pueue", "add", "--label", f"robo26-c2-{args.mode}",
                             shlex.join(["bash", str(snapshot / "launch.sh")])], check=True, text=True, capture_output=True)
    print(result.stdout.strip())
    (snapshot / "submission.txt").write_text(result.stdout)

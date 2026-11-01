"""Queue independently selectable full-stack views using the existing Isaac runtime."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

EXPERIMENT = Path(__file__).resolve().parent
ROOT = EXPERIMENT.parents[1]
sys.path.insert(0, str(EXPERIMENT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--geometry", type=Path, default=EXPERIMENT/"geometry.json")
    parser.add_argument("--cameras", type=Path, default=EXPERIMENT/"cameras.json")
    parser.add_argument("--views", default="all", help="all, one name, or comma-separated camera names")
    parser.add_argument("--python", type=Path, default=Path("/home/faps/miniforge3/envs/unitree_sim_env/bin/python"))
    parser.add_argument("--snapshot-only", action="store_true")
    args = parser.parse_args()
    from render_views import load_geometry
    spec, bricks = load_geometry(args.geometry)
    cameras = json.loads(args.cameras.read_text())
    available = [view["id"] for view in cameras["views"]]
    selected = available if args.views == "all" else [v.strip() for v in args.views.split(",")]
    if not selected or len(set(selected)) != len(selected) or any(v not in available for v in selected):
        parser.error(f"Choose camera names from {available}; received {selected}")
    scope = ["challenge2", "configs/workcell.json", str(EXPERIMENT.relative_to(ROOT))]
    if subprocess.check_output(["git", "status", "--porcelain", "--", *scope], cwd=ROOT, text=True):
        parser.error("Commit the scoped scene/render source before freezing a job")
    if not args.python.is_file() or not (ROOT/".deps/bricksim").is_dir():
        parser.error("The existing Isaac Python and pinned local BrickSim dependency are required")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    snapshot = ROOT/"runs"/f"{stamp}-sim-views"
    scriptdir = snapshot/"experiments/sim_views_20261024"
    scriptdir.mkdir(parents=True)
    for name in ("challenge2", ".deps"):
        shutil.copytree(ROOT/name, snapshot/name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (snapshot/"configs").mkdir()
    shutil.copy2(ROOT/"configs/workcell.json", snapshot/"configs/workcell.json")
    for name in ("render_views.py", "submit.py"):
        shutil.copy2(EXPERIMENT/name, scriptdir/name)
    (scriptdir/"geometry.json").write_text(json.dumps(spec, indent=2)+"\n")
    (scriptdir/"cameras.json").write_text(json.dumps(cameras, indent=2)+"\n")
    prefix = args.python.resolve().parent.parent
    conda_sh = prefix.parent.parent/"etc/profile.d/conda.sh"
    if not conda_sh.is_file():
        parser.error(f"Existing Conda activation script not found: {conda_sh}")
    command = [str(args.python), str(scriptdir/"render_views.py"),
        "--geometry", str(scriptdir/"geometry.json"), "--cameras", str(scriptdir/"cameras.json"),
        "--views", ",".join(selected), "--output", str(snapshot/"output"),
        "--headless", "--enable_cameras", "--device", "cpu"]
    launch = ["#!/usr/bin/env bash", "set -eo pipefail",
        f"source {shlex.quote(str(conda_sh))}", f"conda activate {shlex.quote(str(prefix))}",
        "set -u", f"cd {shlex.quote(str(snapshot))}",
        f"export PYTHONPATH={shlex.quote(str(snapshot/'.deps')+':'+str(snapshot))}",
        "export PYTHONDONTWRITEBYTECODE=1", "export ROBO_PUEUE_JOB=1",
        shlex.join(command), "test -f output/run_complete.json", ""]
    (snapshot/"launch.sh").write_text("\n".join(launch))
    manifest = {"created_utc": stamp, "source_commit": subprocess.check_output([
        "git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "python": str(args.python), "required_bricks": len(bricks), "selected_views": selected,
        "combined_output": "same-state RGB image panel only; no perception fusion",
        "geometry": spec, "cameras": cameras,
        "sha256": {str(p.relative_to(snapshot)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in sorted(snapshot.rglob("*")) if p.is_file()}}
    (snapshot/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print("Snapshot:", snapshot, flush=True)
    print("Views:", ", ".join(selected), flush=True)
    if not args.snapshot_only:
        task = subprocess.run(["pueue", "add", "--label", "robo26-sim-views",
            shlex.join(["bash", str(snapshot/"launch.sh")])], check=True, capture_output=True, text=True)
        (snapshot/"submission.txt").write_text(task.stdout)
        print(task.stdout.strip())


if __name__ == "__main__":
    main()

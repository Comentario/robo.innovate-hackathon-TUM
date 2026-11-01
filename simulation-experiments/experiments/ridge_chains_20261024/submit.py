"""Freeze and queue the bounded RGB ridge-chain comparison in default Pueue."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import shlex
import shutil
import subprocess

EXPERIMENT = Path(__file__).resolve().parent
ROOT = EXPERIMENT.parents[1]
PYTHON = "/home/faps/miniforge3/envs/unitree_sim_env/bin/python"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    status = subprocess.check_output(["git", "status", "--porcelain", "--",
        str(EXPERIMENT.relative_to(ROOT))], cwd=ROOT, text=True)
    if status:
        raise SystemExit("Commit the scoped code/config/protocol before submission")
    sam = ROOT/"experiments/sam3_20261024/results"
    size = ROOT/"experiments/sam3_sizefilter_20261024/results"
    sam_provenance = json.loads((sam/"provenance.json").read_text())
    size_provenance = json.loads((size/"provenance.json").read_text())
    if sha(sam/"evaluation.json") != sam_provenance["evaluation_sha256"]:
        raise ValueError("Saved raw SAM evaluation changed")
    if sha(size/"evaluation.json") != size_provenance["durable_evaluation_sha256"]:
        raise ValueError("Saved dimension-filter evaluation changed")
    images_sha = json.loads((sam/"input_freeze.json").read_text())["images"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    snapshot = ROOT/"runs"/f"{stamp}-rgb-ridge-chains"
    code, images, scoring, output = [snapshot/n for n in ("code", "images", "scoring_only", "output")]
    for p in (code, images, scoring, output):
        p.mkdir(parents=True, exist_ok=True)
    for name in ("chains.py", "config.json"):
        shutil.copy2(EXPERIMENT/name, code/name)
    for name in ("evaluate.py", "base_evaluation.py", "protocol.json"):
        shutil.copy2(EXPERIMENT/name, scoring/name)
    fixtures = {
        "annotations.json": ROOT/"experiments/detection_20261024/reference/annotations.json",
        "missing_reference.json": ROOT/"perception/evaluation/missing_reference.json",
        "sam_evaluation.json": sam/"evaluation.json",
        "size_evaluation.json": size/"evaluation.json",
    }
    for name, source in fixtures.items():
        shutil.copy2(source, scoring/name)
    shutil.copy2(EXPERIMENT/"submit.py", snapshot/"submit.py")
    commands = []
    for number in range(1, 19):
        file, stem = f"img_{number}.jpg", f"img_{number}"
        shutil.copy2(ROOT/"resources/realsense_d435i_lego"/file, images/file)
        if sha(images/file) != images_sha[file]:
            raise ValueError(f"Uploaded image changed: {file}")
        commands.append(shlex.join([PYTHON, str(code/"chains.py"),
            "--image", str(images/file), "--config", str(code/"config.json"),
            "--output", str(output/"predictions"/stem)]))
        commands.append("test -f "+shlex.quote(str(output/"predictions"/stem/"chains.json")))
    # Labels and historical manual registrations are never chain-program inputs.
    commands.append(shlex.join([PYTHON, str(scoring/"evaluate.py"),
        "--predictions", str(output/"predictions"),
        "--reference", str(scoring/"annotations.json"),
        "--missing-reference", str(scoring/"missing_reference.json"),
        "--sam-evaluation", str(scoring/"sam_evaluation.json"),
        "--size-evaluation", str(scoring/"size_evaluation.json"),
        "--output", str(output/"evaluation")]))
    launch = ["#!/usr/bin/env bash", "set -euo pipefail", f"cd {shlex.quote(str(snapshot))}",
        "export ROBO_PUEUE_JOB=1", "export OMP_NUM_THREADS=2", "export OPENBLAS_NUM_THREADS=2",
        "export PYTHONDONTWRITEBYTECODE=1", *commands,
        "test -f output/evaluation/evaluation.json",
        "printf '%s' '{\"complete\":true,\"images\":18}' > run_complete.json", ""]
    (snapshot/"launch.sh").write_text("\n".join(launch))
    manifest = {"created_utc": stamp, "source_commit": subprocess.check_output([
        "git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "runtime": PYTHON, "model_inference": False,
        "chain_inputs": "original RGB and global config only; saved SAM is comparison-only in this edge-proposal variant",
        "scoring_inputs_only": list(fixtures),
        "sha256": {str(p.relative_to(snapshot)): sha(p) for p in sorted(snapshot.rglob("*")) if p.is_file()}}
    (snapshot/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    task = subprocess.run(["pueue", "add", "--label", "robo26-rgb-ridge-chains",
        shlex.join(["bash", str(snapshot/"launch.sh")])], check=True, capture_output=True, text=True)
    (snapshot/"submission.txt").write_text(task.stdout)
    print("Snapshot:", snapshot)
    print(task.stdout.strip())


if __name__ == "__main__":
    main()

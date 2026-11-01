"""Snapshot saved SAM masks and queue one size-filter/seam-splitting run."""
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    dirty = subprocess.check_output([
        "git", "status", "--porcelain", "--", str(EXPERIMENT.relative_to(ROOT))], cwd=ROOT, text=True)
    if dirty:
        raise SystemExit("Commit this scoped experiment before queue submission")
    previous = ROOT/"experiments/sam3_20261024/results"
    provenance = json.loads((previous/"provenance.json").read_text())
    raw_root = Path(provenance["raw_predictions_root"])
    hashes_path = Path(provenance["artifact_hash_manifest"])
    if digest(hashes_path) != provenance["artifact_hash_manifest_sha256"]:
        raise ValueError("Original SAM artifact manifest changed")
    hashes = json.loads(hashes_path.read_text())
    frozen_images = json.loads((previous/"input_freeze.json").read_text())["images"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    snapshot = ROOT/"runs"/f"{stamp}-sam3-size-filter"
    code, inputs, scoring, output = [snapshot/p for p in ("code", "inputs", "scoring_only", "output")]
    for p in (code, inputs/"images", inputs/"brick", scoring, output):
        p.mkdir(parents=True, exist_ok=True)
    for filename in ("filter.py", "config.json"):
        shutil.copy2(EXPERIMENT/filename, code/filename)
    for filename in ("evaluate.py", "base_evaluation.py", "protocol.json"):
        shutil.copy2(EXPERIMENT/filename, scoring/filename)
    reference = ROOT/"experiments/detection_20261024/reference/annotations.json"
    if digest(reference) != provenance["reference_sha256"]:
        raise ValueError("Independent historical annotations changed")
    shutil.copy2(reference, scoring/"annotations.json")
    shutil.copy2(EXPERIMENT/"submit.py", snapshot/"submit.py")
    shutil.copy2(previous/"provenance.json", snapshot/"sam3_provenance.json")
    commands = []
    for n in range(1, 19):
        name, stem = f"img_{n}.jpg", f"img_{n}"
        image = inputs/"images"/name
        shutil.copy2(ROOT/"resources/realsense_d435i_lego"/name, image)
        if digest(image) != frozen_images[name]:
            raise ValueError(f"Uploaded RGB changed: {name}")
        target = inputs/"brick"/stem
        target.mkdir()
        original = raw_root/"brick"/stem
        data = json.loads((original/"raw.json").read_text())
        for filename in ["raw.json"]+[d["mask"] for d in data["detections"]]:
            source, dest = original/filename, target/filename
            shutil.copy2(source, dest)
            if digest(dest) != hashes[str(source.relative_to(raw_root))]:
                raise ValueError(f"Saved SAM output changed: {source}")
        commands.append(shlex.join([PYTHON, str(code/"filter.py"),
            "--image", str(image), "--raw", str(target/"raw.json"),
            "--config", str(code/"config.json"), "--output", str(output/"processed"/stem)]))
    # Prediction-only process inputs above exclude the separately supplied references.
    commands.append(shlex.join([PYTHON, str(scoring/"evaluate.py"),
        "--raw-root", str(inputs/"brick"), "--processed-root", str(output/"processed"),
        "--reference", str(scoring/"annotations.json"), "--output", str(output/"evaluation")]))
    launch = ["#!/usr/bin/env bash", "set -euo pipefail", f"cd {shlex.quote(str(snapshot))}",
        "export ROBO_PUEUE_JOB=1", "export OMP_NUM_THREADS=2", "export OPENBLAS_NUM_THREADS=2",
        "export PYTHONDONTWRITEBYTECODE=1", *commands,
        "test -f output/evaluation/evaluation.json",
        "printf '%s' '{\"complete\":true,\"images\":18}' > run_complete.json", ""]
    (snapshot/"launch.sh").write_text("\n".join(launch))
    manifest = {"source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sam3_job": 1673, "source_sam3_provenance": provenance, "runtime": PYTHON,
        "created_utc": stamp,
        "sha256": {str(p.relative_to(snapshot)): digest(p) for p in sorted(snapshot.rglob("*")) if p.is_file()}}
    (snapshot/"manifest.json").write_text(json.dumps(manifest, indent=2)+"\n")
    result = subprocess.run(["pueue", "add", "--label", "robo26-sam3-size-filter",
        shlex.join(["bash", str(snapshot/"launch.sh")])], check=True, capture_output=True, text=True)
    (snapshot/"submission.txt").write_text(result.stdout)
    print("Snapshot:", snapshot)
    print(result.stdout.strip())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Submit an isolated CUDA health check to the default Pueue queue.

The check first reads the driver's recovery action. If recovery requires a
reboot it stops, rather than attempting more CUDA work on the faulted device.
After recovery it checks the driver API, then a PyTorch allocation and kernel.
"""

import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


def run_check(output_dir):
    if os.environ.get("ROBO_PUEUE_CUDA_CHECK") != "1":
        raise SystemExit("Use python3 scripts/check_cuda.py to submit this check to Pueue.")
    result = {"checked_utc": datetime.now(timezone.utc).isoformat(), "python": sys.executable}
    exit_code = 1
    try:
        gpu_info = subprocess.check_output(["nvidia-smi", "-q"], text=True)
        actions = re.findall(r"^\s*GPU Recovery Action\s*:\s*(.+)$", gpu_info, re.MULTILINE)
        result["gpu_recovery_actions"] = actions
        if any("reboot" in action.lower() for action in actions):
            result["status"] = "reboot_required"
            result["error"] = "NVIDIA driver reports GPU Recovery Action: Reboot. Coordinate an OS reboot before retrying."
        elif any(action.strip().lower() not in ("none", "n/a") for action in actions):
            result["status"] = "recovery_required"
            result["error"] = "Resolve the driver's reported recovery action before retrying."
        else:
            cuda = ctypes.CDLL("libcuda.so.1")
            cuda.cuInit.argtypes = [ctypes.c_uint]
            cuda.cuInit.restype = ctypes.c_int
            code = cuda.cuInit(0)
            result["cuInit"] = code
            if code != 0:
                raise RuntimeError(f"cuInit failed with CUDA driver error {code}")
            count = ctypes.c_int()
            cuda.cuDeviceGetCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
            cuda.cuDeviceGetCount.restype = ctypes.c_int
            code = cuda.cuDeviceGetCount(ctypes.byref(count))
            result["cuDeviceGetCount"] = {"code": code, "devices": count.value}
            if code != 0 or count.value < 1:
                raise RuntimeError("CUDA driver did not enumerate a GPU")
            import torch

            result["torch_version"] = torch.__version__
            result["torch_cuda_version"] = torch.version.cuda
            torch.cuda.init()
            value = torch.ones(1, device="cuda") + 1
            torch.cuda.synchronize()
            result["gpu_name"] = torch.cuda.get_device_name(0)
            result["kernel_result"] = value.item()
            if result["kernel_result"] != 2.0:
                raise RuntimeError("CUDA kernel returned an unexpected result")
            result["status"] = "passed"
            exit_code = 0
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
    (output_dir / "cuda_check.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return exit_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path("/home/faps/miniforge3/envs/unitree_sim_env/bin/python"))
    parser.add_argument("--run", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.run:
        return run_check(Path(__file__).resolve().parent)
    source = Path(__file__).resolve()
    root = source.parents[1]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    snapshot = root / "runs" / f"{stamp}-cuda-check"
    snapshot.mkdir(parents=True)
    target = snapshot / source.name
    shutil.copy2(source, target)
    prefix = args.python.resolve().parent.parent
    conda_sh = prefix.parent.parent / "etc/profile.d/conda.sh"
    if not args.python.is_file() or not conda_sh.is_file():
        raise FileNotFoundError("Expected the project's existing Conda runtime and activation script")
    launch = snapshot / "launch.sh"
    launch.write_text("\n".join([
        "#!/usr/bin/env bash", "set -eo pipefail",
        f"source {shlex.quote(str(conda_sh))}",
        f"conda activate {shlex.quote(str(prefix))}",
        "export PYTHONDONTWRITEBYTECODE=1", "export ROBO_PUEUE_CUDA_CHECK=1",
        "exec " + shlex.join([str(args.python), str(target), "--run"]), "",
    ]))
    (snapshot / "manifest.json").write_text(json.dumps({
        "python": str(args.python),
        "sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (target, launch)},
    }, indent=2) + "\n")
    print(f"Snapshot: {snapshot}", flush=True)
    submitted = subprocess.run(["pueue", "add", "--label", "robo26-cuda-check",
                                shlex.join(["bash", str(launch)])], check=True, capture_output=True, text=True)
    print(submitted.stdout.strip())
    (snapshot / "submission.txt").write_text(submitted.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

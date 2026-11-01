"""Small allocated-node inventory. No package import starts Isaac or CUDA."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def command(arguments):
    try:
        p = subprocess.run(arguments, capture_output=True, text=True, timeout=20)
        return {'returncode':p.returncode,'stdout':p.stdout.strip(),'stderr':p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'error':str(error)}


def main():
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('Run this probe only inside its Slurm allocation')
    packages = {}
    for name in ('isaacsim','isaacsim-kernel','isaaclab','torch'):
        try: packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError: packages[name] = None
    selector = os.environ.get('SLURM_JOB_GPUS') or os.environ.get('CUDA_VISIBLE_DEVICES')
    gpu = command(['nvidia-smi','--id='+selector,'--query-gpu=name,driver_version,memory.total',
                   '--format=csv,noheader,nounits']) if selector else {'error':'No allocated GPU selector; refusing an unscoped device query'}
    report = {'schema':'alex-minimal-capability-preflight-v1',
        'slurm_job_id':os.environ['SLURM_JOB_ID'], 'partition':os.environ.get('SLURM_JOB_PARTITION'),
        'requested_budget':{'gpu_type':'a40','gpu_count':1,'walltime_minutes':5,'documented_cpu_share':16,'documented_memory_share_GB':60,'cpu_memory_policy':'Assigned automatically by Slurm from GPU count'},
        'allocated_cpu_count':os.environ.get('SLURM_CPUS_ON_NODE'),
        'allocated_memory_MiB':os.environ.get('SLURM_MEM_PER_NODE'),
        'hostname':platform.node(),'python':sys.version.split()[0],'python_executable':sys.executable,
        'glibc':os.confstr('CS_GNU_LIBC_VERSION'),'gpu_inventory':gpu,
        'apptainer':command(['apptainer','--version']) if shutil.which('apptainer') else None,
        'package_metadata_in_probe_python':packages,
        'isaac_startup':'NOT_TESTED_NO_VERIFIED_MATCHING_RUNTIME',
        'isaac_compatibility_validated':False,'cuda_kernel_tested':False,'scaling_authorized_by_this_result':False,
        'limitations':['GPU inventory is not CUDA, Vulkan or Isaac application validation.',
            'No verified matching Isaac runtime/container was identified; no pull, installation or implicit application startup.',
            'Metadata absence in this Python is not proof of absence from the entire cluster.',
            'Remote hardware cannot correct the current native full-stack contact/load-model failure.'],
        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    Path('result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)
    if gpu.get('returncode') != 0:
        raise RuntimeError('Allocated GPU inventory failed; see result.json')


if __name__ == '__main__':
    main()

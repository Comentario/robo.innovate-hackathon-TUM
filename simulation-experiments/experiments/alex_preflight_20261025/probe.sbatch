#!/bin/bash -l
#SBATCH --job-name=robo26-capability-probe
#SBATCH --partition=a40
#SBATCH --gres=gpu:a40:1
#SBATCH --ntasks=1
#SBATCH --time=00:05:00
#SBATCH --export=NONE
#SBATCH --output=slurm-%j.out
set -euo pipefail
umask 077
unset SLURM_EXPORT_ENV
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
cd "$SLURM_SUBMIT_DIR"
python3 ./probe.py

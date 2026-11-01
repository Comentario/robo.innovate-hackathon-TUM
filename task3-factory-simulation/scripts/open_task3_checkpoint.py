#!/usr/bin/env python3
"""Extract the reviewed Task 3 checkpoint without rerunning the simulation."""
from pathlib import Path
import gzip
import shutil
import argparse

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir', type=Path, default=root / 'artifacts/task3_checkpoint')
args = parser.parse_args()
if args.output_dir.exists():
    parser.error('Choose a new output directory; existing results are preserved.')
args.output_dir.mkdir(parents=True)
for name in ('index.html', 'run.json', 'scene.json'):
    with gzip.open(root / 'task3_checkpoint' / (name + '.gz'), 'rb') as source:
        with (args.output_dir / name).open('wb') as target:
            shutil.copyfileobj(source, target)
shutil.copy2(root / 'task3_checkpoint/comparison.json', args.output_dir / 'comparison.json')
print('Open in your browser: ' + str((args.output_dir / 'index.html').resolve()))
print('Existing evidence extracted. No simulation or KPI recalculation performed.')

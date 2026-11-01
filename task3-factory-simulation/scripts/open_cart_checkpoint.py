#!/usr/bin/env python3
"""Extract the revision 36 offline demo without overwriting existing output."""
import gzip
import shutil
from pathlib import Path
root = Path(__file__).resolve().parents[1]
source = root / 'task3_checkpoint/greenfield_36/index.html.gz'
output = root / 'artifacts/greenfield_36/index.html'
output.parent.mkdir(parents=True, exist_ok=True)
with gzip.open(source, 'rb') as inp, output.open('xb') as out:
    shutil.copyfileobj(inp, out)
print(output)

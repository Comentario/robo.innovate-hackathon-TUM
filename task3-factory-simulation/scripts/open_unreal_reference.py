#!/usr/bin/env python3
"""Extract the Unreal reference revision 30 offline demo without overwriting existing output."""
import gzip
import shutil
from pathlib import Path
root = Path(__file__).resolve().parents[1]
source = root / 'task3_checkpoint/unreal_reference_30/index.html.gz'
output = root / 'artifacts/greenfield_30/index.html'
output.parent.mkdir(parents=True, exist_ok=True)
with gzip.open(source, 'rb') as inp, output.open('xb') as out:
    shutil.copyfileobj(inp, out)
print(output)

for cache in source.parent.glob("*.json.gz"):
    shutil.copy2(cache, output.parent / cache.name)

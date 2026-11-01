#!/usr/bin/env python3
"""Extract the current Greenfield 37 demo and cache, preserving older outputs."""
import argparse,gzip,hashlib,json,shutil
from pathlib import Path
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-dir',type=Path,default=root/'artifacts/greenfield_37')
args=parser.parse_args();source=root/'task3_checkpoint/greenfield_37';meta=json.loads((source/'provenance.json').read_text());folder=args.output_dir;folder.mkdir(parents=True,exist_ok=True);output=folder/'index.html'
if output.exists():
    if hashlib.sha256(output.read_bytes()).hexdigest()!=meta['packaged_html_sha256']:
        parser.error('An older/different index.html exists. Preserve it and select a new --output-dir.')
else:
    with gzip.open(source/'index.html.gz','rb') as inp,output.open('xb') as out:shutil.copyfileobj(inp,out)
if hashlib.sha256(output.read_bytes()).hexdigest()!=meta['packaged_html_sha256']:raise SystemExit('Extracted HTML checksum mismatch')
cache=folder/meta['replay_cache']
if not cache.exists():shutil.copy2(source/meta['replay_cache'],cache)
if hashlib.sha256(cache.read_bytes()).hexdigest()!=meta['replay_sha256']:raise SystemExit('Replay checksum mismatch')
print('Open: '+str(output.resolve()));print('Prepared replay restored; no simulation rerun.')

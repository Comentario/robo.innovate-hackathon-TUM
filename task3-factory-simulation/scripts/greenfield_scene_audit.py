#!/usr/bin/env python3
"""Audit actual exported static scene meshes against complete recorded paths."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from greenfield.interference import audit_scene
p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);p.add_argument('geometry',type=Path);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();result=audit_scene(json.loads(a.run.read_text()),json.loads(a.geometry.read_text()));a.output.write_text(json.dumps(result,indent=2));print({k:v for k,v in result.items() if k!='examples'});raise SystemExit(0 if result['passed'] else 1)

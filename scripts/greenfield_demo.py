#!/usr/bin/env python3
"""Run the independent autonomous greenfield study with local SimPy."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'.deps'/'plant_sim'))
try:
    import simpy
except ModuleNotFoundError:
    raise SystemExit('Install SimPy: python3 -m pip install --target .deps/plant_sim -r plant_sim/requirements.txt')
from greenfield.__main__ import main
if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Run Task 3 with its isolated local dependency directory, if installed."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'.deps'/'plant_sim'))
try:
    import simpy  # noqa: F401
except ModuleNotFoundError:
    raise SystemExit('Install the Task 3 dependency first:\n'
                     'python3 -m pip install --target .deps/plant_sim -r plant_sim/requirements.txt')

from plant_sim.__main__ import main

if __name__ == '__main__':
    raise SystemExit(main())

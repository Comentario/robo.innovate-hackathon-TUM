"""Render the private approximate final workcell with virtual inspection views."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.final_workcell_20261024 import render_core

if __name__ == "__main__":
    render_core.main()

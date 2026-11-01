"""Reuse final static workcell and frozen partial-state geometry adapter."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.partial_disassembly_20261024.render_adapter import prepare_case
from experiments.final_workcell_20261024 import render_core

if __name__ == '__main__':
    render_core.main(case_adapter=prepare_case)

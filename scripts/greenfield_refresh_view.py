#!/usr/bin/env python3
"""Rebuild an offline viewer from existing evidence, without running SimPy."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from greenfield.report import render_view


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, help='Directory containing the existing run.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output_dir.resolve()
    # Load evidence before creating output; malformed/missing input fails without a new run.
    report = json.loads((source / 'run.json').read_text())
    comparison = source / 'comparison.json'
    rows = json.loads(comparison.read_text()) if comparison.exists() else []
    study = [{
        'label': row['scenario'], 'cells': row['cells'],
        'released_good_bph': row['released_good_bph'],
        'formed_good_bph': row['formed_good_bph'], 'status': row['status'],
    } for row in rows[:3]]
    output.mkdir(parents=True, exist_ok=True)
    if source != output:
        shutil.copy2(source / 'run.json', output / 'run.json')
        if comparison.exists():
            shutil.copy2(comparison, output / comparison.name)
        html = source / 'comparison.html'
        if html.exists():
            text = html.read_text()
            text = re.sub(r'href="(scenario_[^"]*)"',
                          lambda match: 'href="' + os.path.relpath(source / match[1], output).replace(os.sep, '/') + '"', text)
            (output / html.name).write_text(text)
    render_view(report, output, study)
    print(f'Viewer rebuilt: {output / "index.html"}')
    print('Existing evidence reused. No simulation, classification or KPI recalculation performed.')


if __name__ == '__main__':
    main()

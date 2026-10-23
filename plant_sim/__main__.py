"""Generate a reproducible process run, evidence and offline English replay."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from .model import Plant
from .viewer import write_viewer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config/plant_demo.json'))
    parser.add_argument('--output-dir', type=Path, default=Path('artifacts/plant_demo'))
    parser.add_argument('--compare', action='store_true', help='Also run stress, mixing, stockout and sensor-timeout scenarios')
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error('Output directory already exists; select a new directory to preserve evidence')
    config = json.loads(args.config.read_text())
    report = Plant(config).run()
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'run.json').write_text(json.dumps(report, indent=2))
    write_viewer(report, args.output_dir/'index.html')
    results = [{'scenario': 'Configured line', 'status': report['status'], **report['kpis']}]
    if args.compare:
        scenarios = [
            ('High rejection', {'defect_rate': 0.45, 'replacement_per_shade': 1000}),
            ('Stratified input', {'input_pattern': 'stratified', 'replacement_per_shade': 1000}),
            ('Stratified with mix exchanges', {'input_pattern': 'stratified', 'mixing_budget_per_layer': 16, 'replacement_per_shade': 1000}),
            ('Two correction robots', {'defect_rate': 0.45, 'correction_robots': 2, 'replacement_per_shade': 1000}),
            ('Imperfect inspection', {'false_accept_rate': 0.25, 'false_reject_rate': 0.03}),
            ('Supply shortage', {'replacement_per_shade': 0}),
            ('Separator end-limit timeout', {'fault': {'station': 'separator', 'pair': 3}}),
        ]
        for index, (name, changes) in enumerate(scenarios):
            c = deepcopy(config)
            c.update(changes)
            r = Plant(c).run()
            folder = args.output_dir/f'scenario_{index+1}'
            folder.mkdir()
            (folder/'run.json').write_text(json.dumps(r, indent=2))
            write_viewer(r, folder/'index.html')
            results.append({'scenario': name, 'status': r['status'], 'link': f'scenario_{index+1}/index.html', **r['kpis']})
        (args.output_dir/'comparison.json').write_text(json.dumps(results, indent=2))
        from .viewer import write_comparison
        write_comparison(results, args.output_dir/'comparison.html')
    print(json.dumps({'status': report['status'], 'kpis': report['kpis'],
                      'viewer': str(args.output_dir/'index.html'), 'scenarios': len(results)}, indent=2))
    return 0 if report['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())

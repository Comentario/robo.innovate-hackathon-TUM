"""Run the offline planning-to-execution contract demo (no robot connection)."""
import argparse
import json
from pathlib import Path
import sys

from . import run_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', default='examples/handoff/inventory.json')
    parser.add_argument('--config', default='examples/handoff/config.json')
    parser.add_argument('--fail-step', type=int, help='Inject a failure before this simulated pick')
    parser.add_argument('--output', default='artifacts/dry_run.json')
    args = parser.parse_args()
    try:
        with open(args.inventory, encoding='utf-8') as source:
            inventory = json.load(source)
        with open(args.config, encoding='utf-8') as source:
            config = json.load(source)
        report = run_demo(inventory, config, fail_step=args.fail_step)
        output = Path(args.output)
        if output.resolve() in (Path(args.inventory).resolve(), Path(args.config).resolve()):
            raise ValueError('output must not overwrite an input file')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    except (OSError, ValueError) as error:
        print(f'demo: {error}', file=sys.stderr)
        return 2
    print('SIMULATION ONLY — no hardware commands or shared stock changes')
    print(f"Status: {report['status']} | Confirmed placements: {len(report['confirmed_placements'])}")
    if report['status'] == 'rejected':
        print('Reason: ' + report['reason'])
    for event in report['events']:
        print(json.dumps(event, ensure_ascii=False))
    print(f'Report: {output}')
    return {'completed': 0, 'rejected': 2, 'stopped': 3}[report['status']]


if __name__ == '__main__':
    sys.exit(main())

"""JSON command line interface."""
import argparse
import json
import sys
from . import make_plan


def main():
    parser = argparse.ArgumentParser(description='Generate a logical brick pallet plan')
    parser.add_argument('inventory')
    parser.add_argument('--rows', type=int, required=True)
    parser.add_argument('--columns', type=int, required=True)
    parser.add_argument('--layers', type=int, default=1)
    parser.add_argument('--ratios', help='JSON category-to-weight object')
    args = parser.parse_args()
    try:
        with open(args.inventory, encoding='utf-8') as source:
            inventory = json.load(source)
        plan = make_plan(inventory, rows=args.rows, columns=args.columns,
                         layers=args.layers,
                         target_ratios=json.loads(args.ratios) if args.ratios else None)
    except (OSError, ValueError) as error:
        print(f'planning: {error}', file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

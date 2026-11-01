"""JSON command line interface."""
import argparse
import json
import sys
from . import make_plan


def main():
    parser = argparse.ArgumentParser(description='Generate a logical brick pallet plan')
    parser.add_argument('inventory')
    parser.add_argument('--config', help='JSON planner configuration')
    parser.add_argument('--rows', type=int)
    parser.add_argument('--columns', type=int)
    parser.add_argument('--layers', type=int)
    parser.add_argument('--ratios', help='JSON category-to-weight object')
    args = parser.parse_args()
    try:
        with open(args.inventory, encoding='utf-8') as source:
            inventory = json.load(source)
        config = {}
        if args.config:
            with open(args.config, encoding='utf-8') as source:
                config = json.load(source)
            if not isinstance(config, dict):
                raise ValueError('config must be an object')
        allowed = {'rows', 'columns', 'layers', 'target_ratios', 'mode',
                   'tone_values', 'shortage_policy'}
        if set(config) - allowed:
            raise ValueError('unknown config keys: ' + ', '.join(sorted(set(config) - allowed)))
        for key in ('rows', 'columns', 'layers'):
            if getattr(args, key) is not None:
                config[key] = getattr(args, key)
        if args.ratios is not None:
            config['target_ratios'] = json.loads(args.ratios)
        if 'rows' not in config or 'columns' not in config:
            raise ValueError('rows and columns are required through config or CLI')
        plan = make_plan(inventory, **config)
    except (OSError, ValueError) as error:
        print(f'planning: {error}', file=sys.stderr)
        return 2
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

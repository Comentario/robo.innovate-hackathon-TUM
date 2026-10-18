"""Generate a self-contained animated browser demo from real Python planner outputs."""
import argparse
import json
from pathlib import Path
import sys

from . import run_demo
from planning.visualize import inventory_from_stock


def build_data(root):
    spec = json.loads((root / 'data/scenarios.json').read_text(encoding='utf-8'))
    inputs = [dict(name=s['name'], description='Synthetic per-brick shades; no face observations.',
                   inventory=inventory_from_stock(s['stock']), face_aware=False,
                   config=dict(spec['shape'], target_ratios=spec['target_ratios'], tone_values=spec['tone_values']))
              for s in spec['scenarios']]
    faces = json.loads((root / 'examples/faces/inventory.json').read_text(encoding='utf-8'))
    face_config = json.loads((root / 'examples/faces/config.json').read_text(encoding='utf-8'))
    face_config['tone_values'] = spec['tone_values']
    inputs.append(dict(name='Different shades on each face',
                       description='All fronts are dark. Allowed back faces unlock the target recipe. Top faces are unobserved.',
                       inventory=faces, face_aware=True, config=face_config))
    locked = json.loads(json.dumps(faces))
    for brick in locked:
        brick['allowed_orientations'] = [dict(id='front_out', visible_face='front')]
    inputs.append(dict(name='Front faces only',
                       description='The same bricks, with back orientations forbidden. Hidden shades cannot satisfy the recipe.',
                       inventory=locked, face_aware=True, config=face_config))
    scenarios = []
    for source in inputs:
        results = {}
        for mode in ('mixed', 'smooth'):
            for shortage in ('reject', 'redistribute'):
                config = dict(source['config'], mode=mode, shortage_policy=shortage)
                kwargs = dict(face_aware=source['face_aware'])
                results[f'{mode}/{shortage}'] = dict(
                    normal=run_demo(source['inventory'], config, **kwargs),
                    failure=run_demo(source['inventory'], config, fail_step=5, **kwargs))
        scenarios.append(dict(name=source['name'], description=source['description'],
                              inventory=source['inventory'], face_aware=source['face_aware'], results=results))
    return dict(schema_version='browser-demo-0.1', scenarios=scenarios)


def render_page(data, web_directory):
    template = (web_directory / 'index.html').read_text(encoding='utf-8')
    css = (web_directory / 'style.css').read_text(encoding='utf-8')
    js = (web_directory / 'app.js').read_text(encoding='utf-8')
    # User-controlled labels must never terminate the embedded JSON script.
    payload = json.dumps(data, ensure_ascii=True).replace('<', '\\u003c').replace('&', '\\u0026')
    return template.replace('/*INLINE_CSS*/', css).replace('/*INLINE_JS*/', js).replace('__DEMO_DATA__', payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/brick_demo.html')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    if output.suffix.lower() != '.html':
        parser.error('--output must end in .html')
    try:
        data = build_data(root)
        page = render_page(data, Path(__file__).with_name('web'))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(page, encoding='utf-8')
    except (OSError, ValueError) as error:
        print(f'browser demo: {error}', file=sys.stderr)
        return 2
    print(f'Open this file in your browser: {output.resolve()}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

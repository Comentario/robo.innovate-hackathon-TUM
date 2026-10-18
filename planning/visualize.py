"""Offline SVG comparison of planning policies using synthetic inventories."""
import argparse
from collections import Counter
from html import escape
import json
import math
from pathlib import Path
import sys

from . import make_plan

PALETTE = {'dark': '#704331', 'medium': '#b77852', 'light': '#e7c8a1'}
TEXT = {'dark': '#ffffff', 'medium': '#ffffff', 'light': '#30271f'}


def inventory_from_stock(stock):
    if not isinstance(stock, dict) or not stock:
        raise ValueError('stock must be a nonempty category-to-count object')
    inventory = []
    for group, count in sorted(stock.items()):
        if not isinstance(group, str) or not group.strip():
            raise ValueError('stock categories must be nonempty strings')
        if type(count) is not int or count < 0:
            raise ValueError('stock counts must be nonnegative integers')
        inventory.extend(dict(id=f'{group}_{i:03}', color_group=group)
                         for i in range(1, count + 1))
    return inventory


def visual_metrics(plan, tone_values):
    """Evaluate both modes on the same scale; retain original planner metrics."""
    grid = {(p['layer'], p['row'], p['column']): p['color_group']
            for p in plan['placements']}
    distances = []
    for (layer, row, column), group in grid.items():
        for previous in ((layer - 1, row, column), (layer, row - 1, column),
                         (layer, row, column - 1)):
            if previous in grid:
                distances.append(abs(tone_values[group] - tone_values[grid[previous]]))
    target = plan['metrics']['target_ratios']
    local = {}
    for layer in range(plan['shape']['layers']):
        groups = [p['color_group'] for p in plan['placements'] if p['layer'] == layer]
        counts = Counter(groups)
        local[str(layer)] = sum(abs(counts[g] / len(groups) - target[g]) for g in target)
    return dict(mean_neighbor_tone_distance=sum(distances) / len(distances) if distances else 0,
                layer_ratio_l1_errors=local)


def compare_scenarios(spec):
    if not isinstance(spec, dict) or not isinstance(spec.get('scenarios'), list) or not spec['scenarios']:
        raise ValueError('spec requires a nonempty scenarios list')
    tones = spec.get('tone_values')
    if not isinstance(tones, dict) or not tones:
        raise ValueError('tone_values must be a nonempty object')
    for group, value in tones.items():
        if not isinstance(group, str) or type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('tone_values must map categories to finite numbers in [0, 1]')
    target = spec.get('target_ratios')
    if target is not None:
        if not isinstance(target, dict) or not target:
            raise ValueError('target_ratios must be a nonempty object')
        if any(not isinstance(g, str) or not g.strip() or type(w) not in (int, float)
               or not math.isfinite(w) or w < 0 for g, w in target.items()):
            raise ValueError('target_ratios requires finite nonnegative weights')
        if not math.isfinite(sum(target.values())) or sum(target.values()) <= 0:
            raise ValueError('target_ratios requires a finite positive sum')
    shape = spec.get('shape')
    if not isinstance(shape, dict) or set(shape) != {'rows', 'columns', 'layers'}:
        raise ValueError('shape requires rows, columns and layers')
    if any(type(value) is not int or value <= 0 for value in shape.values()):
        raise ValueError('shape dimensions must be positive integers')
    scenarios = []
    for scenario in spec['scenarios']:
        if not isinstance(scenario, dict) or not isinstance(scenario.get('name'), str):
            raise ValueError('each scenario requires a name')
        inventory = inventory_from_stock(scenario.get('stock'))
        if set(scenario['stock']) - set(tones):
            raise ValueError('every stock category requires a tone value')
        results = []
        for shortage in ('reject', 'redistribute'):
            for mode in ('mixed', 'smooth'):
                try:
                    plan = make_plan(inventory, **shape, target_ratios=spec.get('target_ratios'),
                                     mode=mode, tone_values=tones, shortage_policy=shortage)
                except ValueError as error:
                    results.append(dict(mode=mode, shortage_policy=shortage, status='rejected', reason=str(error)))
                else:
                    results.append(dict(mode=mode, shortage_policy=shortage, status='planned', plan=plan,
                                        comparison_metrics=visual_metrics(plan, tones)))
        scenarios.append(dict(name=scenario['name'], stock=scenario['stock'], results=results))
    return dict(schema_version='comparison-0.1', shape=shape,
                target_ratios=spec.get('target_ratios'), tone_values=tones, scenarios=scenarios)


def render_svg(report):
    """Render portable SVG with labels, metrics, and every layer for each plan."""
    shape = report['shape']
    cell_w, cell_h = 78, 54
    layer_w = shape['columns'] * cell_w + 22
    panel_w = max(550, layer_w * min(2, shape['layers']) + 24)
    grid_height = math.ceil(shape['layers'] / 2) * (shape['rows'] * cell_h + 42)
    card_h = 155 + grid_height
    section_h = 80 + 2 * (card_h + 16)
    width = 2 * panel_w + 64
    height = 180 + len(report['scenarios']) * section_h
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
             '<title id="title">Comparación de mezclas de ladrillos</title>',
             '<desc id="description">Inventarios sintéticos. Cada escenario compara mixed y smooth con rechazo o redistribución ante faltantes.</desc>',
             '<style>text{font-family:Arial,sans-serif;fill:#243344} .small{font-size:12px} .metric{font-size:13px} .heading{font-size:19px;font-weight:bold}</style>',
             f'<rect width="{width}" height="{height}" fill="#f2f5f8"/>']

    def text(x, y, value, cls='metric', fill=None):
        style = f' style="fill:{fill}"' if fill else ''
        parts.append(f'<text x="{x}" y="{y}" class="{cls}"{style}>{escape(str(value))}</text>')

    text(24, 36, 'Marmon · laboratorio visual de mezclas', 'heading')
    text(24, 61, 'Datos y colores sintéticos · posiciones lógicas · sin simulación física')
    text(24, 83, 'Mixed evita vecinos iguales. Smooth reduce saltos de tono; puede formar zonas o gradientes.')
    text(24, 105, 'La distancia de tono se mide con la misma escala en ambos modos; menor no implica mejor mezcla industrial.')
    legend = ' / '.join(f'{g}={v:g}' for g,v in report['tone_values'].items())
    text(24, 127, 'Escala de tono: ' + legend)
    target = report['target_ratios']
    recipe = ', '.join(f'{g}: {v / sum(target.values()):.1%}' for g,v in target.items()) if target else 'proporción del inventario'
    text(24, 149, 'Receta objetivo: ' + recipe)
    for index, scenario in enumerate(report['scenarios']):
        top = 180 + index * section_h
        text(24, top + 20, scenario['name'], 'heading')
        text(24, top + 43, 'Existencias: ' + ', '.join(f'{g}={n}' for g,n in scenario['stock'].items()))
        for i, result in enumerate(scenario['results']):
            x = 24 + (i % 2) * (panel_w + 16)
            y = top + 60 + (i // 2) * (card_h + 16)
            parts.append(f'<rect x="{x}" y="{y}" width="{panel_w}" height="{card_h}" rx="10" fill="white" stroke="#cdd6df"/>')
            text(x + 14, y + 26, f"{result['mode']} · faltantes: {result['shortage_policy']}", 'heading')
            if result['status'] == 'rejected':
                text(x + 14, y + 58, 'RECHAZADO · no se genera secuencia', fill='#9c2c26')
                text(x + 14, y + 82, result['reason'], 'small')
                continue
            plan = result['plan']
            metrics = plan['metrics']
            text(x + 14, y + 50, 'Selección: ' + ', '.join(f'{g}={n}' for g,n in plan['blend'].items()))
            actual = ', '.join(f'{g}={v:.1%}' for g,v in metrics['actual_ratios'].items())
            text(x + 14, y + 71, 'Proporciones reales: ' + actual, 'small')
            text(x + 14, y + 93, f"Error receta L1: {metrics['ratio_l1_error']:.3f} · vecinos iguales: {metrics['same_tone_neighbors']}/{metrics['neighbor_pairs']}")
            cm = result['comparison_metrics']
            text(x + 14, y + 114, f"Distancia media de tono: {cm['mean_neighbor_tone_distance']:.3f}")
            for layer in range(shape['layers']):
                lx = x + 14 + (layer % 2) * layer_w
                ly = y + 144 + (layer // 2) * (shape['rows'] * cell_h + 42)
                text(lx, ly, f"Capa {layer + 1} · error L1: {cm['layer_ratio_l1_errors'][str(layer)]:.3f}", 'small')
                for p in plan['placements']:
                    if p['layer'] != layer:
                        continue
                    bx = lx + p['column'] * cell_w
                    by = ly + 10 + p['row'] * cell_h
                    group = p['color_group']
                    parts.append(f'<g class="brick"><title>{escape(p["brick_id"])} · paso {p["step"]} · capa {layer + 1}, fila {p["row"] + 1}, columna {p["column"] + 1}</title>')
                    parts.append(f'<rect x="{bx}" y="{by}" width="{cell_w - 4}" height="{cell_h - 4}" rx="3" fill="{PALETTE.get(group, "#dde3e9")}"/>')
                    text(bx + 5, by + 19, group, 'small', TEXT.get(group, '#243344'))
                    text(bx + 5, by + 37, f'#{p["step"]}', 'small', TEXT.get(group, '#243344'))
                    parts.append('</g>')
    parts.append('</svg>')
    return '\n'.join(parts) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenarios', default='data/scenarios.json')
    parser.add_argument('--output', default='artifacts/mixing_comparison.svg')
    args = parser.parse_args()
    output = Path(args.output)
    if output.suffix.lower() != '.svg':
        parser.error('--output must end in .svg')
    try:
        with open(args.scenarios, encoding='utf-8') as source:
            report = compare_scenarios(json.load(source))
        svg = render_svg(report)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(svg, encoding='utf-8')
        output.with_suffix('.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    except (OSError, ValueError) as error:
        print(f'visualize: {error}', file=sys.stderr)
        return 2
    print(f'SVG: {output}\nJSON: {output.with_suffix(".json")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

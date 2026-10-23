"""Offline 3D and schematic replays driven by the SimPy log; no CDN."""
import html
import json
from pathlib import Path


def write_viewer(report, path):
    from .mechanics import compile_mechanics, validate_mechanics
    if report['config']['correction_robots'] != 1:
        raise ValueError('Current 3D workspace supports one correction robot; multi-robot capacity runs need a separate geometric layout')
    path = Path(path)
    folder = Path(__file__).parent
    payload = json.dumps(report, separators=(',', ':')).replace('<', '\\u003c')
    # Preserve the original 2D representation as a secondary diagnostic view.
    template = folder.joinpath('viewer.html').read_text()
    path.with_name('process_2d.html').write_text(template.replace('__RUN_DATA__', payload))
    mechanics = compile_mechanics(report)
    mechanics['audit'] = validate_mechanics(mechanics)
    from .clearance import audit_clearances, structure_boxes
    mechanics['clearance_audit'] = audit_clearances(mechanics)
    mechanics['fixed_solids'] = structure_boxes()
    if not mechanics['clearance_audit']['passed']:
        raise ValueError('Payload crosses fixed equipment; inspect clearance_audit before generating the demo')
    path.with_name('mechanics.json').write_text(json.dumps(mechanics, separators=(',', ':')))
    library = folder.parent/'third_party/three/three.min.js'
    template = folder.joinpath('viewer3d.html').read_text()
    template = template.replace('__THREE_LIBRARY__', library.read_text())
    template = template.replace('__RUN_DATA__', payload)
    template = template.replace('__MECHANICS_DATA__', json.dumps(mechanics, separators=(',', ':')).replace('<', '\\u003c'))
    template = template.replace('__VIEWER_CODE__', folder.joinpath('viewer3d.js').read_text())
    path.write_text(template)


def write_comparison(results, path):
    headings = ['Scenario', 'Status', 'Output bricks/h', 'Conforming bricks/h', 'Bad output', 'Mix exchanges',
                'Mean layer recipe L1', 'Monochrome rows', 'Monochrome columns']
    keys = ['scenario', 'status', 'output_bricks_per_hour', 'conforming_bricks_per_hour', 'bad_output_bricks',
            'mix_exchanges', 'mean_layer_recipe_l1', 'monochrome_rows', 'monochrome_columns']
    rows = []
    for r in results:
        cells = []
        for key in keys:
            value = html.escape(str(r[key]))
            if key == 'scenario':
                value = f'<a href="{html.escape(r.get("link", "index.html"))}">{value}</a>'
            cells.append(f'<td>{value}</td>')
        rows.append('<tr>'+''.join(cells)+'</tr>')
    Path(path).write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Plant scenario comparison</title>
<style>body{font:16px system-ui;background:#10202c;color:#eef6ff;padding:28px}table{border-collapse:collapse}td,th{padding:12px;border:1px solid #526476}a{color:#7bded2}</style>
<h1>Plant scenario comparison</h1><p>SimPy process simulation · unmeasured timing assumptions · same input seed.</p>
<p>Rates include startup and drain. Incomplete runs are censored: do not compare their quality counts or rates as completed batches.
Mixing metrics cover corrected layers, including any still in process. Lower recipe L1 is closer to the assumed recipe.</p>
<table><thead><tr>'''+''.join('<th>'+x+'</th>' for x in headings)+'</tr></thead><tbody>'+''.join(rows)+
        '</tbody></table><p>No measured human baseline. These results are predictions under assumptions, not validated factory improvements.</p></html>')

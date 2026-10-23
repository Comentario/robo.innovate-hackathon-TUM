"""Offline SVG process replay driven by the exact SimPy event log; no CDN."""
import html
import json
from pathlib import Path


def write_viewer(report, path):
    payload = json.dumps(report, separators=(',', ':')).replace('<', '\\u003c')
    template = Path(__file__).with_name('viewer.html').read_text()
    Path(path).write_text(template.replace('__RUN_DATA__', payload))


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

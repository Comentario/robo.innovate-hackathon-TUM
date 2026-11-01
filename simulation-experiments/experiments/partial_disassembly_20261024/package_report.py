"""Package existing scores and saved RGB/overlays; never rerun perception."""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path

import cv2
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--tables', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Report image processing must use default Pueue')
    cv2.setNumThreads(2)
    exp = args.experiment
    ledger = json.loads((exp/'rounds.json').read_text())
    if not ledger['final_method_frozen'] or not ledger['reserved_released']:
        raise RuntimeError('Final report requires selection freeze and reserved release')
    runs = json.loads(args.runs.read_text())
    benchmark = json.loads((exp/'benchmark.json').read_text())
    tables = json.loads((args.tables/'summary.json').read_text())
    final = ledger['final_selected_version']
    out = args.output
    (out/'panels').mkdir(parents=True, exist_ok=True)
    provenance = {'runs': runs, 'round_ledger': ledger, 'benchmark': benchmark,
                  'dataset': json.loads((exp/'dataset.json').read_text()),
                  'calibration': json.loads((exp/'frozen/calibration.json').read_text()),
                  'versions': {}, 'report_versions': {'opencv': cv2.__version__, 'numpy': np.__version__}}
    for version in dict.fromkeys(['B0']+[r['id'] for r in ledger['rounds']]):
        folder = exp/'versions'/version
        provenance['versions'][version] = {
            'files_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(folder.iterdir()) if p.is_file()},
            'config': json.loads((folder/'config.json').read_text()),
            'depth_config': json.loads((folder/'depth_config.json').read_text()),
            'metadata': json.loads((folder/'version.json').read_text())}
    (out/'configuration_manifest.json').write_text(json.dumps(provenance, indent=2)+'\n')
    overall = [r for r in tables['groups'] if r['group_dimension'] == 'overall']
    body = ['<!doctype html><meta charset="utf-8"><title>Partial disassembly benchmark</title>',
            '<style>body{font:16px system-ui;margin:2em;max-width:1450px}table{border-collapse:collapse}td,th{padding:.5em;border:1px solid #bbb}img{max-width:100%}small{color:#555}</style>',
            '<h1>Depth-guided partial disassembly</h1>',
            '<p>Static native-connected simulation snapshots; views scored separately. '
            'Nominal cameras and rendered axial depth. No physical calibration, dynamics, grasping, '
            'combined-view fusion or temporal memory claim. Repeated configurations/views are correlated.</p>',
            '<p>Green = present, yellow = uncertain, blue = missing in the final method. '
            'Cyan boundary = sensor-supported; magenta = inferred. Raw footprints are not confirmed bricks. '
            'Missing end extent remains unknown.</p>',
            '<p><a href="configuration_manifest.json">Configuration / source / job manifest</a> · '
            '<a href="tables/summary.json">All measurements (JSON)</a> · '
            '<a href="tables/groups.csv">Grouped results</a> · '
            '<a href="tables/frames.csv">Per-frame results</a> · '
            '<a href="tables/recoveries.csv">Recovered / lost IDs</a></p>',
            '<table><tr><th>Split</th><th>Version</th><th>Targets</th><th>TP</th><th>Claims</th><th>P / R</th><th>Uncertain / no match</th><th>Correct gaps / refs</th><th>Wrong lower claims</th></tr>']
    for row in overall:
        p = row['present']
        decisions = row['positive_decisions']
        def pct(value):
            return '—' if value is None else f'{100*value:.1f}%'
        values = [row['split'], row['version'], p['positive_references'], p['height_consistent_matches'],
                  p['raw_detections'], f"{pct(p['height_consistent_precision'])} / {pct(p['height_consistent_recall'])}",
                  f"{decisions['uncertain']} / {decisions['no_match']}",
                  f"{row['correct_missing']} / {row['observable_missing_references']}", p['selected_lower_layer']]
        body.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in values)+'</tr>')
    body.append('</table>')
    for case in benchmark['cases']:
        split = case['split']
        selected = {r['version']: Path(r['snapshot']) for r in runs if r['split'] == split}
        first = selected['B0']
        last = selected[final]
        private = json.loads((last/'scoring_only/frames.json').read_text())
        case_frames = [r for r in private if r['case_id'] == case['id'] and r['control_id'] is None]
        rows = []
        for frame in case_frames:
            identity, view = frame['id'], frame['view']
            sources = [last/'inference/inputs/images'/f'{identity}.png',
                       first/'output/predictions'/identity/'overlay.png',
                       last/'output/predictions'/identity/'overlay.png']
            cells = []
            for label, path in zip(['RGB', 'B0', final], sources):
                image = cv2.imread(str(path))
                if image is None:
                    raise FileNotFoundError(path)
                width = 600
                image = cv2.resize(image, (width, round(image.shape[0]*width/image.shape[1])))
                caption = np.full((32, width, 3), 245, np.uint8)
                cv2.putText(caption, f'{view} / {label}', (10, 23), cv2.FONT_HERSHEY_SIMPLEX, .6, (20,20,20), 1)
                cells.append(np.vstack([caption, image]))
            rows.append(np.hstack(cells))
        panel = out/'panels'/f"{case['id']}.jpg"
        if not cv2.imwrite(str(panel), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise OSError(panel)
        body += [f"<h2>{html.escape(case['id'])} — {split}</h2>",
                 f'<a href="panels/{panel.name}"><img src="panels/{panel.name}"></a>']
    body.append('<p>Detailed per-view, gap, phase, color, control and recovered/lost tables are in the supplied JSON/CSV tables. '
                'Every snapshot retains machine-readable predictions, evidence, masks and full-resolution overlays.</p>')
    (out/'index.html').write_text('\n'.join(body)+'\n')
    print(json.dumps({'packaged': str(out), 'panels': len(benchmark['cases']), 'final': final}))


if __name__ == '__main__':
    main()

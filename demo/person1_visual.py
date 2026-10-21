"""Build an offline, linked source-image / inventory / placement-plan review."""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct

from integration import prepare
from integration.person1_intake import convert_inventory

ROOT=Path(__file__).resolve().parents[1]
THRESHOLDS=(0.,.25,.5,.75,.9,.95)


def build_data(inventory,config,image_bytes):
    # The versioned fixture is a PNG. Never stretch a mismatched image to fit boxes.
    if len(image_bytes)<24 or image_bytes[:8]!=b'\x89PNG\r\n\x1a\n' or image_bytes[12:16]!=b'IHDR':
        raise ValueError('source image must be a PNG')
    width,height=struct.unpack('>II',image_bytes[16:24])
    base,base_audit=convert_inventory(inventory,min_score=0.)
    if inventory['image_size_px']!={'width':width,'height':height}:raise ValueError('source image dimensions do not match inventory')
    byid={b['id']:b for b in inventory['bricks']}
    scenarios=[]
    for threshold in THRESHOLDS:
        # Preserve existing geometry/unknown exclusions, then apply the score gate.
        excluded=deepcopy(base_audit['excluded'])
        for row in excluded:
            if byid[row['id']]['color_score']<threshold:row['reasons'].append('below_score_threshold')
        excluded += [dict(id=b['id'],reasons=['below_score_threshold']) for b in base['items'] if b['score']<threshold]
        accepted=[b['id'] for b in base['items'] if b['score']>=threshold]
        row=dict(threshold=threshold,accepted_ids=accepted,excluded=excluded,plan=None,error=None)
        try:
            snapshot,audit=convert_inventory(inventory,min_score=threshold)
            _,row['plan'],_=prepare(snapshot,config)
        except ValueError as exc:row['error']=str(exc)
        scenarios.append(row)
    return dict(image_id=inventory['image_id'],image_size_px=inventory['image_size_px'],
                inventory_sha256=base['producer']['inventory_sha256'],image_sha256=hashlib.sha256(image_bytes).hexdigest(),
                bricks=deepcopy(inventory['bricks']),color_estimation=deepcopy(inventory['color_estimation']),
                config=deepcopy(config),scenarios=scenarios,default_threshold=.5,
                attribution='Bricks Detection Dataset — Dominik Štursa, Petr Doležel, Daniel Honc, Vítek Rais, Tomáš Novák; University of Pardubice. CC BY 4.0. DOI: 10.5281/zenodo.18952529. Image 34c1881b-image_205.png, unchanged.')


def render(data,image_bytes):
    assets=Path(__file__).with_name('person1_web')
    payload=json.dumps(data,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    return ((assets/'index.html').read_text()
            .replace('/*INLINE_STYLE*/',(assets/'style.css').read_text())
            .replace('/*DATA*/',payload)
            .replace('/*IMAGE*/','data:image/png;base64,'+base64.b64encode(image_bytes).decode())
            .replace('/*INLINE_SCRIPT*/',(assets/'app.js').read_text()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=Path('artifacts/person1_visual'))
    args=parser.parse_args()
    try:
        fixture=ROOT/'examples/person1'
        inventory=json.loads((fixture/'inventory_with_color.json').read_text())
        config=json.loads((fixture/'config.json').read_text())
        image=(fixture/'bricks_70.png').read_bytes()
        data=build_data(inventory,config,image)
        page=render(data,image)
        args.output_dir.mkdir(parents=True,exist_ok=False)
        (args.output_dir/'index.html').write_text(page,encoding='utf-8')
        (args.output_dir/'review.json').write_text(json.dumps(data,indent=2)+'\n')
        default=next(s for s in data['scenarios'] if s['threshold']==data['default_threshold'])
        print(f"Source: {len(data['bricks'])} | Accepted: {len(default['accepted_ids'])} | Planned: {len(default['plan']['placements']) if default['plan'] else 0}")
        print(f"Open: {(args.output_dir/'index.html').resolve()}")
    except (OSError,ValueError,KeyError) as exc:parser.exit(2,f'Visual review refused: {exc}\n')


if __name__=='__main__':main()

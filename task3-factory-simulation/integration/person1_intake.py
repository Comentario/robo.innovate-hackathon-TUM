"""Plan-only intake for Person 1's relative CIELAB inventory; no OpenCV required."""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
from html import escape
import json
import math
from pathlib import Path
from .intake import normalize_snapshot


def number(value):
    return type(value) in (int,float) and math.isfinite(value)


def convert_inventory(value,*,min_score):
    if not number(min_score) or not 0<=min_score<=1:raise ValueError('min_score must be in [0,1]')
    if not isinstance(value,dict) or value.get('schema_version')!='0.2' or value.get('processing_status')!='color_estimated':
        raise ValueError('expected Person 1 color_estimated inventory schema 0.2')
    image=value.get('image_id');size=value.get('image_size_px',{});est=value.get('color_estimation',{})
    if not isinstance(image,str) or not image.strip():raise ValueError('missing image_id')
    if not isinstance(size,dict) or any(type(size.get(k)) is not int or size[k]<=0 for k in ('width','height')):raise ValueError('invalid image size')
    if not isinstance(est,dict) or est.get('status')!='accepted' or est.get('method')!='relative_cielab_kmeans_v0.1':raise ValueError('relative color estimation must be accepted')
    k=est.get('selected_k');centers=est.get('group_centers_lab')
    if type(k) is not int or k not in (1,2,3) or not isinstance(centers,list) or len(centers)!=k:raise ValueError('invalid group count/centers')
    for center in centers:
        if not isinstance(center,list) or len(center)!=3 or not all(number(x) for x in center) or not 0<=center[0]<=100:raise ValueError('invalid standard Lab center')
    if any(a[0]>b[0] for a,b in zip(centers,centers[1:])):raise ValueError('centers must be ordered by lightness')
    names=['uniform'] if k==1 else [f'color_group_{i+1}' for i in range(k)]
    bricks=value.get('bricks')
    if not isinstance(bricks,list) or not bricks:raise ValueError('missing bricks')
    items=[];excluded=[];seen=set()
    for brick in bricks:
        if not isinstance(brick,dict):raise ValueError('brick must be an object')
        bid=brick.get('id');group=brick.get('color_group');score=brick.get('color_score');box=brick.get('bbox_px');center=brick.get('center_px')
        if not isinstance(bid,str) or not bid.strip() or bid in seen:raise ValueError('missing/duplicate brick ID')
        seen.add(bid)
        if not isinstance(box,dict) or any(not number(box.get(key)) for key in ('x','y','width','height')):raise ValueError('invalid bbox')
        if box['x']<0 or box['y']<0 or box['width']<=0 or box['height']<=0 or box['x']+box['width']>size['width'] or box['y']+box['height']>size['height']:raise ValueError('bbox outside image')
        if not isinstance(center,dict) or any(not number(center.get(key)) for key in ('x','y')) or not box['x']<=center['x']<=box['x']+box['width'] or not box['y']<=center['y']<=box['y']+box['height']:raise ValueError('invalid pixel center')
        if not number(score) or not 0<=score<=1:raise ValueError('invalid heuristic color score')
        if group not in names+['unknown']:raise ValueError('label does not match relative centers')
        for flag in ('eligible_for_color','is_partial','possible_merge'):
            if flag in brick and type(brick[flag]) is not bool:raise ValueError('detection flags must be boolean')
        reasons=[]
        if not brick.get('eligible_for_color',True) or brick.get('is_partial',False) or brick.get('possible_merge',False):reasons.append('ineligible_geometry')
        if group=='unknown':reasons.append('unknown_color')
        if score<min_score:reasons.append('below_score_threshold')
        if reasons:excluded.append(dict(id=bid,reasons=reasons));continue
        items.append(dict(id=bid,color_group=group,score=score,bbox_px=deepcopy(box),center_px=deepcopy(center)))
    if not items:raise ValueError('no eligible bricks after filtering')
    fingerprint=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    snapshot=normalize_snapshot(dict(schema_version='inventory-snapshot-0.1',snapshot_id=f'person1:{image}:{fingerprint[:16]}:{min_score:g}',source='perception',face_aware=False,items=items,
        producer=dict(image_id=image,inventory_sha256=fingerprint,color_estimation=deepcopy(est),id_scope='single_image',min_score=min_score)))
    audit=dict(input_count=len(bricks),accepted_count=len(items),counts=dict(Counter(b['color_group'] for b in items)),excluded=excluded,
               min_score=min_score,score_meaning='heuristic; not a calibrated probability',execution_ready=False,
               limitations=['No metric source poses','No observed face identity','IDs are spatial and image-local','Relative groups must not be equated across captures'])
    return snapshot,audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inventory',type=Path)
    parser.add_argument('--min-score',type=float,required=True,help='explicit team heuristic, not calibrated probability')
    parser.add_argument('--config',type=Path,required=True,help='recipe using the actual relative group names')
    parser.add_argument('--output-dir',type=Path,required=True,help='new directory, never overwrite a previous intake')
    args=parser.parse_args()
    from . import prepare
    try:
        snapshot,audit=convert_inventory(json.loads(args.inventory.read_text()),min_score=args.min_score)
        config=json.loads(args.config.read_text())
        _,plan,_=prepare(snapshot,config)
        args.output_dir.mkdir(parents=True,exist_ok=False)
        for name,value in [('snapshot',snapshot),('audit',audit),('plan',plan)]:
            (args.output_dir/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
        cards=''.join('<div class="brick"><b>'+escape(p['brick_id'])+'</b><br>'+escape(p['color_group'])+f'<br>Layer {p["layer"]+1}, row {p["row"]+1}, column {p["column"]+1}</div>' for p in plan['placements'])
        (args.output_dir/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Person 1 intake review</title><style>body{font:18px sans-serif;background:#18242a;color:#eee;margin:40px}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.brick{padding:18px;border:1px solid #789;border-radius:8px}pre{white-space:pre-wrap}</style><h1>Perception to planning</h1><p>Offline dataset detections. Plan only: no metric pick poses or observed face identity.</p><p>Labels are scene-relative CIELAB groups, not absolute dark/medium/light classes. Colors are not reconstructed.</p><pre>'+escape(json.dumps(audit,indent=2))+'</pre><h2>Provisional placement plan</h2><p>The recipe and score threshold are explicit team assumptions.</p><div class="grid">'+cards+'</div></html>')
        print(f'Accepted: {audit["accepted_count"]}/{audit["input_count"]}. Planned: {len(plan["placements"])}. Plan only. Review: {args.output_dir/"index.html"}')
    except (ValueError,TypeError,KeyError,OSError) as error:parser.exit(2,f'Intake refused: {error}\n')


if __name__=='__main__':main()

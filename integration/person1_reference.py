"""Compare operator image annotations with a pinned perception inventory; no automatic calibration."""
import argparse
import hashlib
from html import escape
import json
import struct
from pathlib import Path

from .person1_intake import convert_inventory
from . import prepare

SCHEMA='person1-reference-review-0.1'
THRESHOLDS=(0.,.25,.5,.75,.9,.95)


def identity(inventory,image_bytes):
    snapshot,_=convert_inventory(inventory,min_score=0.)
    if len(image_bytes)<24 or image_bytes[:8]!=b'\x89PNG\r\n\x1a\n' or image_bytes[12:16]!=b'IHDR':raise ValueError('expected PNG source image')
    width,height=struct.unpack('>II',image_bytes[16:24])
    if inventory['image_size_px']!={'width':width,'height':height}:raise ValueError('image dimensions do not match inventory')
    return dict(image_id=inventory['image_id'],inventory_sha256=snapshot['producer']['inventory_sha256'],image_sha256=hashlib.sha256(image_bytes).hexdigest())


def template(inventory,image_bytes):
    names=['uniform'] if inventory['color_estimation']['selected_k']==1 else [f'color_group_{i+1}' for i in range(inventory['color_estimation']['selected_k'])]
    return dict(schema_version=SCHEMA,**identity(inventory,image_bytes),reference_kind='operator_image_review',reviewer='',group_definitions=dict.fromkeys(names,''),annotations=[],predictions_visible_during_session=None)


def evaluate(inventory,image_bytes,review,config):
    expected=template(inventory,image_bytes)
    if not isinstance(review,dict) or review.get('schema_version')!=SCHEMA:raise ValueError('expected '+SCHEMA)
    for key in ('image_id','inventory_sha256','image_sha256','reference_kind'):
        if review.get(key)!=expected[key]:raise ValueError('reference does not match '+key)
    reviewer=review.get('reviewer');definitions=review.get('group_definitions');annotations=review.get('annotations')
    if not isinstance(reviewer,str) or not isinstance(definitions,dict) or set(definitions)!=set(expected['group_definitions']) or any(not isinstance(v,str) for v in definitions.values()):raise ValueError('invalid reviewer/group definitions')
    exposure=review.get('predictions_visible_during_session')
    if exposure is not None and type(exposure) is not bool:raise ValueError('invalid prediction exposure metadata')
    if not isinstance(annotations,list):raise ValueError('annotations must be a list')
    byid={b['id']:b for b in inventory['bricks']};labels={};uncertain=[];seen=set()
    for row in annotations:
        if not isinstance(row,dict):raise ValueError('annotation must be an object')
        bid=row.get('id');label=row.get('reference_group');note=row.get('note','')
        if not isinstance(bid,str) or bid not in byid or bid in seen:raise ValueError('unknown/duplicate annotation ID')
        if not isinstance(label,str) or label not in list(definitions)+['uncertain'] or not isinstance(note,str):raise ValueError('invalid reference group/note')
        seen.add(bid)
        if label=='uncertain':uncertain.append(bid)
        else:labels[bid]=label
    if annotations and (not reviewer.strip() or any(not v.strip() for v in definitions.values())):raise ValueError('annotations require reviewer and explicit definitions for every group')
    base,_=convert_inventory(inventory,min_score=0.)
    eligible={b['id'] for b in base['items']}
    confusion={group:dict.fromkeys(list(definitions)+['unknown'],0) for group in definitions}
    for bid,label in labels.items():confusion[label][byid[bid]['color_group']]+=1
    rows=[]
    for threshold in THRESHOLDS:
        accepted={bid for bid in eligible if byid[bid]['color_score']>=threshold}
        measured=set(labels)&accepted
        agree=sum(byid[bid]['color_group']==labels[bid] for bid in measured)
        disagreed=[bid for bid in sorted(measured) if byid[bid]['color_group']!=labels[bid]]
        discarded=set(labels)-accepted
        discarded_agree=sum(byid[bid]['color_group']==labels[bid] for bid in discarded)
        plan=None;error=None
        try:
            snapshot,_=convert_inventory(inventory,min_score=threshold)
            _,plan,_=prepare(snapshot,config)
        except ValueError as exc:error=str(exc)
        rows.append(dict(threshold=threshold,accepted_count=len(accepted),reviewed_accepted=len(measured),unreviewed_or_uncertain_accepted=len(accepted)-len(measured),agreement_count=agree,disagreement_count=len(disagreed),disagreement_ids=disagreed,
                         agreement_fraction=agree/len(measured) if measured else None,reviewed_discarded=len(discarded),discarded_agreement_count=discarded_agree,discarded_disagreement_count=len(discarded)-discarded_agree,plan_feasible=plan is not None,plan_issue=error))
    return dict(schema_version='person1-reference-evaluation-0.1',reference_sha256=hashlib.sha256(json.dumps(review,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),**identity(inventory,image_bytes),status='awaiting_reference_labels' if not labels else 'operator_review_complete' if len(labels)==len(byid) else 'partial_operator_review',
                reference_kind='operator_image_review',reviewer=reviewer,group_definitions=definitions,predictions_visible_during_session=exposure,
                total=len(byid),classified=len(labels),uncertain_ids=uncertain,unreviewed_ids=sorted(set(byid)-seen),coverage=len(labels)/len(byid),confusion=confusion,
                thresholds=rows,threshold_validated=False,recommended_threshold=None,physical_validation=False,
                limitations=['Agreement with operator image labels is not measured physical accuracy.','Partial or selected annotations may be biased; show all denominators.','Do not select and validate a threshold on the same image.','Use independently reviewed images and fixed group criteria before calibrating.'])


def render_report(result):
    rows=''.join('<tr>'+''.join('<td>'+escape(str(row[key]))+'</td>' for key in ('threshold','accepted_count','reviewed_accepted','agreement_count','disagreement_count','unreviewed_or_uncertain_accepted','discarded_agreement_count','plan_feasible'))+'</tr>' for row in result['thresholds'])
    return '<!doctype html><html lang="en"><meta charset="utf-8"><title>Operator reference review</title><style>body{font:17px system-ui;background:#142128;color:#eef;margin:40px}td,th{padding:10px;border:1px solid #456}table{border-collapse:collapse}pre{white-space:pre-wrap}</style><h1>Operator reference review</h1><p>'+escape(result['status'])+f' · Classified {result["classified"]}/{result["total"]}</p><p>No threshold has been validated or automatically recommended. This measures agreement with operator image labels, not physical accuracy.</p><table><tr><th>Threshold</th><th>Accepted</th><th>Reviewed accepted</th><th>Agree</th><th>Disagree</th><th>Accepted without a definite label</th><th>Discarded despite agreement</th><th>Recipe feasible</th></tr>'+rows+'</table><h2>Coverage, confusion and limitations</h2><pre>'+escape(json.dumps(result,indent=2))+'</pre></html>'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['template','evaluate'])
    parser.add_argument('--inventory',type=Path,default=Path('examples/person1/inventory_with_color.json'))
    parser.add_argument('--image',type=Path,default=Path('examples/person1/bricks_70.png'))
    parser.add_argument('--config',type=Path,default=Path('examples/person1/config.json'))
    parser.add_argument('--annotations',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    try:
        inventory=json.loads(args.inventory.read_text());image=args.image.read_bytes()
        if args.command=='template':value=template(inventory,image);name='reference'
        else:
            if args.annotations is None:raise ValueError('evaluate requires --annotations')
            value=evaluate(inventory,image,json.loads(args.annotations.read_text()),json.loads(args.config.read_text()));name='evaluation'
        args.output_dir.mkdir(parents=True,exist_ok=False)
        (args.output_dir/f'{name}.json').write_text(json.dumps(value,indent=2)+'\n')
        if args.command=='evaluate':
            (args.output_dir/'index.html').write_text(render_report(value))
            print(f'{value["status"]}: {value["classified"]}/{value["total"]} classified. No threshold validated.')
        print(args.output_dir.resolve())
    except (OSError,ValueError,KeyError,TypeError) as exc:parser.exit(2,f'Reference review refused: {exc}\n')


if __name__=='__main__':main()

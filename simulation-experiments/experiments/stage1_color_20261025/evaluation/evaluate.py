"""JSON-only independent score for one frozen saved-simulation color benchmark."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import time
HERE=Path(__file__).resolve().parent
# Frozen from the five HUMAN RGB rectangles and small projected-reference JSON.
# This evaluator-only crosswalk never supplies shader/material RGB to inference.
PATCHES={
 'tan':('brick_9_5_0','tan',[444,300,470,360]),
 'brown':('brick_9_4_4','brown',[516,595,543,655]),
 'dark_red':('brick_9_2_0','dark_red',[663,302,690,360]),
 'bright_red':('brick_9_5_2','reject_4211201',[444,448,470,505]),
 'ochre':('brick_9_5_1','reject_6135191',[444,377,470,432])}
GT_LABEL={value[1]:label for label,value in PATCHES.items()}
EXCLUDED={value[0] for value in PATCHES.values()}

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def group(identity):return 'development' if int(hashlib.sha256(identity.encode()).hexdigest(),16)%2==0 else 'reserved'
def fraction(n,d):return n/d if d else None
def pin_prefix(source_snapshot):return 'runs/'+Path(source_snapshot).name

def inside(point,polygon):
    x,y=point;cross=[(b[0]-a[0])*(y-a[1])-(b[1]-a[1])*(x-a[0]) for a,b in zip(polygon,polygon[1:]+polygon[:1])]
    return bool(cross) and (all(c>=-1e-8 for c in cross) or all(c<=1e-8 for c in cross))

def bind_patches(patches,reference,inventory):
    if {p['label'] for p in patches}!=set(PATCHES) or len(patches)!=5:raise ValueError('Five frozen human labels required')
    records={r['id']:r for r in inventory['records']};bindings=[]
    for patch in patches:
        label=patch['label'];identity,color,box=PATCHES[label]
        if patch['frame_id']!='f000' or patch['pixel_xyxy']!=box:raise ValueError('Frozen human reference rectangle changed')
        x0,y0,x1,y1=box;corners=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]
        candidates=[instance['id'] for instance in reference['instances'] if instance['layer']==reference['current_layer'] and instance['role']=='exposed_top' and all(inside(p,instance['polygon']) for p in corners)]
        if candidates!=[identity] or records[identity]['color']!=color:raise ValueError('Human rectangle/GT-key crosswalk is ambiguous or changed')
        bindings.append({'human_label':label,'reference_id':identity,'truth_color_key':color,'exclude_all_frames':True})
    return bindings

def known_evidence(row,settings):
    e=row.get('evidence',{});distances=e.get('distances',{});numbers=[e.get('valid_pixels'),e.get('valid_fraction'),e.get('margin'),e.get('pixel_agreement'),distances.get(row.get('label'))]
    return all(isinstance(x,(int,float)) and math.isfinite(x) for x in numbers) and e['valid_pixels']>=settings['minimum_valid_pixels'] and e['valid_fraction']>=settings['minimum_valid_fraction'] and set(distances)==set(PATCHES) and e.get('nearest_label')==row['label'] and distances[row['label']]<=settings['maximum_delta_e'] and e['margin']>=settings['minimum_runner_up_gap'] and e['pixel_agreement']>=settings['minimum_pixel_agreement']

def score(visible,calls):
    correct=[c for c in calls if c['status']=='correct'];wrong=[c for c in calls if c['status']=='wrong'];unknown=[c for c in calls if c['status']=='unknown'];known=correct+wrong
    classes={};confusion={}
    for label in PATCHES:
        truth=[r for r in visible if r['truth_label']==label];eligible=[c for c in calls if c['truth_label']==label];right=[c for c in correct if c['truth_label']==label];claimed=[c for c in known if c['predicted_label']==label]
        classes[label]={'visible_observations':len(truth),'visible_unique_objects':len({r['reference_id'] for r in truth}),'eligible_present_observations':len(eligible),'correct':len(right),'correct_unique_objects':len({r['reference_id'] for r in right}),'known':sum(c['status']!='unknown' for c in eligible),'unknown':sum(c['status']=='unknown' for c in eligible),'precision':fraction(sum(c['truth_label']==label for c in claimed),len(claimed)),'correct_color_recall_all_visible':fraction(len(right),len(truth)),'validated':bool(right)}
        confusion[label]=dict(Counter(c['predicted_label'] if c['status']!='unknown' else 'UNKNOWN' for c in eligible))
    available=[label for label,row in classes.items() if row['visible_observations']]
    return {'all_visible_observations':len(visible),'visible_unique_objects':len({r['reference_id'] for r in visible}),'eligible_present_observations':len(calls),'eligible_present_unique_objects':len({c['reference_id'] for c in calls}),'known':len(known),'correct':len(correct),'wrong':len(wrong),'unknown':len(unknown),'known_label_precision':fraction(len(correct),len(known)),'color_coverage_eligible_present':fraction(len(known),len(calls)),'correct_color_recall_eligible_present':fraction(len(correct),len(calls)),'correct_color_recall_all_visible':fraction(len(correct),len(visible)),'per_label':classes,'confusion':confusion,'available_labels':available,'unvalidated_labels':[label for label in PATCHES if not classes[label]['validated']],'all_available_labels_validated':bool(available) and all(classes[label]['validated'] for label in available)}

def audit(args):
    protocol=read(HERE.parent/'protocol.json');settings=read(HERE.parent/'settings.json');patches=read(HERE.parent/'reference_patches.json')
    public=read(args.inputs/'frames.json');private={r['id']:r for r in read(args.private/'frames.json')};refs=read(args.private/'references.json');existing=read(args.private/'existing_stage1_evaluation.json');observations={r['frame_id']:r for r in existing['observations']}
    checks={};checks['frozen_frame_inventory']=[r['id'] for r in public]==protocol['frame_ids'] and len({r['id'] for r in public})==len(public)
    checks['final_first_no_postscore_tuning']=protocol['improvements_authorized_after_results'] is False
    base=pin_prefix(protocol['source_snapshot']);frozen=protocol['frozen_sources_sha256']
    pins=[(args.inputs/'calibration.json',base+'/sensors/calibration.json'),(args.private/'frames.json',base+'/private/frames.json'),(args.private/'references.json',base+'/evaluation/references.json'),(args.private/'existing_stage1_evaluation.json',base+'/evaluation/evaluation.json')]
    inventories={}
    for case in ['I_mix','H_mix','E_mix']:
        path=args.private/('inventory_'+case+'.json');pins.append((path,base+'/private/truth/'+case+'/evaluation_truth/active_bricks.json'));inventories[case]=read(path)
    for frame in public:
        identity=frame['id']
        for field,original in [('rgb','rgb.png'),('depth','depth.npy')]:pins.append((args.inputs/frame[field],base+'/sensors/sensors/'+identity+'/'+original))
        pins.append((args.inputs/frame['candidates'],base+'/inference/'+identity+'/candidates.json'))
    checks['frozen_saved_inputs']=all(sha(path)==frozen[key] for path,key in pins)
    bindings=bind_patches(patches,refs['f000'],inventories['I_mix']);checks['human_reference_binding']=True
    truth={case:{r['id']:r['color'] for r in inventory['records']} for case,inventory in inventories.items()}
    checks['reference_crosswalk_consistent_all_states']=all(truth[case].get(identity)==key for case in truth for identity,key,_ in PATCHES.values())
    complete=read(args.predictions/'complete.json');checks['classifier_completed_fixed_sources']=complete['completed'] is True and complete['settings_sha256']==sha(HERE.parent/'settings.json') and complete['reference_patches_sha256']==sha(HERE.parent/'reference_patches.json')
    prototypes=read(args.predictions/'prototypes.json');checks['prototype_label_contract']=set(prototypes['labels'])==set(PATCHES)
    checks['prototypes_ready']=prototypes['ready'] is True and all(row['valid'] is True and isinstance(row.get('median_lab'),list) and len(row['median_lab'])==3 and all(isinstance(x,(int,float)) and math.isfinite(x) for x in row['median_lab']) for row in prototypes['labels'].values())
    visible=[];calls=[];unverified=[];excluded=[];contracts=[];sources=[];invalid_known=0
    for frame in public:
        fid=frame['id'];mapping=private[fid];packet=read(args.inputs/frame['candidates']);prediction=read(args.predictions/(fid+'.json'));candidates={c['candidate_id']:c for c in packet['candidates']};entries=prediction['classifications'];byid={c['candidate_id']:c for c in entries}
        valid=packet['frame_id']==prediction['frame_id']==fid and len(candidates)==len(packet['candidates']) and len(byid)==len(entries) and set(candidates)==set(byid)
        checks[fid+'_exact_candidate_frame_join']=valid
        if not valid:raise ValueError('Missing/duplicate/extra classification joins: '+fid)
        case=mapping['case_id'];control=mapping.get('control_id') is not None
        if not control:
            row=observations[fid];matches={m['detection_id']:m['reference_id'] for m in row['present']['matches']};eligible={(m['candidate_id'],m['reference_id']) for m in row['metric_eligibility']['checks'] if m['eligible']}
            checks[fid+'_one_to_one_scored_association']=len(matches)==len(row['present']['matches']) and len(set(matches.values()))==len(matches)
            for ref in refs[fid]['instances']:
                if ref['role']=='exposed_top' and ref['id'] not in EXCLUDED:
                    key=truth[case][ref['id']]
                    if key not in GT_LABEL:raise ValueError('Unmapped truth color; no online learning allowed')
                    visible.append({'frame_id':fid,'view':mapping['view'],'case_id':case,'reference_id':ref['id'],'split':group(ref['id']),'truth_label':GT_LABEL[key]})
        else:matches={};eligible=set()
        for identity,candidate in candidates.items():
            row=byid[identity];known=row['decision']=='known';legal=row['decision'] in ['known','unknown'] and row['frame_id']==fid and row['source_decision']==candidate['decision'] and isinstance(row.get('reasons'),list) and ((known and row['label'] in PATCHES and not row['reasons']) or (not known and row['label'] is None))
            if known:legal=legal and candidate['decision']=='present' and known_evidence(row,settings)
            contracts.append(legal)
            sources.append({'frame_id':fid,'source_decision':candidate['decision'],'color_decision':row['decision']})
            if control:
                invalid_known+=known;continue
            reference=matches.get(identity);verified=reference is not None and (identity,reference) in eligible
            if not verified:
                if known:unverified.append({'frame_id':fid,'candidate_id':identity,'source_decision':candidate['decision'],'label':row['label'],'reason':'No frozen eligible one-to-one PRESENT association'})
                continue
            actual=GT_LABEL[truth[case][reference]];status='unknown' if not known else 'correct' if row['label']==actual else 'wrong'
            record={'frame_id':fid,'view':mapping['view'],'case_id':case,'candidate_id':identity,'reference_id':reference,'split':group(reference),'truth_label':actual,'predicted_label':row['label'],'status':status,'reasons':row['reasons']}
            if reference in EXCLUDED:excluded.append(record)
            else:calls.append(record)
    checks['all_output_contracts']=all(contracts);checks['no_unverified_confident_calls']=not unverified;checks['invalid_top_no_confident_color']=invalid_known==0
    negative=read(args.predictions/'negative_mixed.json');e=negative['evidence'];color_reasons={'outside_reference_distance','ambiguous_reference_margin','mixed_or_inconsistent_pixels'}
    tested=negative['source_decision']=='present' and e.get('nearest_label') in PATCHES and set(e.get('distances',{}))==set(PATCHES) and e.get('valid_pixels',0)>=settings['minimum_valid_pixels'] and e.get('valid_fraction',0)>=settings['minimum_valid_fraction']
    checks['mixed_present_color_gate_exercised']=bool(tested)
    checks['mixed_control_abstains_on_color']=negative['frame_id']==protocol['negative_control']['frame_id'] and negative['candidate_id']==protocol['negative_control']['candidate_id'] and negative['decision']=='unknown' and negative['label'] is None and bool(set(negative['reasons'])&color_reasons) and 'candidate_not_present' not in negative['reasons']
    overall=score(visible,calls);overall['unverified_confident_calls']=len(unverified);overall['invalid_control_confident_calls']=invalid_known;overall['association_aware_confident_precision']=fraction(overall['correct'],overall['known']+len(unverified)+invalid_known);overall['precision_scope']='known_label_precision is conditional on eligible one-to-one associations; association_aware_confident_precision includes unverified/control confident calls in its denominator';checks['no_wrong_nonreference_confident_labels']=overall['wrong']==0;checks['each_available_color_correct_nonreference']=overall['all_available_labels_validated']
    bysplit={name:score([r for r in visible if r['split']==name],[r for r in calls if r['split']==name]) for name in ['development','reserved']}
    byview={name:score([r for r in visible if r['view']==name],[r for r in calls if r['view']==name]) for name in sorted({r['view'] for r in visible})}
    baseline=score(visible,[{**c,'status':'unknown','predicted_label':None} for c in calls])
    return {'checks':checks,'gate_passed':all(checks.values()),'summary':overall,'by_split':bysplit,'by_view':byview,'baseline_all_UNKNOWN':baseline,'reference_bindings':bindings,'excluded_calibration_observations':excluded,'calibration_ids_excluded_all_frames':sorted(EXCLUDED),'observations':calls,'unverified_confident_calls':unverified,'frozen_R3_and_color_decisions':dict(Counter(r['source_decision']+'/'+r['color_decision'] for r in sources)),'by_frame_source_color_counts':{fid:dict(Counter(r['source_decision']+'/'+r['color_decision'] for r in sources if r['frame_id']==fid)) for fid in protocol['frame_ids']},'mixed_control':{'color_evidence_eligible':tested,**negative},'invalid_top_confident_calls':invalid_known,'prototypes_ready':prototypes['ready'],'scope':protocol['acceptance']['scope'],'limitations':protocol['limitations'],'protocol_sha256':sha(HERE.parent/'protocol.json'),'source_sha256':sha(Path(__file__))}

def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    for key in ['inputs','private','predictions','output']:parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    started=time.monotonic();result={'gate_passed':False}
    try:result.update(audit(args));result['status']='scored_complete'
    except Exception as error:result.update(status='STOP',error=repr(error))
    result['audit_seconds']=time.monotonic()-started;args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (args.output/'complete.json').write_text(json.dumps({'completed':True,'gate_passed':result['gate_passed'],'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')
    print(json.dumps({'gate_passed':result['gate_passed'],'status':result['status']}))

if __name__=='__main__':main()

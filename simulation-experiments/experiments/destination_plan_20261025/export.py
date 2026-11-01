"""Export nominal destination references; no robot/simulator APIs."""
import argparse
import csv
import hashlib
import itertools
import json
import os
from pathlib import Path
import platform
import sys

import cv2
import numpy as np
import scipy

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from challenge2.destination_plan import DestinationPlan,PALETTE


def load_inputs(protocol_path):
    protocol=json.loads(protocol_path.read_text());loaded={}
    for name,item in protocol['files'].items():
        p=(protocol_path.parent/item['path']).resolve()
        if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Pinned input changed: '+name)
        loaded[name]=json.loads(p.read_text())
    return protocol,loaded


def rotation_angle(a,b):
    return float(np.degrees(np.arccos(np.clip((np.trace(a.T@b)-1)/2,-1,1))))


def make_panel(rows,path):
    # A schematic of proposed references in robot-base XY, not a render or photograph registration.
    canvas=np.full((820,1440,3),250,np.uint8)
    cv2.putText(canvas,'B/C/D nominal stud-grid plan | robot-base XY | not an Isaac render',(24,30),cv2.FONT_HERSHEY_SIMPLEX,.64,(25,25,25),1,cv2.LINE_AA)
    chosen=[r for r in rows if r['k']<2]
    xy=np.array([c[:2] for r in chosen for c in r['footprint_corners_base_m']]);low=xy.min(axis=0)-.022;high=xy.max(axis=0)+.022
    span=high-low;scale=min(620/span[0],650/span[1])
    for parity in (0,1):
        xoff=55+720*parity
        def px(point):return (int(xoff+(point[0]-low[0])*scale),int(745-(point[1]-low[1])*scale))
        cv2.putText(canvas,f'Layer k={parity}: 4 ridges x 3 bricks',(xoff,65),cv2.FONT_HERSHEY_SIMPLEX,.62,(30,30,30),1,cv2.LINE_AA)
        for row in chosen:
            if row['k']!=parity:continue
            corners=np.array([px(c) for c in row['footprint_corners_base_m']],np.int32)
            color={'B':(190,100,25),'C':(70,145,70),'D':(145,70,150)}[row['destination']]
            cv2.polylines(canvas,[corners],True,color,2,cv2.LINE_AA)
            c=px(row['position_m']);label=f"{row['n']},{row['m']}"
            cv2.putText(canvas,label,(c[0]-11,c[1]+4),cv2.FONT_HERSHEY_SIMPLEX,.32,color,1,cv2.LINE_AA)
            if row['n']==row['m']==0:
                cv2.circle(canvas,c,4,(0,0,210),-1)
                cv2.putText(canvas,row['destination'],(c[0]-4,c[1]+27),cv2.FONT_HERSHEY_SIMPLEX,.65,color,2,cv2.LINE_AA)
        cv2.arrowedLine(canvas,(xoff,785),(xoff+50,785),(30,30,30),1,tipLength=.12)
        cv2.putText(canvas,'+base X',(xoff+55,789),cv2.FONT_HERSHEY_SIMPLEX,.4,(30,30,30),1)
        cv2.putText(canvas,'Red point: first slot; n=ridge, m=brick',(xoff,805),cv2.FONT_HERSHEY_SIMPLEX,.4,(30,30,30),1)
    if not cv2.imwrite(str(path),canvas):raise RuntimeError('Panel output failed')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--inputs',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);a=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Batch export requires default Pueue snapshot')
    protocol,data=load_inputs(a.inputs);cfg=data['config'];reference=data['references']
    if reference['reference_frame']!='robot_base_O' or reference['pose_frame']!='configured_end_effector_EE' or reference['position_units']!='m':raise ValueError('Unexpected source conventions')
    if cfg['accepted_colors']!=list(PALETTE) or (cfg['ridges_per_layer'],cfg['bricks_per_ridge'],cfg['center_pitch_m'],cfg['body_height_m'])!=(4,3,.032,.0096):raise ValueError('Frozen layout contract changed')
    plan=DestinationPlan(reference,cfg['default_requested_colors'],max_layers=cfg['max_layers'],reject_labels=cfg['reject_labels'])
    rows=[plan.slot(d,count) for d in ('B','C','D') for count in range(plan.capacity)]
    requested=[list(s) for size in (1,2,3) for s in itertools.combinations(PALETTE,size)]
    routing=[];preferences=[]
    for colors in requested:
        p=DestinationPlan(reference,colors,reject_labels=cfg['reject_labels'])
        for label in [*PALETTE,*cfg['reject_labels'],None,'UNKNOWN','bright_red','ochre']:
            routing.append({'requested':colors,'label':label,'result':p.route(label)})
        for count in range(6):
            p.counts['B']=count
            preferences.append({'requested':colors,'count':count,'result':p.preferred_B_color()})
    confirmations=[]
    def record(case,p,action):
        before=dict(p.counts)
        try:result=action();outcome='ok'
        except (ValueError,OverflowError) as error:result=None;outcome=type(error).__name__
        confirmations.append({'case':case,'before':before,'after':dict(p.counts),'outcome':outcome,'result':result})
    p=DestinationPlan(reference,['tan']);record('proposal_no_change',p,lambda:p.slot('B')['id'])
    record('abstention_reject_no_change',p,lambda:[p.route(None),p.route(cfg['reject_labels'][0])])
    record('confirm_0_to_1',p,lambda:p.confirm('B',0));record('stale_0_rejected',p,lambda:p.confirm('B',0))
    p=DestinationPlan(reference,['tan'],counts={'B':11});record('confirm_11_to_12',p,lambda:p.confirm('B',11))
    p=DestinationPlan(reference,['tan'],counts={'B':299});record('confirm_299_to_300',p,lambda:p.confirm('B',299));record('capacity_rejected',p,lambda:p.confirm('B',300))
    byid={p['id']:p for p in reference['poses']};reviews=[]
    for number in range(8,16):
        name=f'point_{number:02d}';raw=byid[name];r=np.asarray(raw['O_T_EE']).reshape(4,4,order='F')[:3,:3]
        destination={14:'C',15:'D'}.get(number,'B');proposals=[];neighbors=[]
        for parity in (0,1):
            target=plan.slot(destination,parity*12);rotation=np.asarray(target['T_base_EE'])[:3,:3];long=np.asarray(target['long_axis_base'])
            proposals.append({'parity':parity,'orientation_change_deg':rotation_angle(r,rotation),'long_axis_line_error_deg':float(np.degrees(np.arccos(np.clip(abs(r[:,0]@long),0,1)))),'rotation_matrix':rotation.tolist()})
            candidates=[s for s in rows if s['destination']==destination and s['k']==parity]
            nearest=min(candidates,key=lambda s:np.linalg.norm(np.asarray(s['position_m'])[:2]-raw['xyz_m'][:2]))
            neighbors.append({'parity':parity,'slot_id':nearest['id'],'residual_m':float(np.linalg.norm(np.asarray(nearest['position_m'])[:2]-raw['xyz_m'][:2]))})
        recommendation=0 if number in (11,14,15) else min(neighbors,key=lambda x:x['residual_m'])['parity']
        reviews.append({'recorded_id':name,'anchor_destination':destination if number in (11,14,15) else None,'raw_R_base_EE':r.tolist(),'raw_Z_reused':False,
            'proposed':proposals,'nearest_slot_xy_by_parity':neighbors,'recommended_parity':recommendation,
            'recommendation_scope':'Operator first-slot anchor' if number in (11,14,15) else 'Nearest nominal XY grid only; old layer identity and measured placement are not verified',
            'original_export_modified':False})
    result={'schema':'nominal-destination-plan-v1','reference_frame':'robot_base_O','pose_frame':'configured_end_effector_EE_nominal','hardware_authorized':False,
        'config':cfg,'source_reference_hash':protocol['files']['references']['sha256'],'slots':rows,'routing_examples':routing,'preference_examples':preferences,'confirmation_examples':confirmations,'orientation_review':reviews,
        'mixing_rule':'Preferred B color cycles requested order by confirmed B count; routing alone cannot guarantee a balanced mix if the next exposed color is unavailable',
        'counts_advance_only_on_caller_confirmation':True,'physical_held_brick_transform':None,'native_attachment_verified':False,'simulator_truth_used':False,
        'runtime_versions':{'python':platform.python_version(),'numpy':np.__version__,'opencv':cv2.__version__,'scipy':scipy.__version__}}
    a.output.mkdir(parents=True,exist_ok=True)
    (a.output/'destinations.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (a.output/'orientation_review.json').write_text(json.dumps({'scope':'Nominal XY/parity review, not validated old-layer identity','records':reviews},indent=2,allow_nan=False)+'\n')
    (a.output/'first_slots.json').write_text(json.dumps({'scope':'Nominal configured-EE first targets in robot_base_O','slots':[plan.slot(d,0) for d in ('B','C','D')],'runtime_versions':result['runtime_versions']},indent=2,allow_nan=False)+'\n')
    with (a.output/'destinations.csv').open('w',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['id','destination','count','n','m','k','x_m','y_m','z_m','qw','qx','qy','qz','hardware_authorized'])
        for row in rows:writer.writerow([row['id'],row['destination'],row['count'],row['n'],row['m'],row['k'],*row['position_m'],*row['quaternion_wxyz'],False])
    make_panel(rows,a.output/'layers_panel.png')
    print('Exported',len(rows),'nominal EE targets; no hardware or simulation')


if __name__=='__main__':main()

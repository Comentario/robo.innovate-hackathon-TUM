#!/usr/bin/python3
"""Audit both task-equivalent yaw choices for all stored Cartesian targets; no motion."""
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path
import numpy as np
from kinematics import Kinematics

HERE=Path(__file__).resolve().parent


def yaw_variant(pose,degrees):
    matrix=np.array(pose).reshape((4,4),order='F').copy()
    a=math.radians(degrees);c,s=math.cos(a),math.sin(a)
    # Tool-axis symmetry preserves the approach direction even for a taught
    # pose with a small residual tilt. A world-Z turn would reverse that tilt.
    matrix[:3,:3]=matrix[:3,:3]@np.array([[c,-s,0],[s,c,0],[0,0,1]])
    return matrix.reshape(-1,order='F').tolist()


def catalog_signature(raw,policy,model_sha):
    return hashlib.sha256(raw+json.dumps(policy,sort_keys=True).encode()+model_sha.encode()).hexdigest()


def main():
    raw=(HERE/'positions.json').read_bytes();catalog=json.loads(raw)
    policy=json.loads((HERE/'motion_config.json').read_text())['singularity_avoidance']
    state=json.loads((HERE/'robot_model_state.json').read_text())
    model=Kinematics(state['F_T_EE'],policy)
    seeds=[np.array(catalog['points'][f'point_{i:02d}']['q_rad']) for i in (3,15,1)]
    seeds.append(np.array(state['q']))
    # Deterministic mirrored seeds explore both shoulder families, without
    # treating any invented joint vector as a taught or executable pose.
    for q3 in (-1.8,-.8,.8,1.8):
        q=seeds[0].copy();q[0]=-.5 if q3>0 else .5;q[2]=q3;seeds.append(q)
    recent={};entries={};targets=[(str(int(k[-2:])),v) for k,v in catalog['points'].items()]+list(catalog['input_bricks'].items())
    for index,(name,point) in enumerate(targets):
        found=[]
        for yaw in ([0] if name=='1' else [0,180]):
            pose=yaw_variant(point['O_T_EE'],yaw)
            for sign in (1,-1):
                pool=[]
                if (yaw,sign) in recent:pool.append(recent[(yaw,sign)])
                if point.get('q_rad') is not None:pool.append(point['q_rad'])
                pool+=seeds
                for seed in pool:
                    result=model.solve(pose,seed,sign,None,max_evaluations=100)
                    if result:
                        result.update(effective_O_T_EE=pose,yaw_variant_deg=yaw,shoulder_sign=sign)
                        found.append(result);recent[(yaw,sign)]=result['q'];break
        entries[name]={'candidates':found,'status':'model_feasible' if found else 'blocked_no_margin_validated_solution',
                       'canonical_O_T_EE':point['O_T_EE'],'physical_validation':False}
        if index%15==0 or index==len(targets)-1:
            print(f'AUDIT {index+1}/{len(targets)}; feasible {sum(bool(e["candidates"]) for e in entries.values())}',flush=True)
    output=dict(created_utc=datetime.now(timezone.utc).isoformat(),
                source_signature=catalog_signature(raw,policy,model.model_sha256),
                model_sha256=model.model_sha256,policy=policy,tool_F_T_EE=state['F_T_EE'],
                count=len(entries),model_feasible_count=sum(bool(e['candidates']) for e in entries.values()),
                blocked=[k for k,v in entries.items() if not v['candidates']],poses=entries,
                scope='Endpoint IK and margins only. Every commanded full path must independently pass preflight. No hardware movement or Desk warning validation performed.')
    (HERE/'kinematic_catalog.json').write_text(json.dumps(output,indent=2)+'\n')
    print('AUDIT COMPLETE:',output['model_feasible_count'],'/',len(entries),'feasible; blocked:',output['blocked'],flush=True)


if __name__=='__main__':main()

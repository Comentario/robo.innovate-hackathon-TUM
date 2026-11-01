"""Fixed1809 saved-point comparison. No simulation, cook or acceptance promotion."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
STEPS=(1710,1711)


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def nearest(point,vertices,indices):
    """Unsigned triangle distance and nearest facet; edges/degeneracies included."""
    triangles=np.asarray(vertices,float)[np.asarray(indices,int)];a,b,c=triangles.transpose(1,0,2)
    ab,ac=b-a,c-a;n=np.cross(ab,ac);n2=np.sum(n*n,axis=1);ap=np.asarray(point)-a
    projected=np.asarray(point)-n*np.divide(np.sum(ap*n,axis=1),n2,out=np.zeros(len(n2)),where=n2>1e-30)[:,None]
    d00,d01,d11=np.sum(ab*ab,axis=1),np.sum(ab*ac,axis=1),np.sum(ac*ac,axis=1)
    v=projected-a;d20,d21=np.sum(v*ab,axis=1),np.sum(v*ac,axis=1);den=d00*d11-d01*d01
    u=np.divide(d11*d20-d01*d21,den,out=np.full(len(den),-np.inf),where=abs(den)>1e-30)
    w=np.divide(d00*d21-d01*d20,den,out=np.full(len(den),-np.inf),where=abs(den)>1e-30)
    candidates=[projected];distances=[np.where((u>=0)&(w>=0)&(u+w<=1)&(n2>1e-30),np.linalg.norm(projected-point,axis=1),np.inf)]
    for start,end in ((a,b),(b,c),(c,a)):
        edge=end-start;l2=np.sum(edge*edge,axis=1)
        t=np.clip(np.divide(np.sum((point-start)*edge,axis=1),l2,out=np.zeros(len(l2)),where=l2>1e-30),0,1)
        q=start+t[:,None]*edge;candidates.append(q);distances.append(np.linalg.norm(q-point,axis=1))
    which,facet=np.unravel_index(np.argmin(distances),np.asarray(distances).shape)
    return {'distance_m':float(distances[which][facet]),'facet_index':int(facet),
            'nearest_finger_m':candidates[which][facet].tolist(),'triangle_indices':np.asarray(indices)[facet].tolist()}


def frames(path,wanted):
    result={}
    with path.open() as stream:
        for line in stream:
            row=json.loads(line)
            if row['step'] in wanted:
                if row['step'] in result:raise RuntimeError('Duplicate requested trace frame')
                result[row['step']]=row
            if row['step']>max(wanted):break
    if set(result)!=set(wanted):raise RuntimeError('Missing requested trace frames')
    return result


def run(inputs,output):
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Saved-data work requires default Pueue')
    start=time.monotonic();deadline=start+9.;inputs=Path(inputs);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(inputs.read_text());paths={};hashes={}
    if manifest.get('execution_authorized') is not True:raise RuntimeError('Diagnostic execution is not authorized')
    def checked(key,record):
        path=(inputs.parent/record['path']).resolve();digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if digest!=record['sha256']:raise RuntimeError('Input hash mismatch: '+key)
        hashes[key]=digest;return path
    prior=json.loads(checked('prior_supervisor',manifest['prior_supervisor']).read_text())
    if prior['proceed_gate_passed'] is not False or prior['cumulative_case_seconds']!=manifest['prior_case_seconds']:
        raise RuntimeError('Prior failed result or cumulative clock binding differs')
    required={'online_trace','truth_trace','tool_geometry','cook_results','observer_metadata',
              'evaluation_observer_metadata','capture_metadata','science','contact_protocol'}
    if (set(manifest['files'])!=required or set(manifest['contacts'])!={'1710','1711'} or
        manifest['steps']!=list(STEPS) or manifest['pose_only_predecessor_step']!=1709 or manifest['maximum_active_seconds']!=10):
        raise RuntimeError('Manifest differs from fixed two-step scope')
    for key,row in manifest['files'].items():paths[key]=checked(key,row)
    for step,rows in manifest['contacts'].items():
        if set(rows)!={'right','source'}:raise RuntimeError('Only right/source NPZ are in scope')
        for label,row in rows.items():paths[step+'_'+label]=checked(step+'_'+label,row)
    read=lambda key:json.loads(paths[key].read_text())
    geometry,cook,science,protocol=map(read,('tool_geometry','cook_results','science','contact_protocol'))
    online=frames(paths['online_trace'],(1709,1710,1711));truth=frames(paths['truth_trace'],STEPS)
    observer,evaluation,metadata=map(read,('observer_metadata','evaluation_observer_metadata','capture_metadata'))
    if (metadata['controller_status']!='aborted' or metadata['steps_executed']!=1711 or
        'unqualified_contact_right' not in online[1711]['stop_reasons']):
        raise RuntimeError('Pinned capture does not preserve the original step1711 abort')
    if metadata['protocol_sha256']!=hashes['science']:raise RuntimeError('Scientific protocol is not the captured version')
    for key,field in (('observer_metadata','observer_metadata'),('evaluation_observer_metadata','evaluation_observer_metadata')):
        if (Path(manifest['source_snapshot'])/'output'/metadata[field]).resolve()!=paths[key]:raise RuntimeError('Observer metadata channel binding differs')
    own=load_module('fixed_point_online',ROOT/'experiments/stage2_contact_20261025/geometry.py')
    helper=load_module('fixed_point_independent',ROOT/'experiments/stage2_exploratory_20261025/evaluation/contact_helpers.py')
    finger=geometry['fingers']['right'];right=finger['body_path']
    views={'right':observer['resolved_views']['right'],'source':evaluation['resolved_views']['source']}
    target=views['source']['sensor_paths'][0]
    if views['right']['sensor_paths']!=[right] or len(views['source']['sensor_paths'])!=1:
        raise RuntimeError('Resolved sensor paths are ambiguous')
    cooked={}
    for kind in ('body','head'):
        result=cook['tips']['right'][kind]
        if not result['result_valid'] or result['hull_count']!=1:raise RuntimeError('Expected saved valid single hull')
        hull=result['hulls'][0];triangles=[]
        for face in hull['polygons']:
            indices=face['indices'];triangles.extend([indices[0],indices[k],indices[k+1]] for k in range(1,len(indices)-1))
        cooked[kind]=(hull['vertices_m'],triangles)
    report={'proceed_gate_passed':False,'original1809_failure_preserved':True,'input_sha256':hashes,
            'scope':'Right loaded points and source RIGHTpair only; actor filters do not identify collider shapes.',
            'cooked_surface_scope':'SDK returned indexed polygon fan, descriptive; not asserted live support geometry.',
            'capture_protocol_sha256':metadata['protocol_sha256'],'frames':[],'truncated':False,
            'cook_coordinate_provenance':'Existing exposed model bakes both body/head mesh vertices into finger frame with identity mesh transform; no new fitting.',
            'helper_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in
                (Path(own.__file__),Path(helper.__file__))}}
    for step in STEPS:
        row=online[step];gt=truth[step];previous=online[step-1]
        if (row['step']!=gt['step'] or row['time_s']!=gt['time_s'] or row['physics_dt_s']!=science['physics']['dt_s'] or
            abs(row['time_s']-previous['time_s']-row['physics_dt_s'])>1e-7):
            raise RuntimeError('Source/finger step, clock or dt mismatch')
        frame={'step':step,'time_s':row['time_s'],'prior_pose_step':step-1,'sides':{},
               'right_finger_pose_world_wxyz':row['finger_poses_world_wxyz']['right'],
               'prior_right_finger_pose_world_wxyz':previous['finger_poses_world_wxyz']['right']}
        for label in ('right','source'):
            summary=row['contacts']['right'] if label=='right' else gt['contacts']['source']
            recorded=summary['file'] if isinstance(summary,dict) else summary
            expected=(Path(manifest['source_snapshot'])/'output'/recorded).resolve()
            if expected!=paths[str(step)+'_'+label]:raise RuntimeError('NPZ trace-path binding differs')
            with np.load(paths[str(step)+'_'+label],allow_pickle=False) as raw:data={k:raw[k].copy() for k in raw.files}
            if not all(np.isfinite(v).all() for v in data.values()):raise RuntimeError('Nonfinite saved contact arrays')
            filters=helper.filter_paths(views[label]);wanted=filters if label=='right' else [right]
            side={'force_carrying_points':[],'sensor_path':views[label]['sensor_paths'][0],
                  'raw_summary':helper.view_summary(data,filters,protocol,row['physics_dt_s'])}
            side['raw_summary']['pairs']={p:v for p,v in side['raw_summary']['pairs'].items()
                if p in wanted and (v['normal_magnitude_N']>0 or p==right or p==target)}
            for partner in wanted:
                indices=helper.pair_rows(data,filters.index(partner),views[label]['max_contact_data_count'])
                for index in indices:
                    force=float(data['normal_forces_N'][index].item())
                    if abs(force)<=1e-8:continue
                    if time.monotonic()>=deadline:report['truncated']=True;break
                    point=data['normal_points_world_m'][index];normal=data['normal_vectors_world'][index];sep=float(data['normal_separations_m'][index].item())
                    pose=np.asarray(row['finger_poses_world_wxyz']['right']);rotation=helper.rotation(pose[3:]);local=(point-pose[:3])@rotation
                    prior=np.asarray(previous['finger_poses_world_wxyz']['right']);prior_local=(point-prior[:3])@helper.rotation(prior[3:])
                    outward=(-1 if label=='right' else 1)*np.sign(force)*normal
                    original=own.own_point(local,sep,finger,{'point_gate':{'surface_slack_m':science['contacts']['point_surface_slack_m'],'white_clearance_extra_m':science['contacts']['white_head_clearance_extra_m']}})
                    independent=helper.classify_point(point,sep,pose,finger['colliders'],protocol,outward_world=outward,flat_face_y_m=finger['inner_plane_y_m'],expected_grip_normal_finger=[0,1,0])
                    surfaces=[{'role':c['role'],'path':c['path'],**nearest(local,c['points_finger_m'],c['triangle_indices']),
                               'bounds_finger_m':c['bounds_finger_m'],'contact_offset_authored':c['contact_offset_m'],'rest_offset_authored':c['rest_offset_m']} for c in finger['colliders']]
                    side['force_carrying_points'].append({'active_row':int(index),'raw_index':int(data['normal_indices'][index]),'partner':partner,
                        'force_signed_N':force,'point_world_m':point.tolist(),'normal_world':normal.tolist(),'separation_m':sep,
                        'point_finger_m':local.tolist(),'prior_pose_point_finger_m':prior_local.tolist(),'pose_sensitivity_m':float(np.linalg.norm(prior_local-local)),
                        'online_own_point':original,'independent_classify_point':independent,'authored_surfaces':surfaces,
                        'SDK_indexed_fans':{kind:{**nearest(local,v,t),'bounds_finger_m':[np.min(v,axis=0).tolist(),np.max(v,axis=0).tolist()]} for kind,(v,t) in cooked.items()}})
                if report['truncated']:break
            side['loaded_count']=len(side['force_carrying_points']);frame['sides'][label]=side
        report['frames'].append(frame)
        if report['truncated']:break
    report['wall_seconds']=time.monotonic()-start
    report['offset_interpretation']='Authored None/sentinel offsets do not establish effective runtime defaults; UNMEASURED.'
    (output/'contact_points.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(allow_abbrev=False);parser.add_argument('--inputs',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();run(args.inputs,args.output)

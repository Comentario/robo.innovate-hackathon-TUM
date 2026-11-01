"""One pinned saved-data clearance replay; no Kit, camera change or motion."""
import argparse,ast,collections,hashlib,heapq,json,math,os,time
from pathlib import Path
import numpy as np
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation
HERE=Path(__file__).resolve().parent


def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def frozen_helpers(protocol):
    namespace={'np':np,'math':math};nodes=[]
    for name in ('run_pick.py','sensors.py','stage1_online.py'):
        text=protocol['frozen_source_text'][name]
        if hashlib.sha256(text.encode()).hexdigest()!=protocol['frozen_source_sha256'][name]:raise RuntimeError('Frozen helper source changed')
        tree=ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node,ast.FunctionDef) and node.name in ('qangle','interpolate','cloud','local_height','filter_workspace_depth'):
                nodes.append(node)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<pinned pure functions>','exec'),namespace)
    return namespace

def quaternion_apply_float32(q,v):
    q=np.asarray(q,np.float32);v=np.asarray(v,np.float32);t=np.cross(q[1:],v)*np.float32(2)
    return v+q[0]*t+np.cross(q[1:],t)

def coverage_view(center,view,K):
    eye=center+view['eye_offset_m'];target=center+view['target_offset_m'];forward=target-eye;forward/=np.linalg.norm(forward)
    up=np.asarray(view['up_world'],float);up/=np.linalg.norm(up);right=np.cross(forward,up);right/=np.linalg.norm(right);up=np.cross(right,forward)
    R=np.stack((right,-up,forward));return {'K':K,'R':R,'t':-R@eye,'evidence':'PROJECTION_COVERAGE_ONLY_NO_DEPTH'}


def run(inputdir,outputdir,deadline=None):
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Saved-data diagnostic requires the default Pueue queue')
    started=time.monotonic();end=min(deadline if deadline is not None else started+30,started+25)
    inputdir,outputdir=Path(inputdir),Path(outputdir);outputdir.mkdir(parents=True,exist_ok=True)
    p=json.loads((HERE/'clearance_protocol.json').read_text())
    for relative,digest in p['input_sha256'].items():
        if sha(inputdir/relative)!=digest:raise RuntimeError('Saved replay input changed:'+relative)
    read=lambda name:json.loads((inputdir/name).read_text())
    science=p['science'];helpers=frozen_helpers(p);selection=read('online/selection.json');r3=read('online/r3_initial.json');calibration=read('online/calibration.json');geometry=read('tool_geometry.json');init=read('robot_initialization.json');metadata=read('capture_metadata.json')
    if selection['rejected_candidates'][0]['candidate_id']!=p['candidate_id']:raise RuntimeError('Not the frozen first candidate')
    raw=next(c for c in r3['candidates'] if c['id']==p['candidate_id'])
    candidate={'table_xy_m':raw['center_world_xy_m'],'yaw_table_rad':raw['yaw_world_rad'],'estimated_body_top_from_selected_band_m':raw['surface_height_world_m']}
    with np.load(inputdir/selection['depth'],allow_pickle=False) as data:depth=data[selection['depth_array_key']].copy()
    nominal=calibration['views']['camera_0'];cal={'K':np.asarray(calibration['K']), 'R':np.asarray(nominal['R_world_to_camera']),'t':np.asarray(nominal['t_world_to_camera_m'])}
    filtered,_=helpers['filter_workspace_depth'](depth,cal,{'table_z_bounds_m':[-.005,.20]})
    sensor=type('FrozenSensor',(),{})();sensor.cal=cal;sensor.protocol=science;sensor.initial_cloud=helpers['cloud'](sensor,filtered)
    upper,support=helpers['local_height'](sensor,candidate)
    if upper is None:raise RuntimeError('Frozen first-candidate local support could not be reconstructed')
    hand=np.asarray(init['hand_physics_pose_wxyz'],np.float32);offset=np.asarray(science['tool_frames']['T_hand_grip_translation_m'],np.float32)
    current=np.r_[hand[:3]+quaternion_apply_float32(hand[3:],offset),hand[3:]].astype(float);rotation=Rotation.from_quat(current[3:][[1,2,3,0]]).as_matrix();parts=[];self_hulls=[]
    joint=dict(zip(init['joint_names'],init['actual_joint_positions_native_units']));reconstructed_fingers={}
    for label,finger in geometry['fingers'].items():
        q=joint['fr3_finger_joint1' if label=='left' else 'fr3_finger_joint2'];position=hand[:3]+quaternion_apply_float32(hand[3:],[0,q if label=='left' else -q,.0584])
        reconstructed_fingers[label]={'position_world_m':position.tolist(),'quaternion_world_wxyz':hand[3:].tolist(),'nominal_hand_offset_m':[0,q if label=='left' else -q,.0584]}
        for c in finger['colliders']:
            world=np.asarray(c['points_finger_m'])@rotation.T+position;self_hulls.append(ConvexHull(world).equations)
            parts.append({'id':c['path'],'role':c.get('role'),'local':(world-current[:3])@rotation})
    yaw=candidate['yaw_table_rad'];x=np.array([math.cos(yaw),math.sin(yaw),0]);z=np.array([0,0,-1.]);y=np.cross(z,x);target_rotation=np.column_stack((x,y,z));quat=Rotation.from_matrix(target_rotation).as_quat()[[3,0,1,2]]
    delta=science['tool_frames']['metal_distal_hand_z_m']-science['tool_frames']['T_hand_grip_translation_m'][2];xyz=np.r_[candidate['table_xy_m'],upper+.003]-target_rotation@np.array([0,0,delta]);goal=np.r_[xyz,quat];hover=goal.copy();hover[2]+=.010;poses=[]
    for leg,(a,b) in enumerate(((current,hover),(hover,goal))):
        n=max(1,math.ceil(np.linalg.norm(b[:3]-a[:3])/.002),math.ceil(helpers['qangle'](a[3:],b[3:])/math.radians(1)))
        poses.extend((leg,k/n,helpers['interpolate'](a,b,k/n)) for k in range(n+1))
    alternate={'existing_close_oblique':{'K':cal['K'],'R':np.asarray(calibration['views']['camera_1']['R_world_to_camera']),'t':np.asarray(calibration['views']['camera_1']['t_world_to_camera_m']),'evidence':'PROJECTION_COVERAGE_ONLY_NO_DEPTH'}}
    center=np.asarray(nominal['eye_world_m'])-[0,0,.4]
    for view in p['alternate_view_presets']:alternate['existing_wide_'+view['id']]=coverage_view(center,view,cal['K'])
    counts=collections.Counter();groups=collections.defaultdict(collections.Counter);view_counts={name:collections.Counter() for name in alternate};examples=[];worst=[];seen_per_category=collections.Counter();sample_id=0;truncated=False;envelope=science['engineering_envelopes'];H,W=depth.shape
    try:
        for pose_index,(leg,fraction,pose) in enumerate(poses):
            rot=Rotation.from_quat(pose[3:][[1,2,3,0]]).as_matrix()
            for part in parts:
                v=part['local'];lo,hi=v.min(0),v.max(0);grid=np.asarray([[a,b,c] for a in (lo[0],(lo[0]+hi[0])/2,hi[0]) for b in (lo[1],(lo[1]+hi[1])/2,hi[1]) for c in (lo[2],(lo[2]+hi[2])/2,hi[2])]);relative=grid@rot.T
                angle=envelope['final_TCP_tracking_angle_rad'];yaw_bound=envelope['yaw_rad'];norm=np.linalg.norm(relative,axis=1)
                angular=np.column_stack([np.sin(angle)*np.linalg.norm(np.delete(relative,j,axis=1),axis=1)+(1-np.cos(angle))*norm for j in range(3)]);angular[:,:2]+=np.sin(yaw_bound)*abs(relative[:,[1,0]])+(1-np.cos(yaw_bound))*abs(relative[:,:2])
                position=np.array([envelope['XY_m'],envelope['XY_m'],envelope['local_upper_depth_Z_m']])+envelope['final_TCP_tracking_position_m'];inflation=angular+position;signs=np.asarray([[a,b,c] for a in (-1,1) for b in (-1,1) for c in (-1,1)])
                world=(relative[:,None,:]+inflation[:,None,:]*signs[None,:,:]+pose[:3]).reshape(-1,3);camera=world@cal['R'].T+cal['t'];uv=camera[:,:2]/camera[:,2,None];uv=uv@cal['K'][:2,:2].T+cal['K'][:2,2]
                alternate_inside={}
                for name,view in alternate.items():
                    optical=world@view['R'].T+view['t'];pixels=optical[:,:2]/optical[:,2,None];pixels=pixels@view['K'][:2,:2].T+view['K'][:2,2];front=np.isfinite(pixels).all(1)&(optical[:,2]>0);rounded=np.rint(np.nan_to_num(pixels,nan=-1e9,posinf=-1e9,neginf=-1e9));inside=front&(rounded[:,0]>=0)&(rounded[:,0]<W)&(rounded[:,1]>=0)&(rounded[:,1]<H)
                    alternate_inside[name]=inside
                for local_index,(point,optical,pixel) in enumerate(zip(world,camera,uv)):
                    if sample_id%128==0 and time.monotonic()>=end:raise TimeoutError('Shared diagnostic deadline')
                    identity=sample_id;sample_id+=1;gap=None;returned=None
                    for name,inside in alternate_inside.items():
                        view_counts[name]['samples']+=1;view_counts[name]['front_inframe']+=int(inside[local_index]);view_counts[name]['not_front_inframe']+=int(not inside[local_index])
                    if any(np.max(h[:,:3]@point+h[:,3])<=1e-8 for h in self_hulls):category='self_known_proprio_skip'
                    elif not np.isfinite(pixel).all() or optical[2]<=0:category='invalid_projection_or_behind_camera'
                    else:
                        ix,iy=np.rint(pixel).astype(int)
                        if not(0<=ix<W and 0<=iy<H):category='out_of_image'
                        elif not np.isfinite(depth[iy,ix]):category='invalid_depth'
                        else:
                            gap=float(depth[iy,ix]-optical[2]);category='observed_ray_free' if gap>0 else 'UNRESOLVED_OCCLUDED_OR_OBSTRUCTED'
                            ray=np.array([(ix-cal['K'][0,2])/cal['K'][0,0],(iy-cal['K'][1,2])/cal['K'][1,1],1.]);returned=(float(depth[iy,ix])*ray-cal['t'])@cal['R']
                    counts[category]+=1;groups[f"{part['id']}|leg{leg}|quarter{min(3,int(fraction*4))}"][category]+=1
                    record={'sample_id':identity,'category':category,'part':part['id'],'role':part['role'],'path_leg':leg,'path_fraction':fraction,'pose_index':pose_index,'world_m':point.tolist(),'pixel':pixel.tolist() if np.isfinite(pixel).all() else None,'gap_m':gap,'measured_return_world_m':returned.tolist() if returned is not None else None}
                    if returned is not None:record['return_inside_current_tool']=bool(any(np.max(h[:,:3]@returned+h[:,3])<=1e-8 for h in self_hulls))
                    if seen_per_category[category]<p['representative_first_per_category']:examples.append(record);seen_per_category[category]+=1
                    if gap is not None and gap<=0:
                        item=(-gap,identity,record)
                        if len(worst)<p['worst_nonfree_examples']:heapq.heappush(worst,item)
                        elif item[0]>worst[0][0]:heapq.heapreplace(worst,item)
    except TimeoutError:truncated=True
    all_examples={r['sample_id']:r for r in examples}
    all_examples.update({r['sample_id']:r for _,_,r in worst});examples=[all_examples[k] for k in sorted(all_examples)][:p['maximum_saved_examples']]
    unknown=sum(counts[k] for k in ('invalid_projection_or_behind_camera','out_of_image','invalid_depth'));replay={'samples':sample_id,'unknown_samples':unknown,'nonfree_samples':counts['UNRESOLVED_OCCLUDED_OR_OBSTRUCTED']}
    result={'schema':p['schema'],'completed':not truncated,'truncated':truncated,'candidate_id':p['candidate_id'],'classification_counts':dict(counts),'by_part_leg_quarter':{k:dict(v) for k,v in groups.items()},'projection_only_coverage':{k:dict(v) for k,v in view_counts.items()},'baseline_counts':p['baseline_counts'],'replayed_counts':replay,'count_differences':{k:replay[k]-p['baseline_counts'][k] for k in replay},'exact_count_reproduction':replay==p['baseline_counts'],'local_height_replay':{'height_m':upper,'support':support},'target_pose_replay':goal.tolist(),'proprio_reconstruction':{'initial_TCP':current.tolist(),'fingers':reconstructed_fingers,'status':p['reconstruction']},'representative_samples':examples,'active_wall_s':time.monotonic()-started,'proceed_gate_passed':False,'scope':p['scope'],'nonfree_interpretation':'Behind/at first measured depth is unresolved occlusion or obstruction, NOT proof of solid penetration. Alternative views have no saved-depth evidence.'}
    save(outputdir/'clearance_summary.json',result)
    if time.monotonic()<end:
        from PIL import Image,ImageDraw
        image=Image.open(inputdir/selection['rgb']).convert('RGB');draw=ImageDraw.Draw(image)
        color={'out_of_image':'orange','UNRESOLVED_OCCLUDED_OR_OBSTRUCTED':'red','invalid_depth':'magenta'}
        for r in examples:
            if r['category'] not in color or r['pixel'] is None:continue
            x,y=r['pixel'];x=max(2,min(W-3,x));y=max(2,min(H-3,y));draw.ellipse((x-3,y-3,x+3,y+3),outline=color[r['category']],width=1)
        image.save(outputdir/'clearance_overlay.png')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();run(args.input,args.output)

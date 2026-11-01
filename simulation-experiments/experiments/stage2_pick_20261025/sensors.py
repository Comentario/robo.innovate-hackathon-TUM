"""Fixed configured virtual RGB-D, unchanged R3 and conservative local checks."""
import hashlib,json,math
from pathlib import Path
import sys
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'experiments/stage1_20261025'))
from experiments.stage1_20261025 import online
from experiments.stage1_20261025.calibration import build
from experiments.stage2_exposed_tip_20261025.model import save

class Sensors:
    def __init__(self,sim,scene,geometry,cameras,output,protocol,source_color_reference=None):
        import torch
        from pxr import Gf,UsdGeom,UsdLux
        from isaaclab.sim import get_current_stage
        from experiments.final_workcell_20261024 import render_core
        self.sim,self.scene,self.output,self.protocol=sim,scene,output,protocol
        self.source_color_reference=Path(source_color_reference) if source_color_reference is not None else None
        self.core,self.torch=render_core,torch
        self.camera=scene['overview'];self.index=0;self.config=json.loads(cameras.read_text())
        self.calibration=build(geometry,cameras);nominal=self.calibration['views']['camera_0']
        self.cal={'K':np.asarray(self.calibration['K']), 'R':np.asarray(nominal['R_world_to_camera']),'t':np.asarray(nominal['t_world_to_camera_m'])}
        view=next(v for v in self.config['views'] if v['id']=='diagnostic_table_top')
        center=np.asarray(nominal['eye_world_m'])-view['eye_offset_m'];pose=render_core.camera_pose(center,view)
        self.design_center,self.close_pose=center,pose
        self.safety_cfg=protocol['perception'].get('geometry_safety_view')
        self.safety_config_sha256=hashlib.sha256(json.dumps(self.safety_cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest() if self.safety_cfg else None
        self.geometry_views=[];self.clearance_index=0
        self.camera.set_world_poses(positions=torch.tensor([pose['eye_world_m']],dtype=torch.float32),orientations=torch.tensor([pose['quaternion_wxyz_opengl']],dtype=torch.float32),convention='opengl');self.camera.reset()
        stage=get_current_stage();light=self.config['lighting'];UsdLux.DomeLight.Get(stage,'/World/Light').GetIntensityAttr().Set(light['dome_intensity'])
        key=UsdLux.RectLight.Define(stage,'/World/ExperimentKey');key.CreateWidthAttr(light['key_width_m']);key.CreateHeightAttr(light['key_height_m']);key.CreateNormalizeAttr(light['key_normalize']);key.CreateColorAttr(Gf.Vec3f(*light['key_color_linear']));key.CreateIntensityAttr(light['key_intensity'])
        lp=render_core.camera_pose((0,0,0),{'eye_offset_m':light['key_position_table_m'],'target_offset_m':light['key_target_table_m'],'up_world':(0,0,1)})
        xf=UsdGeom.Xformable(key.GetPrim());xf.AddTranslateOp().Set(Gf.Vec3d(*lp['eye_world_m']));q=lp['quaternion_wxyz_opengl'];xf.AddOrientOp().Set(Gf.Quatf(q[0],Gf.Vec3f(*q[1:])))
        for _ in range(self.config['render_warmup_frames']):sim.render()
        upstream=ROOT/'experiments/stage1_20261025/upstream'
        for name,digest in protocol['perception']['upstream_sha256'].items():
            if hashlib.sha256((upstream/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Frozen R3 changed:'+name)
        self.method=online.load('pick_R3',upstream/'method.py');self.depth_module=online.load('pick_depth',upstream/'depth_module.py');self.Evidence=online.load('pick_evidence',upstream/'evidence.py').Evidence
        self.method_config=json.loads((upstream/'config.json').read_text());self.depth_config=json.loads((upstream/'depth_config.json').read_text());self.depth_config['source_roi_world_xy_m']={'x':[-.128,.128],'y':[-.128,.128]}
        self.workspace=json.loads((ROOT/protocol['perception']['workspace']).read_text())
        save(output/'online/calibration.json',self.calibration)

    def _set_pose(self,pose):
        self.camera.set_world_poses(positions=self.torch.tensor([pose['eye_world_m']],dtype=self.torch.float32),orientations=self.torch.tensor([pose['quaternion_wxyz_opengl']],dtype=self.torch.float32),convention='opengl')
        self.camera.reset()
        for _ in range(self.config['render_warmup_frames']):self.sim.render()

    def _view_record(self,frame,cal,pose):
        K=self.camera.data.intrinsic_matrices[0].cpu().numpy().copy();position=self.camera.data.pos_w[0].cpu().numpy().copy();quaternion=self.camera.data.quat_w_opengl[0].cpu().numpy().copy()
        guard=self.safety_cfg['readback_guards'] if self.safety_cfg else {'K_atol_px':.001,'position_m':.000002,'angle_rad':.0001}
        if np.max(abs(K-cal['K']))>guard['K_atol_px'] or np.linalg.norm(position-pose['eye_world_m'])>guard['position_m'] or self.core.quaternion_error(quaternion,pose['quaternion_wxyz_opengl'])>guard['angle_rad']:raise RuntimeError('Configured geometry camera readback mismatch')
        return {**frame,'depth_sha256':hashlib.sha256((self.output/frame['depth']).read_bytes()).hexdigest(),'calibration':{**{key:np.asarray(value).tolist() for key,value in cal.items()},'image_size':self.config['image_size']},'image_size':self.config['image_size'],'configured_pose':{**pose,'up_fallback_used':bool(pose['up_fallback_used'])},'actual_sensor_readback':{'K':K.tolist(),'pos_world_m':position.tolist(),'quat_opengl_wxyz':quaternion.tolist()}}

    def _safety_capture(self,frame):
        import cv2
        close=self._view_record(frame,self.cal,self.close_pose);self.geometry_views=[close]
        self.depth_views=[{'frame_id':frame['frame_id'],'cal':self.cal,'depth':self.initial_depth}]
        if not self.safety_cfg:return
        cfg=self.safety_cfg
        if hashlib.sha256((ROOT/cfg['source_config']).read_bytes()).hexdigest()!=cfg['source_config_sha256'] or cfg['image_size']!=self.config['image_size'] or not np.array_equal(np.asarray(cfg['K']),self.cal['K']):raise RuntimeError('Frozen wide camera settings changed')
        pose=self.core.camera_pose(self.design_center,cfg['view']);rotation=np.asarray(pose['rotation_camera_to_world']);R=(rotation*np.array([1.,-1.,-1.])).T
        cal={'K':self.cal['K'].copy(),'R':R,'t':-R@np.asarray(pose['eye_world_m'])}
        clock=float(self.sim.current_time)
        try:
            self._set_pose(pose);self.camera.update(0.,force_recompute=True)
            rgb=self.camera.data.output['rgb'][0,:,:,:3].cpu().numpy().copy();depth=self.camera.data.output['distance_to_image_plane'][0,:,:,0].cpu().numpy().copy()
            folder=self.output/'online/geometry_observations/geometry_safety_wide_0000';folder.mkdir(parents=True)
            cv2.imwrite(str(folder/'rgb.png'),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR));np.savez_compressed(folder/'depth.npz',depth=depth)
            wide={'frame_id':folder.name,'measurement_time_s':float(self.sim.current_time),'rgb':str((folder/'rgb.png').relative_to(self.output)),'depth':str((folder/'depth.npz').relative_to(self.output)),'depth_array_key':'depth'}
            if wide['measurement_time_s']!=frame['measurement_time_s']:raise RuntimeError('Wide/close geometry frames differ in physics time')
            self.geometry_views.append(self._view_record(wide,cal,pose));self.depth_views.append({'frame_id':wide['frame_id'],'cal':cal,'depth':depth})
        finally:
            self._set_pose(self.close_pose);self.camera.update(0.,force_recompute=True)
        if float(self.sim.current_time)!=clock:raise RuntimeError('Geometry camera switching advanced physics')
        self._view_record(frame,self.cal,self.close_pose)
        save(self.output/'online/geometry_views.json',{'safety_config_sha256':self.safety_config_sha256,'views':self.geometry_views,'close_pose_restored':True,'physics_time_s':clock})

    def capture(self):
        import cv2
        clock=float(self.sim.current_time);self.sim.render();self.camera.update(0.,force_recompute=True)
        if float(self.sim.current_time)!=clock:raise RuntimeError('Render-only camera advanced physics')
        rgb=self.camera.data.output['rgb'][0,:,:,:3].cpu().numpy().copy();depth=self.camera.data.output['distance_to_image_plane'][0,:,:,0].cpu().numpy().copy()
        folder=self.output/'online/observations'/f'frame_{self.index:04d}';folder.mkdir(parents=True);self.index+=1
        cv2.imwrite(str(folder/'rgb.png'),cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR));np.savez_compressed(folder/'depth.npz',depth=depth)
        return rgb,depth,{'frame_id':folder.name,'measurement_time_s':clock,'rgb':str((folder/'rgb.png').relative_to(self.output)),'depth':str((folder/'depth.npz').relative_to(self.output)),'depth_array_key':'depth'}

    def cloud(self,depth):
        valid=np.isfinite(depth)&(depth>0);y,x=np.nonzero(valid);K=self.cal['K'];rays=np.c_[(x-K[0,2])/K[0,0],(y-K[1,2])/K[1,1],np.ones(len(x))]
        return (depth[valid,None]*rays-self.cal['t'])@self.cal['R']

    def select(self,current_tcp):
        import cv2
        rgb,depth,frame=self.capture();filtered,_=online.filter_workspace_depth(depth,self.cal,self.workspace)
        if self.source_color_reference is not None:
            from experiments.stage1_handoff_20261025.adapter import make_observation
            self.color_rgb_bgr=cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR)
            self.color_depth=depth
            self.color_observation=make_observation(frame,self.color_rgb_bgr,depth,self.cal)
        cv2.setRNGSeed(26);result,_,_=self.method.analyze(filtered,cv2.cvtColor(rgb,cv2.COLOR_RGB2BGR),self.cal,self.depth_module,self.depth_config,self.method_config,self.Evidence,'camera_0','observed')
        save(self.output/'online/r3_initial.json',result);candidates=[online.candidate_contract(c) for c in result['candidates'] if c['decision']=='present']
        candidates.sort(key=lambda c:(float(np.linalg.norm(np.asarray(c['table_xy_m'])-current_tcp[:2])),c['candidate_id']))
        self.initial_depth=depth;self.initial_cloud=self.cloud(filtered);self.frame=frame
        self._safety_capture(frame)
        return candidates,frame

    def color_handoff(self,selection,case_id):
        if self.source_color_reference is None:return None
        from experiments.stage1_handoff_20261025.adapter import classify_selection,json_digest
        raw=self.source_color_reference.read_bytes();reference=json.loads(raw)
        if reference['schema']!='frozen-source-color-reference-v1':raise RuntimeError('Unknown source-color reference bundle')
        values={};hashes={}
        for name in ('classifier','settings','prototypes'):
            record=reference[name];path=Path(record['path']);path=path if path.is_absolute() else ROOT/path
            contents=path.read_bytes();digest=hashlib.sha256(contents).hexdigest()
            if digest!=record['sha256']:raise RuntimeError('Frozen source-color reference changed: '+name)
            hashes[name+'_sha256']=digest
            if name!='classifier':values[name]=json.loads(contents)
        observation={**self.color_observation,'candidate_sha256':json_digest(selection.get('candidate'))}
        packet=classify_selection(selection,self.color_rgb_bgr,self.color_depth,self.cal,values['prototypes'],values['settings'],
            observation=observation,reference_hashes=hashes,current_time_s=float(self.sim.current_time),case_id=case_id)
        packet['reference_bundle_sha256']=hashlib.sha256(raw).hexdigest()
        save(self.output/'online/source_color_handoff.json',packet)
        return packet

    def local_height(self,candidate):
        xy=np.asarray(candidate['table_xy_m']);yaw=candidate['yaw_table_rad'];c,s=np.cos(yaw),np.sin(yaw);axes=np.array([[c,s],[-s,c]])
        cloud=self.initial_cloud;local=(cloud[:,:2]-xy)@axes.T
        selected=cloud[(abs(local[:,0])<=.014)&(abs(local[:,1])<=.006)&(abs(cloud[:,2]-candidate['estimated_body_top_from_selected_band_m'])<=.003)]
        support={'supported':False,'count':len(selected),'method':'Fixed eroded2x4 interior upper-depth quantiles; engineering support, not calibrated covariance'}
        if len(selected)<64:return None,support
        upper,p99=np.quantile(selected[:,2],[.9,.99]);upper_count=int(np.count_nonzero(abs(selected[:,2]-upper)<=.0005))
        support.update(upper_90_m=float(upper),upper_99_m=float(p99),upper_support_count=upper_count,spread_m=float(p99-upper))
        support['supported']=bool(p99-upper<=self.protocol['engineering_envelopes']['local_upper_depth_Z_m'] and upper_count>=32)
        return float(upper) if support['supported'] else None,support

    def clearance(self,poses,parts,current_parts):
        """Sample inflated tool boxes against observed ray-free space; unknown fails."""
        from scipy.spatial.transform import Rotation
        unknown=occupied=0;minimum=float('inf');samples=0;known_count=0
        views=getattr(self,'depth_views',[{'frame_id':'camera_0','cal':self.cal,'depth':self.initial_depth}])
        categories=('self_known_proprio_skip','invalid_projection_or_behind_camera','out_of_image','invalid_depth','observed_ray_free','UNRESOLVED_OCCLUDED_OR_OBSTRUCTED')
        per_view={v['frame_id']:{key:0 for key in categories} for v in views};witness_counts={'known_self':0,'close_only':0,'wide_only':0,'both':0,'none':0}
        all_points=[];all_known=[];all_witness=[];primary_unresolved=[];positive_minimum=float('inf')
        current=[]
        for v in current_parts:
            from scipy.spatial import ConvexHull
            current.append(ConvexHull(v).equations)
        envelope=self.protocol['engineering_envelopes']
        for pose in poses:
            q=np.asarray(pose[3:]);rot=Rotation.from_quat(q[[1,2,3,0]]).as_matrix()
            for vertices in parts:
                v=np.asarray(vertices);lo,hi=v.min(0),v.max(0)
                grid=np.asarray([[x,y,z] for x in (lo[0],(lo[0]+hi[0])/2,hi[0]) for y in (lo[1],(lo[1]+hi[1])/2,hi[1]) for z in (lo[2],(lo[2]+hi[2])/2,hi[2])])
                relative=grid@rot.T
                # Pointwise working envelope, so proximal metal extent does not
                # incorrectly inflate the distinct distal contact band.
                angle=envelope['final_TCP_tracking_angle_rad'];yaw=envelope['yaw_rad']
                norm=np.linalg.norm(relative,axis=1)
                angular=np.column_stack([np.sin(angle)*np.linalg.norm(np.delete(relative,j,axis=1),axis=1)+(1-np.cos(angle))*norm for j in range(3)])
                angular[:,:2]+=np.sin(yaw)*abs(relative[:,[1,0]])+(1-np.cos(yaw))*abs(relative[:,:2])
                position=np.array([envelope['XY_m'],envelope['XY_m'],envelope['local_upper_depth_Z_m']])+envelope['final_TCP_tracking_position_m']
                inflation=angular+position
                signs=np.asarray([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)])
                world=(relative[:,None,:]+inflation[:,None,:]*signs[None,:,:]+pose[:3]).reshape(-1,3)
                projections=[]
                for view in views:
                    cal=view['cal'];optical=world@cal['R'].T+cal['t'];uv=optical[:,:2]/optical[:,2,None];uv=uv@cal['K'][:2,:2].T+cal['K'][:2,2]
                    projections.append((optical,uv))
                all_points.append(world)
                for i,point in enumerate(world):
                    identity=samples;samples+=1;known=any(np.max(h[:,:3]@point+h[:,3])<=1e-8 for h in current)
                    all_known.append(known);witness=[False]*len(views);states=[];gaps=[]
                    if known:
                        known_count+=1;witness_counts['known_self']+=1
                        for view in views:per_view[view['frame_id']]['self_known_proprio_skip']+=1
                    else:
                        for j,view in enumerate(views):
                            optical,pixel=projections[j][0][i],projections[j][1][i];depth=view['depth'];gap=None
                            if not np.isfinite(pixel).all() or optical[2]<=0:state='invalid_projection_or_behind_camera'
                            else:
                                x,y=np.rint(pixel).astype(int)
                                if not(0<=x<depth.shape[1] and 0<=y<depth.shape[0]):state='out_of_image'
                                elif not np.isfinite(depth[y,x]):state='invalid_depth'
                                else:
                                    gap=float(depth[y,x]-optical[2]);minimum=min(minimum,gap)
                                    state='observed_ray_free' if gap>0 else 'UNRESOLVED_OCCLUDED_OR_OBSTRUCTED'
                                    witness[j]=gap>0
                            per_view[view['frame_id']][state]+=1;states.append(state);gaps.append(gap)
                        if any(witness):
                            witness_counts['both' if all(witness) and len(witness)>1 else 'close_only' if witness[0] else 'wide_only']+=1
                            positive_minimum=min(positive_minimum,min(gap for gap,free in zip(gaps,witness) if free))
                        else:
                            witness_counts['none']+=1
                            if any(state=='UNRESOLVED_OCCLUDED_OR_OBSTRUCTED' for state in states):occupied+=1
                            else:unknown+=1
                        if states[0]=='UNRESOLVED_OCCLUDED_OR_OBSTRUCTED' and len(primary_unresolved)<256:
                            primary_unresolved.append({'sample_id':identity,'point_world_m':point.tolist(),'categories':states,'gaps_m':gaps,'positive_witness':witness})
                    all_witness.append(witness)
        evidence=self.output/'online'/f'clearance_{self.clearance_index:04d}.npz';self.clearance_index+=1
        np.savez_compressed(evidence,points_world_m=np.concatenate(all_points,axis=0),known_self=np.asarray(all_known,dtype=bool),positive_view_witness=np.asarray(all_witness,dtype=bool))
        return {'passed':unknown==0 and occupied==0,'unknown_samples':unknown,'nonfree_samples':occupied,'samples':samples,'minimum_observed_ray_clearance_m':minimum if np.isfinite(minimum) else None,'minimum_positive_witness_gap_m':positive_minimum if np.isfinite(positive_minimum) else None,'per_view_counts':per_view,'witness_counts':witness_counts,'known_self_samples':known_count,'samples_with_no_free_view':witness_counts['none'],'view_frame_ids':[v['frame_id'] for v in views],'evidence_file':str(evidence.relative_to(self.output)),'primary_unresolved_examples':primary_unresolved,'method':'Fixed inflated box corners/midplanes over2mm/1deg path samples; ANY-view positive measured ray witness; conditional sampled screen, not global collision certification'}

"""Independent measured-depth witnesses for the frozen sampled tool envelope."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from scipy.spatial import ConvexHull
from contact_helpers import rotation,angle_between

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())

def project_free(points,depth,cal):
    K,R,t=[np.asarray(cal[k],float) for k in ['K','R','t']]
    optical=points@R.T+t
    with np.errstate(divide='ignore',invalid='ignore'):
        uv=optical[:,:2]/optical[:,2,None];uv=uv@K[:2,:2].T+K[:2,2]
    valid=np.isfinite(optical).all(1)&np.isfinite(uv).all(1)&(optical[:,2]>0)
    indices=np.flatnonzero(valid);pixels=np.rint(uv[indices]).astype(np.int64)
    inside=(pixels[:,0]>=0)&(pixels[:,0]<depth.shape[1])&(pixels[:,1]>=0)&(pixels[:,1]<depth.shape[0]);indices=indices[inside];pixels=pixels[inside]
    measured=depth[pixels[:,1],pixels[:,0]];good=np.isfinite(measured)&(measured>0);indices=indices[good]
    free=np.zeros(len(points),bool);free[indices]=measured[good]-optical[indices,2]>0
    return free

def self_mask(points,geometry,proprio):
    known=np.zeros(len(points),bool)
    for label in ['left','right']:
        pose=proprio['finger_poses_world_wxyz'][label];rot=rotation(pose[3:7])
        for collider in geometry['fingers'][label]['colliders']:
            vertices=np.asarray(collider['points_finger_m'])@rot.T+pose[:3];planes=ConvexHull(vertices).equations
            for start in range(0,len(points),4096):
                chunk=points[start:start+4096];known[start:start+len(chunk)]|=(chunk@planes[:,:3].T+planes[:,3]).max(1)<=1e-8
    return known

def audit_safety(folder,selected,meta,geometry,science):
    cfg=science['perception']['geometry_safety_view'];guard=cfg['readback_guards'];views=selected['geometry_views'];checks={};details={}
    blob=read(folder/'online/geometry_views.json');expected_config=hashlib.sha256(json.dumps(cfg,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    checks['geometry_view_packet_binding']=blob['views']==views and blob['safety_config_sha256']==meta['geometry_safety_config_sha256']==expected_config and meta['geometry_views_file']=='online/geometry_views.json' and blob['close_pose_restored'] is True and blob['physics_time_s']==selected['measurement_time_s']
    checks['two_fresh_same_clock_geometry_views']=len(views)==2 and len({v['frame_id'] for v in views})==2 and views[0]['frame_id']==selected['frame_id'] and all(v['measurement_time_s']==selected['measurement_time_s'] for v in views)
    depths=[]
    for index,view in enumerate(views):
        cal=view['calibration'];actual=view['actual_sensor_readback'];pose=view['configured_pose'];K=np.asarray(cal['K']);R=np.asarray(cal['R']);t=np.asarray(cal['t'])
        with np.load(folder/view['depth'],allow_pickle=False) as raw:depths.append(raw[view['depth_array_key']])
        depth=depths[-1];image=cv2.imread(str(folder/view['rgb']));size=view['image_size']
        checks[f'geometry_view_{index}_real_RGBD']=sha(folder/view['depth'])==view['depth_sha256'] and image is not None and list(depth.shape[::-1])==list(image.shape[1::-1])==size==cal['image_size']==cfg['image_size']
        optical_R=np.diag([1.,-1.,-1.])@rotation(pose['quaternion_wxyz_opengl']).T
        checks[f'geometry_view_{index}_configured_calibration']=bool(np.allclose(K,cfg['K'],atol=1e-12,rtol=0) and np.allclose(R,optical_R,atol=1e-12,rtol=0) and np.allclose(t,-R@np.asarray(pose['eye_world_m']),atol=1e-12,rtol=0))
        checks[f'geometry_view_{index}_actual_readback']=bool(np.max(abs(np.asarray(actual['K'])-K))<=guard['K_atol_px'] and np.linalg.norm(np.asarray(actual['pos_world_m'])-pose['eye_world_m'])<=guard['position_m'] and angle_between(actual['quat_opengl_wxyz'],pose['quaternion_wxyz_opengl'])<=guard['angle_rad'])
        if index==1:
            # Fixed original design center is z=.1009m; derive independently
            # from the unchanged close configured camera/calibration packet.
            close_pose=read(folder/'online/calibration.json')['views']['camera_0']['eye_world_m']
            close_source=read(Path(__file__).resolve().parents[2]/'stage1_20261025/source_views_v1.json');close_view=next(v for v in close_source['views'] if v['id']=='diagnostic_table_top')
            center=np.asarray(close_pose)-close_view['eye_offset_m'];eye=center+cfg['view']['eye_offset_m'];target=center+cfg['view']['target_offset_m']
            forward=(target-eye)/np.linalg.norm(target-eye);up=np.asarray(cfg['view']['up_world']);right=np.cross(forward,up);right/=np.linalg.norm(right);camera_up=np.cross(right,forward);expected_R=np.stack([right,-camera_up,forward])
            checks['geometry_safety_fixed_existing_pose']=bool(np.allclose(pose['eye_world_m'],eye,atol=1e-12,rtol=0) and np.allclose(R,expected_R,atol=1e-12,rtol=0))
        details[view['frame_id']]={'depth_sha256':view['depth_sha256'],'image_size':size,'measurement_time_s':view['measurement_time_s']}
    if selected.get('candidate') is None:return checks,{'status':'NO_SELECTED_CLEARANCE','views':details}
    clearance=selected['clearance']
    with np.load(folder/clearance['evidence_file'],allow_pickle=False) as raw:points=raw['points_world_m'];known=raw['known_self'];witness=raw['positive_view_witness']
    checks['clearance_numeric_packet_complete']=points.shape==(clearance['samples'],3) and np.isfinite(points).all() and known.dtype==bool and known.shape==(len(points),) and witness.dtype==bool and witness.shape==(len(points),2) and clearance['view_frame_ids']==[v['frame_id'] for v in views]
    actual_known=self_mask(points,geometry,meta['initial_proprioception']);checks['clearance_self_skip_independently_equal']=bool(np.array_equal(known,actual_known) and int(known.sum())==clearance['known_self_samples'])
    measured=np.column_stack([project_free(points,depth,view['calibration']) for view,depth in zip(views,depths)]);measured[known]=False
    checks['clearance_each_positive_witness_measured']=bool(np.array_equal(witness,measured))
    checks['clearance_all_nonself_have_positive_witness']=bool(np.all(known|measured.any(1)) and clearance['samples_with_no_free_view']==0 and clearance['passed'] is True)
    return checks,{'status':'INDEPENDENT_DEPTH_WITNESSES_CHECKED','views':details,'samples':len(points),'self_samples':int(known.sum()),'close_only':int((~known&measured[:,0]&~measured[:,1]).sum()),'wide_only':int((~known&~measured[:,0]&measured[:,1]).sum()),'both':int((~known&measured.all(1)).sum()),'no_free_view':int((~known&~measured.any(1)).sum()),'scope':'Conditional frozen sampled-envelope depth evidence, not continuous-volume/global collision certification.'}

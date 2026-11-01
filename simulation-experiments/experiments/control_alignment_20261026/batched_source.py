"""Read-only world-pose batching with explicit name/path/row correspondence."""
import copy
import numpy as np


class SourcePoseEquivalenceError(RuntimeError):
    """Preserve the failed comparison without weakening its acceptance gate."""
    def __init__(self,proof):
        super().__init__('Batched/per-asset startup source poses differ')
        self.proof=copy.deepcopy(proof)


def _array(value):
    if hasattr(value,'detach'):value=value.detach()
    if hasattr(value,'cpu'):value=value.cpu()
    if hasattr(value,'numpy'):value=value.numpy()
    return np.asarray(value)


def _poses(value,count):
    result=np.array(_array(value),dtype=np.float64,copy=True)
    if result.shape!=(count,7) or not np.isfinite(result).all() or np.any(np.linalg.norm(result[:,3:],axis=1)==0):
        raise RuntimeError('Finite nonzero-quaternion source poses required')
    return result


def quaternion_angles(a,b):
    """Float64, sign-invariant quaternion angles, without acos near-one loss."""
    a=np.asarray(a,dtype=np.float64);b=np.asarray(b,dtype=np.float64)
    a=a/np.linalg.norm(a,axis=1)[:,None];b=b/np.linalg.norm(b,axis=1)[:,None]
    distance=np.minimum(np.linalg.norm(a-b,axis=1),np.linalg.norm(a+b,axis=1))
    return 4*np.arcsin(np.clip(distance/2,0,1))


def capture_startup_comparison(scene,names,clock,evidence_sink=None):
    """Compare property/cache and two fresh getters without stepping or writes.

    Batch raw rows stay in actual view order; only poses_world_wxyz is reordered
    into sorted names. Differences are returned, never hidden by an equality
    exception. Cache timestamps are observations of implementation metadata.
    """
    names=list(names)
    if not names or any(not isinstance(n,str) or not n for n in names) or len(set(names))!=len(names):
        raise ValueError('Unique source names required')
    names=sorted(names);count=len(names);expected=[]
    for name in names:
        paths=list(map(str,scene[name].root_physx_view.prim_paths))
        if len(paths)!=1 or not paths[0].startswith('/'):raise RuntimeError('Exact single actor root path required')
        expected.append(paths[0])
    if len(set(expected))!=count:raise RuntimeError('Duplicate expected source root path')
    def stamp(value):
        if value is None:return None
        value=float(value)
        return value if np.isfinite(value) else None
    channels={}
    partial={'schema':'pose-reader-startup-partial-v1','names':names,'expected_root_paths':expected,
             'count':count,'frame':'world','subspace_roots':'/','channels':channels}
    def serializable(value):
        if isinstance(value,dict):return {key:serializable(item) for key,item in value.items()}
        if isinstance(value,list):return [serializable(item) for item in value]
        if isinstance(value,float) and not np.isfinite(value):return {'nonfinite_scalar':'nan' if np.isnan(value) else 'inf' if value>0 else '-inf'}
        return value
    def emit(stage):
        if evidence_sink is not None:evidence_sink(serializable(copy.deepcopy({**partial,'capture_stage':stage})))
    def packet(raw,layout,before,after):
        return {'raw_layout':layout,'raw_dtype':str(raw.dtype),'raw_poses':raw.tolist(),
            'clock_before_s':before,'clock_after_s':after}
    before=float(clock());cache_stamps=[];sim_stamps=[];cache_after=[];sim_after=[];present=[];rows=[]
    for name in names:
        data=scene[name].data
        buffer=getattr(data,'_root_link_pose_w',None)
        cache_stamps.append(stamp(getattr(buffer,'timestamp',None)))
        present.append(getattr(buffer,'data',None) is not None)
        sim_stamps.append(stamp(getattr(data,'_sim_timestamp',None)))
        rows.append(np.array(_array(data.root_link_pose_w[0]),copy=True))
        cache_after.append(stamp(getattr(getattr(data,'_root_link_pose_w',None),'timestamp',None)))
        sim_after.append(stamp(getattr(data,'_sim_timestamp',None)))
    cached=packet(np.stack(rows),'xyz_wxyz',before,float(clock()))
    cached.update(cache_timestamp_before=cache_stamps,sim_timestamp_before=sim_stamps,
        cache_timestamp_after=cache_after,sim_timestamp_after=sim_after,cache_buffer_present_before=present)
    channels['cached']=cached;emit('cached_raw')
    cached['poses_world_wxyz']=_poses(np.asarray(cached['raw_poses']),count).tolist()
    before=float(clock());rows=[]
    for name in names:rows.append(np.array(_array(scene[name].root_physx_view.get_transforms()[0]),copy=True))
    direct_raw=np.stack(rows);direct=packet(direct_raw,'xyz_xyzw',before,float(clock()))
    channels['direct']=direct;emit('direct_raw')
    direct['poses_world_wxyz']=_poses(direct_raw[:,[0,1,2,6,3,4,5]],count).tolist()
    before=float(clock())
    from omni.physics import tensors
    simulation=tensors.create_simulation_view('torch');simulation.set_subspace_roots('/')
    view=simulation.create_rigid_body_view(expected);actual=list(map(str,view.prim_paths))
    raw=np.array(_array(view.get_transforms()),copy=True)
    batch=packet(raw,'xyz_xyzw',before,float(clock()));channels['batch']=batch
    partial.update(actual_view_prim_paths=actual,actual_view_count=int(view.count));emit('batch_raw_before_path_validation')
    if view.count!=count or len(actual)!=count or len(set(actual))!=count or set(actual)!=set(expected):
        raise RuntimeError('Batched source actor paths differ from the exact requested set')
    lookup={path:i for i,path in enumerate(actual)};indices=[lookup[path] for path in expected]
    batch['poses_world_wxyz']=_poses(raw[indices][:,[0,1,2,6,3,4,5]],count).tolist()
    comparisons={}
    for a,b in (('cached','direct'),('cached','batch'),('direct','batch')):
        left=np.asarray(channels[a]['poses_world_wxyz']);right=np.asarray(channels[b]['poses_world_wxyz'])
        position=float(np.max(np.linalg.norm(left[:,:3]-right[:,:3],axis=1)))
        angle=float(np.max(quaternion_angles(left[:,3:],right[:,3:])))
        comparisons[a+'_'+b]={'maximum_position_error_m':position,'maximum_angle_error_rad':angle,
                             'passed':bool(position<=1e-9 and angle<=1e-7)}
    return {'schema':'pose-reader-startup-v1','names':names,'expected_root_paths':expected,
        'actual_view_prim_paths':actual,'row_indices_in_name_order':indices,'count':count,
        'subspace_roots':'/','frame':'world','channels':channels,'comparisons':comparisons,
        'limits':{'position_m':1e-9,'angle_rad':1e-7},'no_step_called':True,'snapshot_copy':True}


class BatchedSourcePoses:
    def __init__(self,scene,names):
        names=list(names)
        if not names or any(not isinstance(n,str) or not n for n in names) or len(set(names))!=len(names):
            raise ValueError('Unique source names required')
        self.names=sorted(names);expected=[]
        for name in self.names:
            paths=list(map(str,scene[name].root_physx_view.prim_paths))
            if len(paths)!=1 or not paths[0].startswith('/'):raise RuntimeError('Exact single actor root path required')
            expected.append(paths[0])
        if len(set(expected))!=len(expected):raise RuntimeError('Duplicate expected source root path')
        from omni.physics import tensors
        self.simulation_view=tensors.create_simulation_view('torch')
        self.simulation_view.set_subspace_roots('/')
        self.view=self.simulation_view.create_rigid_body_view(expected)
        actual=list(map(str,self.view.prim_paths));count=len(self.names)
        if self.view.count!=count or len(actual)!=count or len(set(actual))!=count or set(actual)!=set(expected):
            raise RuntimeError('Batched source actor paths differ from the exact requested set')
        lookup={path:i for i,path in enumerate(actual)}
        self.indices=np.asarray([lookup[path] for path in expected],dtype=np.int64)
        # The property may retain requested poses after initialization writes.
        # Compare two fresh PhysX readers; retain cache differences separately.
        cached=_poses(np.stack([np.array(_array(scene[name].data.root_link_pose_w[0]),copy=True) for name in self.names]),count)
        direct_raw=np.stack([np.array(_array(scene[name].root_physx_view.get_transforms()[0]),copy=True) for name in self.names])
        direct=_poses(direct_raw[:,[0,1,2,6,3,4,5]],count)
        batch_raw=np.array(_array(self.view.get_transforms()),copy=True)
        if batch_raw.shape!=(count,7):raise RuntimeError('Unexpected batched transform shape')
        new=_poses(batch_raw[self.indices][:,[0,1,2,6,3,4,5]],count)
        def comparison(a,b):
            position=float(np.max(np.linalg.norm(a[:,:3]-b[:,:3],axis=1)))
            angle=float(np.max(quaternion_angles(a[:,3:],b[:,3:])))
            return {'maximum_position_error_m':position,'maximum_angle_error_rad':angle,
                    'passed':bool(position<=1e-9 and angle<=1e-7)}
        fresh=comparison(direct,new);passed=fresh['passed']
        self.proof={'names':self.names.copy(),'expected_root_paths':expected,'actual_view_prim_paths':actual,
            'row_indices_in_name_order':self.indices.tolist(),'count':count,'subspace_roots':'/','frame':'world',
            'getter_layout':'xyz_xyzw','returned_layout':'xyz_wxyz','snapshot_copy':True,
            'no_step_called_by_reader':True,'proof_version':2,'reference_reader':'fresh_per_asset_PhysX_get_transforms',
            'direct_raw_poses_world_xyzw':direct_raw.tolist(),'direct_poses_world_wxyz':direct.tolist(),
            'batch_raw_poses_world_xyzw':batch_raw.tolist(),'cached_poses_world_wxyz':cached.tolist(),
            'cached_direct_comparison':comparison(cached,direct),'cached_batch_comparison':comparison(cached,new),
            'new_poses_world_wxyz':new.tolist(),
            'maximum_position_error_m':fresh['maximum_position_error_m'],'maximum_angle_error_rad':fresh['maximum_angle_error_rad'],
            'position_tolerance_m':1e-9,'angle_tolerance_rad':1e-7,'equivalence_passed':passed}
        if not passed:raise SourcePoseEquivalenceError(self.proof)

    def read(self):
        raw=_array(self.view.get_transforms())
        if raw.shape!=(len(self.names),7):raise RuntimeError('Unexpected batched transform shape')
        reordered=raw[self.indices][:,[0,1,2,6,3,4,5]]
        return _poses(reordered,len(self.names))

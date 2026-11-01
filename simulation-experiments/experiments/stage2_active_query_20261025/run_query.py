"""One motion-free active-shape observation; never reopens closed contact gates."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
CONTACT=ROOT/'experiments/stage2_contact_20261025'
sys.path[:0]=[str(ROOT),str(CONTACT),str(ROOT/'experiments/stage2_idle_20261025')]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')


def registered_vertices(config,label):
    import numpy as np
    data=(ROOT/config['stl']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=config['stl_sha256']:raise RuntimeError('Frozen STL changed')
    count=struct.unpack_from('<I',data,80)[0]
    if len(data)!=84+50*count:raise RuntimeError('Unexpected STL encoding')
    raw=np.asarray([list(struct.iter_unpack('<fff',data[84+50*i+12:84+50*i+48])) for i in range(count)])
    vertices,inverse=np.unique(raw.reshape(-1,3),axis=0,return_inverse=True)
    r=config['registration'][label];a=math.radians(r['rotation_z_deg'])
    rotation=np.array([[math.cos(a),-math.sin(a),0],[math.sin(a),math.cos(a),0],[0,0,1]])
    return vertices*config['stl_unit_m']@rotation.T+r['translation_m'],inverse.reshape(-1,3),rotation


def main(proxy_author=None,protocol_path=None,observation_hook=None):
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--output',type=Path,required=True)
    args,remaining=parser.parse_known_args();output=args.output.resolve()
    sys.argv=[sys.argv[0],*remaining,'--output',str(output)]
    if os.environ.get('ROBO_PUEUE_JOB')!='1' or os.environ.get('OSQP_EPSILON')!='1e-4':raise RuntimeError('Default Pueue and baseline epsilon required')
    protocol=json.loads((Path(protocol_path) if protocol_path else HERE/'protocol.json').read_text());config=json.loads((CONTACT/'proxy_config.json').read_text())
    reference=json.loads((CONTACT/'proxy_reference.json').read_text())
    for path,digest in protocol['input_sha256'].items():
        if sha(ROOT/path)!=digest:raise RuntimeError('Frozen input changed: '+path)
    from experiments.final_workcell_20261024 import scene as final_scene,render_core
    from geometry import BODIES,metadata_scalar
    original_factory=final_scene.make_env_cfg;original_init=None;authored={};factory_record={}

    def construct(scene,cfg):
        import numpy as np
        from pxr import UsdGeom,UsdPhysics,PhysxSchema,UsdShade,Gf
        from isaaclab.sim import get_current_stage
        original_init(scene,cfg);stage=get_current_stage()
        if scene['robot'].is_initialized:raise RuntimeError('Proxy must be authored before play')
        if proxy_author is not None:
            authored.update(proxy_author(stage,ROOT,config,output,scene))
        else:
            for label in ('left','right'):
                vertices,triangles,_=registered_vertices(config,label)
                path=BODIES[label]+'/collisions/mesh_3';prim=stage.GetPrimAtPath(path)
                if prim.GetTypeName()!='Cube' or prim.IsInstanceProxy():raise RuntimeError('Expected stock mesh_3 Cube only')
                material,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics');old_material=str(material.GetPath())
                operations=UsdGeom.Xformable(prim).GetOrderedXformOps();mesh=UsdGeom.Mesh.Define(stage,path)
                UsdGeom.Xformable(mesh).ClearXformOpOrder()
                for operation in operations:operation.GetAttr().Block()
                mesh.CreatePointsAttr(vertices.tolist());mesh.CreateFaceVertexCountsAttr([3]*len(triangles))
                mesh.CreateFaceVertexIndicesAttr(triangles.ravel().tolist());mesh.CreateSubdivisionSchemeAttr('none')
                mesh.CreateExtentAttr([vertices.min(axis=0).tolist(),vertices.max(axis=0).tolist()])
                UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr(config['collision']['approximation'])
                api=PhysxSchema.PhysxConvexDecompositionCollisionAPI.Apply(prim)
                for name,value in config['collision'].items():
                    if name!='approximation':getattr(api,'Create'+name[0].upper()+name[1:]+'Attr')(value)
                readback={name:getattr(api,'Get'+name[0].upper()+name[1:]+'Attr')().Get() for name in config['collision'] if name!='approximation'}
                for name,value in readback.items():
                    intended=config['collision'][name]
                    if (abs(value-intended)>config['schema_float_readback_atol'] if isinstance(intended,float) else value!=intended):raise RuntimeError('Cook attribute mismatch')
                relative=UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(0)*UsdGeom.Xformable(stage.GetPrimAtPath(BODIES[label])).ComputeLocalToWorldTransform(0).GetInverse()
                if np.max(abs(np.asarray([list(row) for row in relative])-np.eye(4)))>1e-9:raise RuntimeError('Proxy transform not identity')
                material,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
                if str(material.GetPath())!=old_material:raise RuntimeError('Pad material binding changed')
                authored[label]={'path':path,'vertices_finger_m':vertices.tolist(),'triangles':triangles.tolist(),
                    'material':old_material,'cook_readback':readback,'transform_finger':list(map(list,relative))}
        control=protocol['query_control'];cube=UsdGeom.Cube.Define(stage,control['path']);cube.CreateSizeAttr(control['size_m'])
        cube.AddTranslateOp().Set(Gf.Vec3d(*control['center_world_m']));UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        save(output/'authored_proxy.json',{'config':config,'tips':authored,'control':control,'query_descriptor_guard':'Not invoked; observation only, oldG remains failed'})

    def factory(cfg,capture=False):
        nonlocal original_init
        from isaaclab import scene as module
        from isaacsim.core.utils.extensions import enable_extension
        if not enable_extension('omni.isaac.dynamic_control'):raise RuntimeError('Installed runtime getter unavailable')
        env=original_factory(cfg,capture=capture);full_before=env.sim.to_dict();before=env.sim.physx.to_dict()
        if full_before['enable_scene_query_support'] is not False or before['solver_type']!=1:raise RuntimeError('Unexpected pinned baseline query/solver config')
        env.sim.physx.solver_type=0;env.sim.enable_scene_query_support=True
        expected={**full_before,'enable_scene_query_support':True,'physx':{**full_before['physx'],'solver_type':0}}
        if env.sim.to_dict()!=expected:raise RuntimeError('Unexpected full SimulationCfg change')
        factory_record.update(before=before,after=env.sim.physx.to_dict(),
            enable_scene_query_support_configured_before=full_before['enable_scene_query_support'],
            enable_scene_query_support_configured_after=env.sim.enable_scene_query_support,
            full_sim_cfg_only_declared_changes_verified=True,
            changed_paths=['physx.solver_type','enable_scene_query_support'],
            nominal_joint_configuration=dict(env.scene.robot.init_state.joint_pos))
        original_init=module.InteractiveScene.__init__;module.InteractiveScene.__init__=construct
        return env

    def query(**context):
        import numpy as np
        from pxr import UsdGeom,UsdPhysics,Gf
        from isaaclab.sim import get_current_stage
        from omni.physx import get_physx_scene_query_interface
        from omni.isaac.dynamic_control import _dynamic_control
        import bricksim.core as core
        from diagnose_breakage import threshold_snapshot
        sim,scene,robot=context['sim'],context['scene'],context['robot'];stage=get_current_stage()
        names=['plate_source']+[b.name for b in context['bricks']];expected={'/World/envs/env_0/'+n for n in names}
        def snapshot():
            return {'time_s':float(sim.current_time),'q':robot.root_physx_view.get_dof_positions().cpu().numpy().tolist(),
                'qdot':robot.root_physx_view.get_dof_velocities().cpu().numpy().tolist(),
                'source':{n:{'pose':scene[n].root_physx_view.get_transforms().cpu().numpy().tolist(),
                    'velocity':scene[n].root_physx_view.get_velocities().cpu().numpy().tolist()} for n in names}}
        initial=snapshot()
        extra_initial=observation_hook('initial',context) if observation_hook else None
        parts,links=core.compute_connected_component('/World/envs/env_0/plate_source')
        if set(parts)!=expected or len(links)!=930 or len(names)!=301:raise RuntimeError('Full native source inventory mismatch')
        if threshold_snapshot(core.get_breakage_thresholds())!=protocol['native_breakage']:raise RuntimeError('Native break settings changed')
        assembly=core.get_assembly_thresholds()
        if {'enabled':assembly.enabled,'required_force':assembly.required_force}!=protocol['native_assembly']:raise RuntimeError('Native assembly settings changed')
        dc=_dynamic_control.acquire_dynamic_control_interface();runtime={}
        for name in names[1:]:
            p=dc.get_rigid_body_properties(dc.get_rigid_body('/World/envs/env_0/'+name))
            runtime[name]=[int(p.solver_position_iteration_count),int(p.solver_velocity_iteration_count)]
        if any(v!=[32,4] for v in runtime.values()):raise RuntimeError('Actor32/4 mismatch')
        scenes=[{'path':str(p.GetPath()),'solver':p.GetAttribute('physxScene:solverType').Get(),
            'enable_scene_query_support':p.GetAttribute('physxScene:enableSceneQuerySupport').Get()} for p in stage.Traverse() if p.IsA(UsdPhysics.Scene)]
        support=sim.get_physics_context().get_enable_scene_query_support()
        save(output/'prequery_setup.json',{'factory':factory_record,'physics_scenes':scenes,
            'scene_query_support_runtime':support,'readback_scope':'SDKPhysicsContext getter reads scene attribute; positive controls still required'})
        if not scenes or any(p['solver']!='PGS' for p in scenes):raise RuntimeError('Actual scene not PGS')
        if support is not True or any(p['enable_scene_query_support'] is not True for p in scenes):raise RuntimeError('Scene query support not enabled')
        api=get_physx_scene_query_interface();records=[];control=protocol['query_control']
        def vec(v):return [float(v.x),float(v.y),float(v.z)]
        def hit_record(hit,ray):
            result={'collision':str(hit.collision),'rigid_body':str(hit.rigid_body),'protoIndex':int(hit.protoIndex)}
            if ray:result.update(position_world_m=vec(hit.position),normal_world=vec(hit.normal),distance_m=float(hit.distance),face_index=int(hit.face_index),material=str(hit.material))
            return result
        def ray(label,origin,direction,length,metadata=None):
            hits=[]
            def callback(hit):hits.append(hit_record(hit,True));return True
            found=api.raycast_all(Gf.Vec3f(*origin),Gf.Vec3f(*direction),float(length),callback,False)
            record={'kind':'ray','id':label,'origin_world_m':list(map(float,origin)),'direction_world':list(map(float,direction)),
                'length_m':float(length),'api_return_bool':bool(found),'callback_count':len(hits),'hits':hits,**(metadata or {})}
            records.append(record);return record
        def overlap(label,point,radius,metadata=None):
            hits=[]
            def callback(hit):hits.append(hit_record(hit,False));return True
            count=api.overlap_sphere(float(radius),Gf.Vec3f(*point),callback,False)
            record={'kind':'overlap','id':label,'center_world_m':list(map(float,point)),'radius_m':radius,
                'api_return_count':int(count),'callback_count':len(hits),'hits':hits,**(metadata or {})}
            records.append(record);return record
        positive=ray('control_hit',control['ray_hit_origin_m'],control['ray_direction'],control['ray_length_m'])
        negative=ray('control_miss',np.asarray(control['ray_hit_origin_m'])+control['miss_offset_world_m'],control['ray_direction'],control['ray_length_m'])
        inside=overlap('control_inside',control['center_world_m'],control['overlap_radius_m'])
        outside=overlap('control_outside',np.asarray(control['center_world_m'])+control['miss_offset_world_m'],control['overlap_radius_m'])
        save(output/'queries.json',records)
        control_hits=[h for h in positive['hits'] if h['collision']==control['path']]
        if len(control_hits)!=1 or not positive['api_return_bool'] or negative['hits'] or negative['api_return_bool'] or inside['api_return_count']!=1 or inside['callback_count']!=1 or inside['hits'][0]['collision']!=control['path'] or outside['api_return_count'] or outside['hits']:
            raise RuntimeError('Active query positive/miss/path/count controls failed')
        if abs(control_hits[0]['distance_m']-control['expected_hit_distance_m'])>control['distance_tolerance_m'] or np.max(abs(np.asarray(control_hits[0]['normal_world'])-[0,0,1]))>control['normal_component_tolerance']:
            raise RuntimeError('Active query metric/normal control failed')
        frames={};hand=UsdGeom.Xformable(stage.GetPrimAtPath('/World/envs/env_0/Robot/fr3_hand')).ComputeLocalToWorldTransform(0)
        for label in ('left','right'):
            path=BODIES[label];xf=UsdGeom.Xformable(stage.GetPrimAtPath(path)).ComputeLocalToWorldTransform(0)
            q=xf.ExtractRotationQuat();usd=np.r_[np.asarray(xf.ExtractTranslation()),q.GetReal(),q.GetImaginary()]
            physics=robot.data.body_link_pose_w[0,robot.body_names.index(path.rsplit('/',1)[-1])].cpu().numpy()
            if np.linalg.norm(usd[:3]-physics[:3])>protocol['frame_verification']['physics_vs_USD_position_m'] or render_core.quaternion_error(usd[3:],physics[3:])>protocol['frame_verification']['physics_vs_USD_orientation_rad']:raise RuntimeError('Finger frame USD/physics mismatch')
            frames[label]={'world_from_finger':list(map(list,xf)),'physics_body_link_pose_world_wxyz':physics.tolist(),'USD_pose_world_wxyz':usd.tolist()}
            v,_,rotation=registered_vertices(config,label);lo,hi=v.min(axis=0),v.max(axis=0)
            def world(p):return list(xf.Transform(Gf.Vec3d(*p)))
            def direction(d):return list(xf.TransformDir(Gf.Vec3d(*d)).GetNormalized())
            for ix,x in enumerate(protocol['contact_ray_grid']['hand_x_offsets_m']):
                for iz,z in enumerate(protocol['contact_ray_grid']['hand_z_offsets_m']):
                    center=np.asarray(reference['coupon_center_hand_m'])+[x,0,z]
                    local=np.asarray(xf.GetInverse().Transform(hand.Transform(Gf.Vec3d(*center))))
                    local[1]=lo[1]-.02 if label=='left' else hi[1]+.02;d=[0,1 if label=='left' else -1,0]
                    ray(f'{label}_grid_{ix}_{iz}',world(local),direction(d),hi[1]-lo[1]+.04,{'tip':label,'origin_finger_m':local.tolist(),'direction_finger':d,'group':'contact_grid'})
            for axis in range(3):
                for sign in (-1,1):
                    origin=(lo+hi)/2;origin[axis]=(lo[axis]-.02) if sign==1 else (hi[axis]+.02)
                    d=np.zeros(3);d[axis]=sign
                    ray(f'{label}_bbox_{axis}_{sign}',world(origin),direction(d),hi[axis]-lo[axis]+.04,{'tip':label,'origin_finger_m':origin.tolist(),'direction_finger':d.tolist(),'group':'bounds_axis'})
            f=config['fidelity'];r=config['registration'][label]
            for x in f['bore_x_cad_mm']:
                for k in range(f['bore_witnesses_per_x']):
                    offset=np.zeros(2) if k==0 else f['bore_witness_radius_mm']*np.array([math.cos((k-1)*math.pi/4),math.sin((k-1)*math.pi/4)])
                    point=np.r_[x,np.asarray(f['bore_center_cad_yz_mm'])+offset]*config['stl_unit_m']@rotation.T+r['translation_m']
                    overlap(f'{label}_bore_{x}_{k}',world(point),protocol['bore_overlaps']['radius_m'],{'tip':label,'center_finger_m':point.tolist(),'group':'bore_witness'})
            save(output/'queries.json',records)
        extra_terminal=observation_hook('terminal',context) if observation_hook else None
        terminal=snapshot();terminal_parts,terminal_links=core.compute_connected_component('/World/envs/env_0/plate_source')
        save(output/'query_report.json',{'schema':protocol['schema'],'observation_complete':True,'proceed_gate_passed':False,
            'R3_G_status':'FAILED and closed; this does not authorize D/R','old_bounds_failure_m':protocol['old_bounds_failure_m'],
            'initial':initial,'terminal':terminal,'observation_extra':{'initial':extra_initial,'terminal':extra_terminal},'frames':frames,'world_from_hand':list(map(list,hand)),'authored':'authored_proxy.json','queries':'queries.json',
            'source_parts':sorted(parts),'native_connections':sorted(links),'runtime_source32_4':runtime,'physics_scenes':scenes,'scene_query_support_runtime':support,
            'factory':factory_record,'native_core_sha256':sha(core.__file__),'dt_s':sim.get_physics_dt(),
            'OSQP_EPSILON':os.environ['OSQP_EPSILON'],'preassembly_initialization_steps':1,'measured_postassembly_physics_steps':0,
            'queries_do_not_move_actors':initial==terminal,'graph_unchanged':set(parts)==set(terminal_parts) and set(links)==set(terminal_links)})
        if initial!=terminal or set(parts)!=set(terminal_parts) or set(links)!=set(terminal_links):raise RuntimeError('Motion-free query changed state/graph')
        save(output/'active_query_complete.json',{'observation_complete':True,'proceed_gate_passed':False,'measured_postassembly_physics_steps':0})
    final_scene.make_env_cfg=factory
    render_core.main(postassembly_hook=query)


if __name__=='__main__':main()

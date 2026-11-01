"""One eccentric, native two-brick diagnostic; never a full-stack replacement."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def metadata_scalar(value):
    """Represent SDK attribute infinities explicitly; never process physical arrays."""
    if isinstance(value, float) and not math.isfinite(value):
        return {'nonfinite_scalar': 'nan' if math.isnan(value) else 'inf' if value > 0 else '-inf'}
    return value


def quaternion_error(a, b):
    import numpy as np
    a, b = np.asarray(a, float), np.asarray(b, float)
    return float(2*np.arccos(np.clip(abs(a@b)/(np.linalg.norm(a)*np.linalg.norm(b)), 0, 1)))


def check_geometry():
    from challenge2.layout import Brick, connection_offset
    lower = Brick('lower', 0, 0, 0, 0, 'tan')
    upper = Brick('upper', -1, 1, 1, 1, 'tan')
    assert connection_offset(lower, upper, 32) == ((1, 1), 1)
    assert min(4, 1)-max(0, -1) == 1 and min(2, 5)-max(0, 1) == 1


def run(args, protocol):
    import importlib.metadata
    import inspect
    import numpy as np
    import torch
    from pxr import UsdGeom, UsdPhysics, Gf
    from isaaclab.assets import RigidObjectCfg
    from isaaclab.scene import InteractiveScene, InteractiveSceneCfg
    from isaaclab.sim import SimulationCfg, SimulationContext, RigidBodyPropertiesCfg, get_current_stage
    import bricksim.core as core
    from bricksim.mdp.brick_part import BrickPartCfg, set_brick_part_xform
    from bricksim.mdp.connection_thresholds import configure_assembly_thresholds, configure_breakage_thresholds

    check_geometry()
    if sha(core.__file__) != protocol['native_core_sha256']:
        raise RuntimeError('Installed native binary differs from the frozen baseline')
    package_version = importlib.metadata.version('bricksim')
    if package_version != protocol['native_package_version']:
        raise RuntimeError('Installed package version differs from protocol')
    for path, digest in protocol['frozen_helpers'].items():
        if sha(ROOT/path) != digest: raise RuntimeError('Frozen helper changed: '+path)
    names = ['lower', 'upper']
    paths = ['/World/envs/env_0/'+name for name in names]
    poses = protocol['root_poses_wxyz']
    configure_assembly_thresholds(enabled=False)
    configure_breakage_thresholds(**protocol['breakage_thresholds'])
    cfg = InteractiveSceneCfg(num_envs=1, env_spacing=3, replicate_physics=False)
    for name in names:
        anchored = name == 'lower'
        setattr(cfg, name, RigidObjectCfg(prim_path='{ENV_REGEX_NS}/'+name,
            spawn=BrickPartCfg(dimensions=(4, 2, 3), color=(185, 145, 100),
                rigid_props=RigidBodyPropertiesCfg(kinematic_enabled=anchored,
                    disable_gravity=anchored, solver_position_iteration_count=32,
                    solver_velocity_iteration_count=4, max_depenetration_velocity=.2)),
            init_state=RigidObjectCfg.InitialStateCfg(pos=tuple(poses[name][:3]), rot=tuple(poses[name][3:]))))
    sim_cfg = SimulationCfg(device='cpu', dt=protocol['dt_s'], use_fabric=False, gravity=tuple(protocol['gravity_m_s2']))
    sim_cfg.physx.solver_type = {'PGS':0, 'TGS':1}[protocol['solver']['type']]
    sim = SimulationContext(sim_cfg)
    sim.get_physics_context().set_physx_update_transformations_settings(update_to_usd=True)
    stage = get_current_stage()
    scene = InteractiveScene(cfg)
    sim.reset(); scene.reset()
    if abs(sim.get_physics_dt()-protocol['dt_s']) > 1e-12:
        raise RuntimeError('Physics dt differs from protocol')
    if float(scene.env_origins[0].abs().max()) > 1e-8:
        raise RuntimeError('Fixture requires identity environment origin')
    # reset internally advances free bodies. Restore BOTH representations once,
    # before native authoring; there are no subsequent state/velocity resets.
    for name, path in zip(names, paths):
        target = torch.tensor([[*poses[name], *([0.]*6)]], dtype=torch.float32, device=scene[name].device)
        scene[name].write_root_state_to_sim(target)
        set_brick_part_xform(stage.GetPrimAtPath(path), poses[name][:3], poses[name][3:])

    def states():
        rows = []
        for name in names:
            view = scene[name].root_physx_view
            p = view.get_transforms()[0].cpu().numpy()
            rows.append(np.r_[p[:3], p[6], p[3:6], view.get_velocities()[0].cpu().numpy()])
        return np.asarray(rows, float)

    def verify_initial():
        current = states()
        for i, (name, path) in enumerate(zip(names, paths)):
            transform = UsdGeom.Xformable(stage.GetPrimAtPath(path)).ComputeLocalToWorldTransform(0)
            q = transform.ExtractRotationQuat()
            actual_usd = [*transform.ExtractTranslation(), q.GetReal(), *q.GetImaginary()]
            for pose in (current[i, :7], actual_usd):
                if np.linalg.norm(np.asarray(pose[:3])-poses[name][:3]) > 2e-6 or quaternion_error(pose[3:7], poses[name][3:]) > 1e-4:
                    raise RuntimeError('PhysX/USD configured-pose mismatch: '+name)
            if np.max(np.abs(current[i, 7:])) > 1e-7:
                raise RuntimeError('Initial velocity is nonzero')
        return current

    initial = verify_initial()
    # The native helper returns (WXYZ quaternion, position), not the reverse.
    connection_args = (paths[0], 1, paths[1], 0, (1, 1), 1)
    q, p = core.compute_connection_transform(*connection_args)
    if np.linalg.norm(np.asarray(p)-poses['upper'][:3]) > 2e-6 or quaternion_error(q, poses['upper'][3:]) > 1e-4:
        raise RuntimeError('Native connection transform disagrees with the specified one-stud fixture')
    local = core.compute_connection_local_transform(*connection_args)
    world_interfaces = []
    for name, (local_q, local_p) in zip(names, local):
        if not np.isfinite([*local_q, *local_p]).all():
            raise RuntimeError('Invalid native local interface transform')
        body_q = np.asarray(poses[name][3:]); offset = np.asarray(local_p)
        point = np.asarray(poses[name][:3])+offset+2*np.cross(body_q[1:], np.cross(body_q[1:], offset)+body_q[0]*offset)
        orientation = Gf.Quatd(*poses[name][3:])*Gf.Quatd(*local_q)
        world_interfaces.append([*point, orientation.GetReal(), *orientation.GetImaginary()])
    if (np.linalg.norm(np.asarray(world_interfaces[0][:3])-world_interfaces[1][:3]) > 2e-6
        or quaternion_error(world_interfaces[0][3:], world_interfaces[1][3:]) > 1e-4):
        raise RuntimeError('Native local interface frames do not coincide; no hand compensation allowed')
    if any(core.compute_connected_component(path)[1] for path in paths):
        raise RuntimeError('Unexpected connection before manual authoring')
    connection = core.create_connection(*connection_args)
    verify_initial()
    parts, links = core.compute_connected_component(paths[0])
    if set(parts) != set(paths) or links != [connection]:
        raise RuntimeError('Fixture does not contain exactly two native parts and one link')
    rigid = [str(prim.GetPath()) for prim in stage.Traverse() if prim.HasAPI(UsdPhysics.RigidBodyAPI)]
    colliders = [str(prim.GetPath()) for prim in stage.Traverse() if prim.HasAPI(UsdPhysics.CollisionAPI)]
    if set(rigid) != set(paths) or any(not any(p.startswith(root+'/') or p == root for root in paths) for p in colliders):
        raise RuntimeError('Unexpected rigid actor/collider outside the two-brick fixture')
    fields = protocol['breakage_thresholds'].keys()
    threshold_snapshot = lambda: {key: getattr(core.get_breakage_thresholds(), key) for key in fields}
    if threshold_snapshot() != protocol['breakage_thresholds'] or core.get_assembly_thresholds().enabled:
        raise RuntimeError('Native switches/physical thresholds differ from the frozen fixture')
    actors = {}
    for name, path in zip(names, paths):
        view = scene[name].root_physx_view
        prim = stage.GetPrimAtPath(path)
        actors[name] = {'path':path, 'mass_kg':view.get_masses().cpu().numpy().tolist(),
            'inertias_kg_m2':view.get_inertias().cpu().numpy().tolist(),
            'com_local_pose_xyzw':view.get_coms().cpu().numpy().tolist(),
            'usd_physics_attributes':{a.GetName():metadata_scalar(a.Get()) for a in prim.GetAttributes()
                if a.GetName().startswith(('physics:', 'physxRigidBody:')) and isinstance(a.Get(), (float, int, bool, str))}}
    physics_scene = next(prim for prim in stage.Traverse() if prim.IsA(UsdPhysics.Scene))
    if str(physics_scene.GetAttribute('physxScene:solverType').Get()).upper() != protocol['solver']['type']:
        raise RuntimeError('Actual USD PhysicsScene solver differs from requested protocol')
    gravity_direction = UsdPhysics.Scene(physics_scene).GetGravityDirectionAttr().Get()
    metadata = {'protocol':protocol, 'actor_paths':paths, 'actor_order':names,
        'native_core_path':core.__file__, 'native_core_sha256':sha(core.__file__),
        'native_package_version':package_version,
        'tensor_api_source':inspect.getfile(type(scene['upper'].root_physx_view)),
        'tensor_api_source_sha256':sha(inspect.getfile(type(scene['upper'].root_physx_view))),
        'readable_helper_hashes':{str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'.deps/bricksim/core.pyi', ROOT/'challenge2/layout.py']},
        'actors':actors, 'gravity_configured_m_s2':list(sim_cfg.gravity),
        'gravity_usd_direction':list(gravity_direction),
        'gravity_usd_magnitude':UsdPhysics.Scene(physics_scene).GetGravityMagnitudeAttr().Get(),
        'physics_scene_attributes':{a.GetName():metadata_scalar(a.Get()) for a in physics_scene.GetAttributes()
            if isinstance(a.Get(), (float, int, bool, str))},
        'connection_path':connection, 'connection_arguments':connection_args,
        'native_relative_transform_qpos':[q,p], 'native_local_interface_transforms_qpos':local,
        'native_interface_frames_world_xyzwxyz':world_interfaces,
        'interface_frame_limit':'Native interface transforms; actual internal PxConstraint getForce frame/force is not publicly exposed.',
        'initial_native_parts':parts, 'initial_native_connections':links,
        'rigid_actor_paths':rigid, 'collider_paths':colliders,
        'thresholds_initial':threshold_snapshot(), 'automatic_assembly':False,
        'api_frames':'PhysX velocities and data.root_com_pos_w are WORLD. get_coms is principal-frame pose XYZ+XYZW relative to rigid-body prim. get_inertias is the COM tensor expressed in rigid-body-prim frame, column-major9; no extra principal-frame rotation should be applied to that matrix.',
        'weld_force_measurement':'Unavailable; native J/H cannot independently measure weld force by subtracting them from momentum change.'}
    write(args.output/'fixture_metadata.json', metadata)
    write(args.output/'native_id_mappings.json', {'physx':core.get_physx_id_mappings(), 'usd':core.get_usd_id_mappings()})
    np.save(args.output/'states_initial.npy', initial)
    records = []
    directory = args.output/'native_debug_tmp'
    with (args.output/'trace.jsonl').open('w') as trace:
        for step in range(protocol['maximum_steps']+1):
            before_time = float(sim.current_time)
            com_before = [scene[name].data.root_com_pos_w[0].cpu().numpy().tolist() for name in names]
            existing = set(directory.rglob('breakage_debug_*.json'))
            if step:
                scene.write_data_to_sim(); sim.step(render=False); scene.update(sim.get_physics_dt())
            current = states()
            com_after = [scene[name].data.root_com_pos_w[0].cpu().numpy().tolist() for name in names]
            parts, links = core.compute_connected_component(paths[0])
            events = core.get_disassembled_connections(clear=True)
            reasons = []
            if not np.isfinite(current).all() or not np.isfinite([com_before, com_after]).all(): reasons.append('nonfinite')
            displacement = float(np.linalg.norm(current[:,:3]-initial[:,:3], axis=1).max())
            angles = max(quaternion_error(a,b) for a,b in zip(current[:,3:7], initial[:,3:7]))
            if displacement > protocol['maximum_position_drift_m']: reasons.append('pose_position_drift')
            if angles > protocol['maximum_orientation_drift_rad']: reasons.append('pose_orientation_drift')
            if events or set(parts) != set(paths) or set(links) != {connection}: reasons.append('native_break_or_component_change')
            statefile = f'states_step_{step:02d}.npy'; np.save(args.output/statefile, current)
            utilization = float(core.get_connection_utilization(connection))
            record = {'step':step, 'physics_time_before_s':before_time, 'physics_time_after_s':float(sim.current_time),
                'dt_s':sim.get_physics_dt(), 'state_file':statefile, 'actor_order':names,
                'com_world_before_m':com_before, 'com_world_after_m':com_after,
                'max_position_drift_m':displacement, 'max_orientation_drift_rad':angles,
                'native_parts':parts, 'native_connections':links, 'break_events':[repr(e) for e in events],
                'utilization':utilization if math.isfinite(utilization) else None,
                'native_dumps_created_this_step':sorted(str(p.relative_to(args.output)) for p in set(directory.rglob('breakage_debug_*.json'))-existing),
                'reasons':reasons}
            trace.write(json.dumps(record, allow_nan=False)+'\n'); trace.flush()
            records.append(record)
            print('ECCENTRIC_STEP', step, reasons, flush=True)
            if reasons: break
    write(args.output/'diagnostic_report.json', {'diagnostic_completed':True, 'idle_validated':False,
        'full300_validated':False, 'steps_executed':records[-1]['step'], 'maximum_steps':protocol['maximum_steps'],
        'first_failure':records[-1] if records[-1]['reasons'] else None,
        'thresholds_terminal':threshold_snapshot(), 'protocol_sha256':sha(args.protocol),
        'interpretation':'Two-actor diagnostic only. Native external J/H, not raw momentum or weld reaction, are compared descriptively with gravity. Damping/discrete terms remain qualified; no physical-capacity or full-lattice validation.'})
    write(args.output/'diagnostic_complete.json', {'diagnostic_completed':True, 'idle_validated':False, 'full300_validated':False})


def main():
    if '--self-test' in sys.argv:
        check_geometry()
        assert quaternion_error((1,0,0,0),(-1,0,0,0)) == 0
        assert abs(quaternion_error((1,0,0,0),(math.sqrt(.5),0,0,math.sqrt(.5)))-math.pi/2) < 1e-12
        values = [True, 3, 2.5, 'TGS', math.inf, -math.inf, math.nan]
        encoded = [metadata_scalar(value) for value in values]
        assert encoded[:4] == values[:4]
        assert encoded[4:] == [{'nonfinite_scalar':'inf'}, {'nonfinite_scalar':'-inf'}, {'nonfinite_scalar':'nan'}]
        assert json.loads(json.dumps(encoded, allow_nan=False)) == encoded
        try:
            json.dumps({'mass_kg':[math.inf]}, allow_nan=False)
        except ValueError:
            pass
        else:
            raise AssertionError('Physical arrays must remain strict JSON')
        print('One-stud offset/footprint and quaternion tiny contracts: PASS')
        print('SDK metadata tags and strict physical-array JSON: PASS')
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--protocol', type=Path, default=HERE/'protocol.json')
    # Importing AppLauncher is lightweight; constructing it is queue guarded.
    from isaaclab.app import AppLauncher
    AppLauncher.add_app_launcher_args(parser)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1' or os.environ.get('OSQP_EPSILON') != '1e-4':
        raise RuntimeError('Requires default Pueue and explicit baseline OSQP_EPSILON=1e-4')
    args.output = args.output.resolve(); args.output.mkdir(parents=True, exist_ok=True)
    temporary = args.output/'native_debug_tmp'; temporary.mkdir()
    os.environ['TMPDIR'] = str(temporary)
    protocol = json.loads(args.protocol.read_text())
    app = None
    try:
        app = AppLauncher(args).app
        run(args, protocol)
    except BaseException:
        text = traceback.format_exc(); print(text, file=sys.stderr, flush=True)
        write(args.output/'failure.json', {'traceback':text, 'diagnostic_completed':False})
        raise
    finally:
        if app is not None: app.close(wait_for_replicator=False)


if __name__ == '__main__':
    main()

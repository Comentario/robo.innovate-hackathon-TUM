"""One pre-reset FR3 USD-chain derivation; never writes simulation state."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

NAMES = ['fr3_joint'+str(i) for i in range(1, 8)]
GOAL = [0.14, -0.12, 0.20, 0., math.sqrt(.5), math.sqrt(.5), 0.]
SOLVER = dict(damping=.01, maximum_iterations=200, maximum_update_rad=.05,
              position_tolerance_m=.0001, angle_tolerance_rad=math.radians(.1))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def transform(position, quaternion):
    p, q = np.asarray(position, float), np.asarray(quaternion, float)
    if p.shape != (3,) or q.shape != (4,) or not np.isfinite(np.r_[p, q]).all():
        raise RuntimeError('Nonfinite/invalid joint transform')
    if abs(np.linalg.norm(q)-1.) > 1e-6:
        raise RuntimeError('USD local quaternion is not normalized')
    result = np.eye(4)
    result[:3, :3] = Rotation.from_quat(q[[1, 2, 3, 0]]).as_matrix()
    result[:3, 3] = p
    return result


def pose(matrix):
    q = Rotation.from_matrix(matrix[:3, :3]).as_quat()[[3, 0, 1, 2]]
    return np.r_[matrix[:3, 3], q].tolist()


def fk(chain, q, offset):
    """Column-vector T_world_child=T_world_parent*T_local0*R(q)*inv(T_local1)."""
    world = np.asarray(chain['T_world_root'], float).copy()
    origins, axes = [], []
    for joint in chain['joints']:
        at_joint = world @ np.asarray(joint['T_parent_joint'], float)
        motion = np.eye(4)
        if joint['type'] == 'revolute':
            axis = np.asarray(joint['axis_vector'], float)
            origins.append(at_joint[:3, 3].copy())
            axes.append(at_joint[:3, :3] @ axis)
            motion[:3, :3] = Rotation.from_rotvec(axis*q[len(axes)-1]).as_matrix()
        world = at_joint @ motion @ np.linalg.inv(joint['T_child_joint'])
    hand, tcp = world, world @ offset
    jacobian = np.array([np.r_[np.cross(axis, tcp[:3, 3]-origin), axis]
                         for origin, axis in zip(origins, axes)]).T
    return hand, tcp, jacobian


def errors(actual, desired):
    return np.r_[desired[:3, 3]-actual[:3, 3],
                 Rotation.from_matrix(desired[:3, :3] @ actual[:3, :3].T).as_rotvec()]


def solve(chain, seed, offset, target, settings=None):
    settings = SOLVER if settings is None else settings
    q = np.asarray(seed, float).copy()
    limits = np.asarray(chain['limits_rad'], float)
    for iteration in range(settings['maximum_iterations']+1):
        if not np.isfinite(q).all() or np.any(q < limits[:, 0]) or np.any(q > limits[:, 1]):
            raise RuntimeError('Kinematic iterate outside actual USD joint limits')
        hand, tcp, jacobian = fk(chain, q, offset)
        error = errors(tcp, target)
        if (np.linalg.norm(error[:3]) <= settings['position_tolerance_m'] and
                np.linalg.norm(error[3:]) <= settings['angle_tolerance_rad']):
            return q, hand, tcp, iteration, error
        if iteration == settings['maximum_iterations']:
            break
        update = jacobian.T @ np.linalg.solve(jacobian @ jacobian.T + settings['damping']**2*np.eye(6), error)
        if not np.isfinite(update).all():
            raise RuntimeError('Nonfinite DLS update')
        update *= min(1., settings['maximum_update_rad']/max(np.max(abs(update)), 1e-30))
        q += update
    raise RuntimeError('The one fixed goal did not converge within 200 iterations')


def derive(stage, robot, science, init_protocol, nominal_proprio, output):
    from pxr import UsdGeom, UsdPhysics
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    config = init_protocol['kinematics']
    expected = {'goal_tcp_pose_world_wxyz': GOAL, 'maximum_iterations': 200, 'damping': .01,
                'maximum_joint_update_rad': .05, 'position_tolerance_m': .0001,
                'angle_tolerance_rad': math.radians(.1), 'nominal_position_tolerance_m': 2e-6,
                'nominal_angle_tolerance_rad': 1e-4}
    # 5e-12 permits only the frozen decimal spelling of 0.1 degrees, not a new gate.
    if any(not np.allclose(config[key], value, rtol=0, atol=5e-12) for key, value in expected.items()):
        raise RuntimeError('Initialization protocol differs from the one frozen solve')
    solver = {key: config['maximum_joint_update_rad' if key == 'maximum_update_rad' else key] for key in SOLVER}
    prefix = '/World/envs/env_0/Robot'
    root, hand_path = prefix+'/fr3_link0', prefix+'/fr3_hand'
    if UsdGeom.GetStageMetersPerUnit(stage) != 1. or not stage.GetPrimAtPath(root).IsValid():
        raise RuntimeError('Expected composed meter-scale FR3 root is unavailable')
    incoming = {}
    for prim in stage.Traverse():
        if not str(prim.GetPath()).startswith(prefix+'/') or not prim.IsA(UsdPhysics.Joint):
            continue
        joint = UsdPhysics.Joint(prim)
        a, b = joint.GetBody0Rel().GetTargets(), joint.GetBody1Rel().GetTargets()
        if len(a) != 1 or len(b) != 1:
            continue  # World anchoring is not part of the root-to-hand chain.
        incoming.setdefault(str(b[0]), []).append((prim, str(a[0])))
    joints, child, seen = [], hand_path, set()
    while child != root:
        if child in seen or len(incoming.get(child, [])) != 1:
            raise RuntimeError('Root-to-hand USD joint chain is missing or ambiguous')
        seen.add(child); prim, parent = incoming[child][0]
        if not parent.startswith(prefix+'/'):
            raise RuntimeError('Joint chain leaves the actual FR3 asset')
        joint = UsdPhysics.Joint(prim)
        record = {'path': str(prim.GetPath()), 'name': prim.GetName(), 'parent': parent, 'child': child}
        for index, key in ((0, 'T_parent_joint'), (1, 'T_child_joint')):
            p = getattr(joint, 'GetLocalPos'+str(index)+'Attr')().Get()
            q = getattr(joint, 'GetLocalRot'+str(index)+'Attr')().Get()
            raw = [float(q.GetReal()), *map(float, q.GetImaginary())]
            record['local'+str(index)] = {'position_m': list(map(float, p)), 'quaternion_wxyz': raw}
            record[key] = transform(p, raw).tolist()
        if prim.IsA(UsdPhysics.RevoluteJoint):
            revolute = UsdPhysics.RevoluteJoint(prim); axis = str(revolute.GetAxisAttr().Get())
            if axis not in ('X', 'Y', 'Z'):
                raise RuntimeError('Unsupported USD revolute axis')
            record.update(type='revolute', axis=axis, axis_vector=np.eye(3)['XYZ'.index(axis)].tolist(),
                          limits_rad=np.deg2rad([revolute.GetLowerLimitAttr().Get(), revolute.GetUpperLimitAttr().Get()]).tolist())
        elif prim.IsA(UsdPhysics.FixedJoint):
            record['type'] = 'fixed'
        else:
            raise RuntimeError('Unsupported joint type in actual FR3 arm chain')
        joints.append(record); child = parent
    joints.reverse(); arm = [j for j in joints if j['type'] == 'revolute']
    if [j['name'] for j in arm] != NAMES:
        raise RuntimeError('Actual seven joint names/order differ from frozen FR3 mapping')
    world_root = np.asarray(list(map(list, UsdGeom.Xformable(stage.GetPrimAtPath(root)).ComputeLocalToWorldTransform(0))), float).T
    limits = np.asarray([j['limits_rad'] for j in arm])
    if not np.isfinite(limits).all() or np.any(limits[:, 0] >= limits[:, 1]):
        raise RuntimeError('Invalid or unbounded actual USD joint limits')
    offset = transform(science['tool_frames']['T_hand_grip_translation_m'], science['tool_frames']['T_hand_grip_quaternion_wxyz'])
    chain = {'root': root, 'hand': hand_path, 'T_world_root': world_root.tolist(), 'T_hand_grip': offset.tolist(), 'joints': joints,
             'limits_rad': limits.tolist(), 'joint_names': NAMES,
             'joint_prim_stacks': {j['path']: [str(s.layer.identifier) for s in stage.GetPrimAtPath(j['path']).GetPrimStack()] for j in joints}}
    save(output/'kinematic_chain.json', chain)
    names = nominal_proprio.get('joint_names')
    if names is None or len(names) != len(nominal_proprio['q']) or any(names.count(n) != 1 for n in NAMES):
        raise RuntimeError('Pinned nominal proprioception needs explicit unique joint_names mapping')
    seed = np.asarray([nominal_proprio['q'][names.index(n)] for n in NAMES], float)
    nominal_tcp = transform(nominal_proprio['tcp_pose_world_wxyz'][:3], nominal_proprio['tcp_pose_world_wxyz'][3:])
    discrepancy = errors(fk(chain, seed, offset)[1], nominal_tcp)
    nominal_errors = {'position_m': float(np.linalg.norm(discrepancy[:3])), 'angle_rad': float(np.linalg.norm(discrepancy[3:]))}
    save(output/'nominal_fk_check.json', nominal_errors)
    if (nominal_errors['position_m'] > config['nominal_position_tolerance_m'] or
            nominal_errors['angle_rad'] > config['nominal_angle_tolerance_rad']):
        raise RuntimeError('Composed USD FK does not match pinned actual FR3 proprioception')
    goal = config['goal_tcp_pose_world_wxyz']
    q, hand, tcp, iterations, error = solve(chain, seed, offset, transform(goal[:3], goal[3:]), solver)
    report = {'joint_names': NAMES, 'q': q.tolist(), 'chain_file': 'kinematic_chain.json',
              'predicted_hand_pose_wxyz': pose(hand), 'predicted_tcp_pose_wxyz': pose(tcp),
              'nominal_fk_errors': nominal_errors, 'target_errors': {'position_m': float(np.linalg.norm(error[:3])), 'angle_rad': float(np.linalg.norm(error[3:]))},
              'target_tcp_pose_wxyz': goal, 'seed_q': seed.tolist(), 'iterations': iterations, 'solver': solver,
              'init_protocol_sha256': hashlib.sha256(json.dumps(init_protocol, sort_keys=True, allow_nan=False).encode()).hexdigest(),
              'state_writes': 0, 'simulation_steps': 0, 'table_equals_world_required': True}
    save(output/'kinematic_derivation.json', report)
    return report

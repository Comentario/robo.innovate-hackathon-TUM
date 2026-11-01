"""Nine pinned saved samples; no simulation, capacity estimate or retry permission."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np
from scipy.spatial.transform import Rotation

HERE = Path(__file__).resolve().parent
SAMPLES = [('position1819', 1819, [1853,1900,1950,2000,2050,2100,2112,2113]),
           ('baseline1818', 1818, [1853])]


def transform(pose):
    pose = np.asarray(pose, dtype=np.float64)
    if pose.shape != (7,) or not np.isfinite(pose).all() or np.linalg.norm(pose[3:]) == 0:
        raise ValueError('Invalid WXYZ pose')
    matrix = np.eye(4)
    matrix[:3,:3] = Rotation.from_quat(pose[[4,5,6,3]]).as_matrix()
    matrix[:3,3] = pose[:3]
    return matrix


def stream_rows(data, kind, capacity):
    """Each stream has its OWN original indices/count/start buffers."""
    counts, starts = data[kind+'_counts'].reshape(-1), data[kind+'_starts'].reshape(-1)
    active = data[kind+'_indices'].reshape(-1)
    if not np.array_equal(active, active.astype(np.int64)):
        raise ValueError('Noninteger active indices')
    rows, original = [], []
    for count, start in zip(counts, starts):
        n, a = int(count), int(start)
        if count != n or start != a or n < 0 or (n and (a < 0 or a+n > capacity)):
            raise ValueError('Invalid '+kind+' pair range')
        wanted = np.arange(a, a+n, dtype=int); positions = np.searchsorted(active, wanted)
        if n and (np.max(positions) >= len(active) or not np.array_equal(active[positions], wanted)):
            raise ValueError('Missing '+kind+' compact rows')
        rows.append(positions); original.extend(wanted.tolist())
    if len(original) >= capacity or len(set(original)) != len(original) or not np.array_equal(sorted(original), active):
        raise ValueError('Incomplete/overlapping/saturated '+kind+' ranges')
    return rows


def read_frames(path, steps):
    rows = {}
    with path.open() as stream:
        for line in stream:
            row = json.loads(line)
            if row['step'] in steps:
                if row['step'] in rows: raise ValueError('Duplicate frame')
                rows[row['step']] = row
            if row['step'] > max(steps): break
    if set(rows) != set(steps): raise ValueError('Missing fixed frame')
    return rows


def summarize(data, view, dt):
    if not all(np.isfinite(v).all() for v in data.values()): raise ValueError('Nonfinite contact data')
    paths = view['filter_paths']; paths = paths[0] if len(paths)==1 and isinstance(paths[0],list) else paths
    normal = stream_rows(data, 'normal', view['max_contact_data_count'])
    friction = stream_rows(data, 'friction', view['max_contact_data_count'])
    if len(paths) != len(normal) or len(paths) != len(friction): raise ValueError('Filter count differs')
    f = data['normal_forces_N'].reshape(-1); normals = data['normal_vectors_world']
    ff = data['friction_forces_world_N'].reshape(-1,3)
    if not np.all(abs(np.linalg.norm(normals,axis=1)-1) <= 1e-3): raise ValueError('Nonunit normal')
    checks = {}
    for name, impulse, force in [('normal', data['normal_impulses_Ns'].reshape(-1), f),
                                 ('friction', data['friction_impulses_world_Ns'].reshape(-1,3), ff)]:
        checks[name+'_dt_scaling'] = bool(np.linalg.norm(impulse-force*dt) <= max(1e-7,1e-5*np.linalg.norm(force*dt)))
    matrix = data['filtered_normal_impulse_matrix_world_Ns'].reshape(-1,3)/dt
    net = data['all_body_net_normal_impulse_world_Ns'].reshape(-1,3)[0]/dt
    checks['matrix_net'] = bool(np.linalg.norm(matrix.sum(0)-net) <= max(.005,.01*np.linalg.norm(net)))
    pairs = {}
    for i, path in enumerate(paths):
        nr, fr = normal[i], friction[i]; vector = (f[nr,None]*normals[nr]).sum(0); raw_friction = ff[fr].sum(0)
        checks['pair_matrix_'+str(i)] = bool(np.linalg.norm(vector-matrix[i]) <= max(.005,.01*np.linalg.norm(matrix[i])))
        pairs[path] = {'normal_rows':nr.tolist(),'friction_rows':fr.tolist(),
            'normal_sumabs_N':float(abs(f[nr]).sum()),'normal_vector_world_N':vector.tolist(),
            'normal_world_Z_sum_N':float(vector[2]),'raw_friction_vector_world_N':raw_friction.tolist(),
            'raw_friction_world_Z_sum_N':float(raw_friction[2]),
            'raw_friction_sum_magnitudes_N':float(np.linalg.norm(ff[fr],axis=1).sum())}
    return {'checks':checks,'pairs':pairs,'normal_count':len(f),'friction_anchor_count':len(ff)}


def loaded_points(data, indices, pose, side, finger, distal, floor, source=False, recorded=None):
    matrix = transform(pose); records = []; forces = data['normal_forces_N'].reshape(-1)
    for index in indices:
        force = float(forces[index])
        if abs(force) <= floor: continue
        world = data['normal_points_world_m'][index]; local = (world-matrix[:3,3])@matrix[:3,:3]
        normal = (1 if source else -1)*np.sign(force)*data['normal_vectors_world'][index]@matrix[:3,:3]
        normal /= np.linalg.norm(normal); expected = np.array([0.,-1 if side=='left' else 1.,0.])
        separation = float(data['normal_separations_m'].reshape(-1)[index]); tolerance = abs(separation)+50e-6
        flat = float(abs(local[1]-finger['inner_plane_y_m'])); dot = float(normal@expected)
        saved = [p for p in (recorded or []) if p['point_world_m']==world.tolist() and p['force_signed_N']==force and p['separation_m']==separation]
        records.append({'active_row':int(index),'raw_index':int(data['normal_indices'][index]),
            'force_signed_N':force,'separation_m':separation,'point_world_m':world.tolist(),
            'point_finger_m':local.tolist(),'local_Z_to_authored_tip_m':float(distal-local[2]),
            'flat_distance_m':flat,'tolerance_m':tolerance,'outward_normal_finger':normal.tolist(),
            'outward_dot_grip_normal':dot,'flat_and_normal_compatible':bool(flat<=tolerance and dot>=.9),
            'recorded_finger_qualification':saved[0] if len(saved)==1 else None,
            'qualification_scope':'Flat/normal reconstructed; full finger qualification copied only for an exact saved point/force/sep match. No shape ownership inferred.'})
    return records


def run(protocol_path, output):
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    start = time.monotonic(); protocol = json.loads(Path(protocol_path).read_text()); output = Path(output); output.mkdir(parents=True,exist_ok=True)
    if protocol.get('execution_authorized') is not True: raise RuntimeError('Execution not authorized')
    if [(c['id'],c['job_id'],c['steps']) for c in protocol['cases']] != SAMPLES or protocol['maximum_active_seconds'] != 30:
        raise ValueError('Fixed nine-sample scope differs')
    pins = protocol['input_sha256']
    def checked(path):
        path = Path(path).resolve()
        if str(path) not in pins or hashlib.sha256(path.read_bytes()).hexdigest() != pins[str(path)]: raise ValueError('Unpinned or changed input: '+str(path))
        return path
    def read(path): return json.loads(checked(path).read_text())
    def arrays(path):
        with np.load(checked(path),allow_pickle=False) as raw: return {k:raw[k].copy() for k in raw.files}
    for path in pins: checked(path)
    prior = read(protocol['prior_supervisor']['path'])
    if prior['physics_extraction_passed'] is not False or prior['cumulative_case_seconds'] != protocol['prior_case_seconds']: raise ValueError('Prior failure/clock differs')
    result = {'proceed_gate_passed':False,'physical_retry_authorized':False,'prior_failures_preserved':True,
        'input_sha256':pins,'cases':[],'truncated':False,'friction_signed_traction':'UNKNOWN; raw stream only, no independent sign control',
        'native_utilization':'UNKNOWN; debug_dump false','scope':'Fixed saved samples, not a net wrench/capacity or causal proof'}
    for case in protocol['cases']:
        base = Path(case['snapshot'])/'output'; steps = case['steps']; meta = read(base/'capture_metadata.json')
        online = read_frames(checked(base/'online/trace.jsonl'),steps); truth = read_frames(checked(base/'evaluation_truth/trace.jsonl'),steps)
        inventory = read(base/'evaluation_truth/initial_inventory.json'); binding = read(base/'evaluation_truth/initial_binding.json')
        if not binding['unique'] or len(binding['matches'])!=1: raise ValueError('Ambiguous private binding')
        target = binding['matches'][0]['id']; target_index = inventory['ids'].index(target)
        geometry = read(base/'tool_geometry.json'); selection = read(base/'online/selection.json')
        views = read(base/'contact_observations/metadata.json')['resolved_views']; views.update(read(base/'evaluation_truth/contact_observations/metadata.json')['resolved_views'])
        frames=[]; reference_tcp=None; reference_body=None; reference_command_z=None
        for step in steps:
            if time.monotonic()-start >= 29: result['truncated']=True; break
            row, gt = online[step], truth[step]; dt = row['physics_dt_s']
            if row['time_s'] != gt['time_s'] or dt != meta['dt_s']: raise ValueError('Clock/dt mismatch')
            state = arrays(base/'evaluation_truth'/gt['state_file'])['states'][target_index]
            tcp, body = transform(row['tcp_pose_world_wxyz']), transform(state[:7])
            if reference_tcp is None:
                reference_tcp,reference_body = tcp.copy(),body.copy(); reference_command_z=row['tcp_target_table_wxyz'][2]
            slip=float((tcp[2,3]-reference_tcp[2,3])-(body[2,3]-reference_body[2,3]))
            frame={'step':step,'phase':row['phase'],'time_s':row['time_s'],'tcp_pose_world_wxyz':row['tcp_pose_world_wxyz'],
                'commanded_tcp_pose_table_wxyz':row['tcp_target_table_wxyz'],
                'commanded_tcp_rise_since_admission_m':float(row['tcp_target_table_wxyz'][2]-reference_command_z),
                'target_pose_world_wxyz':state[:7].tolist(),'T_tcp_target':(np.linalg.inv(tcp)@body).tolist(),
                'tcp_rise_since_admission_m':float(tcp[2,3]-reference_tcp[2,3]),'target_rise_since_admission_m':float(body[2,3]-reference_body[2,3]),
                'relative_vertical_slip_m':slip,
                'approx_remaining_nominal_side_band_m':float(selection['nominal_body_side_overlap_m']-slip),
                'band_descriptor_limit':'Initial nominal overlap minus relative vertical slip; not measured physical remaining overlap.',
                'gaps':{k:row.get(k) for k in ('actual_joint_gap_m','commanded_joint_gap_m','actual_model_pad_gap_m','nominal_commanded_pad_gap_m')},
                'q':row['q'],'joint_commands':row['joint_commands'],'stop_reasons':row['stop_reasons'],
                'remaining_target_edges':[e['id'] for e in inventory['initial_edges'] if target in (e['a'],e['b']) and e['id'] in gt['edges']],
                'break_events':gt['break_events'],'views':{},'reciprocal_normals':{}}
            raw={}
            for label in ('left','right','source'):
                record = gt['contacts'][label] if label=='source' else row['contacts'][label]
                raw[label] = arrays(base/record['file']); frame['views'][label]=summarize(raw[label],views[label],dt)
            for side in ('left','right'):
                finger=geometry['fingers'][side]; source_pair=frame['views']['source']['pairs'][finger['body_path']]
                finger_pair=frame['views'][side]['pairs'][target]; a=np.asarray(finger_pair['normal_vector_world_N']); b=np.asarray(source_pair['normal_vector_world_N'])
                residual=float(np.linalg.norm(a+b)); frame['reciprocal_normals'][side]={'residual_N':residual,'within_existing_tolerance':bool(residual<=max(.005,.01*max(np.linalg.norm(a),np.linalg.norm(b))))}
                for label,indices,is_source in [(side,range(len(raw[side]['normal_indices'])),False),('source',source_pair['normal_rows'],True)]:
                    points=loaded_points(raw[label],indices,row['finger_poses_world_wxyz'][side],side,finger,protocol['authored_distal_finger_z_m'],protocol['force_carrying_floor_N'],is_source,row['point_ownership'][side] if not is_source else None)
                    frame['views'][label].setdefault('loaded_points_by_finger',{})[side]=points
            frames.append(frame)
        result['cases'].append({'id':case['id'],'nominal_body_side_overlap_m':selection['nominal_body_side_overlap_m'],'frames':frames})
        if result['truncated']: break
    all_frames=[frame for case in result['cases'] for frame in case['frames']]
    result['diagnostic_complete']=bool(not result['truncated'] and len(all_frames)==9 and
        all(all(view['checks'].values()) for frame in all_frames for view in frame['views'].values()) and
        all(pair['within_existing_tolerance'] for frame in all_frames for pair in frame['reciprocal_normals'].values()))
    result['wall_seconds']=time.monotonic()-start
    (output/'retention_review.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(allow_abbrev=False);parser.add_argument('--protocol',type=Path,default=HERE/'protocol.json');parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not run(args.protocol,args.output)['diagnostic_complete']: raise SystemExit(2)

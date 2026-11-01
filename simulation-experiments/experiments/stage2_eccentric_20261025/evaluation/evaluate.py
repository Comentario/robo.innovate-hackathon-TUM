"""Independent, queued read-only eccentric-fixture audit; never a native solve."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
READER_SHA = 'c745fb09248ba70882ce31d7e1534a523630ad4be00b7c0ce32f150c9fbd68bf'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rotation(q):
    q = np.asarray(q, float)
    if not np.isfinite(q).all() or np.linalg.norm(q) == 0:
        raise ValueError('Invalid WXYZ orientation')
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def audit(args):
    if sha(HERE/'matrix_loader.py') != READER_SHA:
        raise ValueError('Pinned existing matrix reader changed')
    from matrix_loader import load_matrix
    protocol = json.loads((HERE/'protocol.json').read_text())
    metadata = json.loads((args.input/'fixture_metadata.json').read_text())
    report = json.loads((args.input/'diagnostic_report.json').read_text())
    capture = metadata['protocol']
    rows = [json.loads(line) for line in (args.input/'trace.jsonl').read_text().splitlines()]
    n = report['steps_executed']
    if not 1 <= n <= protocol['budget']['maximum_steps']:
        raise ValueError('Invalid diagnostic step budget')
    checks = {}
    checks['exact_step_sequence'] = [r['step'] for r in rows] == list(range(n+1))
    checks['completed_not_promoted'] = report['diagnostic_completed'] and not report['idle_validated'] and not report['full300_validated']
    checks['two_actor_order'] = metadata['actor_order'] == ['lower', 'upper']
    paths = metadata['actor_paths']
    checks['only_two_rigid_actors'] = len(paths) == 2 and set(metadata['rigid_actor_paths']) == set(paths)
    checks['no_external_colliders'] = all(any(p == a or p.startswith(a+'/') for a in paths) for p in metadata['collider_paths'])
    checks['initial_two_parts_one_link'] = set(metadata['initial_native_parts']) == set(paths) and len(metadata['initial_native_connections']) == 1
    checks['binary'] = metadata['native_core_sha256'] == capture['native_core_sha256']
    checks['thresholds'] = metadata['thresholds_initial'] == capture['breakage_thresholds'] == report['thresholds_terminal']
    checks['automatic_assembly_disabled'] = metadata['automatic_assembly'] is False
    checks['default_config'] = capture['solver']['position_iterations'] == 32 and capture['solver']['velocity_iterations'] == 4 and capture['OSQP_EPSILON'] == '1e-4' and capture['dt_s'] == protocol['unchanged']['physics_dt_s']
    gravity = np.asarray(metadata['gravity_configured_m_s2'], float)
    usd_g = np.asarray(metadata['gravity_usd_direction'], float)*metadata['gravity_usd_magnitude']
    checks['gravity_configured_equals_usd'] = bool(np.allclose(gravity, usd_g, atol=protocol['serialization_tolerances']['gravity_vector_absolute_m_s2'], rtol=0))
    mapping = json.loads((args.input/'native_id_mappings.json').read_text())
    part_paths = {int(pid): path for path, pid in mapping['physx'][0].items()}
    upper_ids = [pid for pid, path in part_paths.items() if path == paths[1]]
    if len(upper_ids) != 1:
        raise ValueError('Cannot independently map dynamic upper native body')
    upper_pid = upper_ids[0]
    upper = metadata['actors']['upper']
    mass = float(np.asarray(upper['mass_kg']).ravel()[0])
    inertia = np.asarray(upper['inertias_kg_m2'], float).reshape(3, 3, order='F')
    checks['upper_mass_inertia_finite_positive'] = bool(math.isfinite(mass) and mass > 0 and np.isfinite(inertia).all() and np.linalg.eigvalsh((inertia+inertia.T)/2).min() > 0)
    checks['exact_actor_order_each_step'] = all(r['actor_order'] == ['lower', 'upper'] for r in rows)
    checks['step_clocks'] = all(abs(r['dt_s']-capture['dt_s']) < 1e-12 and abs((r['physics_time_after_s']-r['physics_time_before_s'])-(capture['dt_s'] if i else 0)) < 1e-7 and (not i or abs(r['physics_time_before_s']-rows[i-1]['physics_time_after_s']) < 1e-7) for i,r in enumerate(rows))
    states = [np.load(args.input/r['state_file'], allow_pickle=False) for r in rows]
    checks['finite_two_actor_states'] = all(s.shape == (2,13) and np.isfinite(s).all() for s in states)
    checks['initial_matches_saved'] = np.array_equal(states[0], np.load(args.input/'states_initial.npy', allow_pickle=False))
    checks['initial_poses'] = all(np.linalg.norm(states[0][i,:3]-capture['root_poses_wxyz'][name][:3]) <= 2e-6 and abs(abs(np.dot(states[0][i,3:7]/np.linalg.norm(states[0][i,3:7]), capture['root_poses_wxyz'][name][3:]))-1) < 1e-8 for i,name in enumerate(['lower','upper']))
    checks['initial_zero_velocity'] = bool(np.max(np.abs(states[0][:,7:])) <= 1e-7)
    discovered = {str(p.relative_to(args.input)) for p in (args.input/'native_debug_tmp').rglob('breakage_debug_*.json')}
    named = [p for r in rows for p in r['native_dumps_created_this_step']]
    checks['dump_set_exact_and_unique'] = len(named) == len(set(named)) and set(named) == discovered
    checks['one_dump_per_physics_step'] = not rows[0]['native_dumps_created_this_step'] and all(len(r['native_dumps_created_this_step']) == 1 for r in rows[1:])
    records = []
    for index, row in enumerate(rows[1:], 1):
        if len(row['native_dumps_created_this_step']) != 1:
            continue
        file = args.input/row['native_dumps_created_this_step'][0]
        dump = json.loads(file.read_text())
        system, inp = dump['system'], dump['input']
        ids = list(map(int, system['part_ids']))
        if upper_pid not in ids:
            raise ValueError('Dynamic upper missing from aligned native system')
        k = ids.index(upper_pid)
        j, h, center, native_mass = (np.asarray(load_matrix(obj), float) for obj in (inp['J'], inp['H'], inp['c'], system['mass']))
        dt = float(inp['dt'])
        finite = all(np.isfinite(a).all() for a in (j,h,center,native_mass))
        checks[f'step_{index}_native_finite_dt_mass'] = bool(finite and abs(dt-capture['dt_s']) <= protocol['serialization_tolerances']['native_dump_dt_absolute_s'] and abs(native_mass.ravel()[k]-mass) < 1e-10)
        checks[f'step_{index}_prebreak_native_system'] = system['num_parts'] == 2 and system['num_clutches'] == 1 and set(ids) == set(part_paths)
        expected = mass*gravity*dt
        sj = float(np.linalg.norm(expected)); sh = sj*protocol['analysis']['characteristic_length_m']
        jr = j[k]-expected
        before, after = states[index-1][1], states[index][1]
        # Conditional on captured tensor's documented rigid-body-frame convention;
        # no extra rotation by local COM principal-frame quaternion is applied.
        angular = lambda s: rotation(s[3:7])@inertia@rotation(s[3:7]).T@s[10:13]
        native_com_to_before = float(np.linalg.norm(center[k]-np.asarray(row['com_world_before_m'])[1]))
        native_com_to_after = float(np.linalg.norm(center[k]-np.asarray(row['com_world_after_m'])[1]))
        records.append({'step': index, 'dump':str(file.relative_to(args.input)), 'dump_sha256':sha(file),
            'event_step':bool(row['reasons']), 'utilization_after_step':row['utilization'],
            'solver_info_serialized':dump['solution'].get('info', {}),
            'native_mass_kg':float(native_mass.ravel()[k]), 'native_COM_world_m':center[k].tolist(),
            'native_COM_distance_to_pre_post_m':[native_com_to_before,native_com_to_after],
            'native_external_J_world_Ns':j[k].tolist(), 'native_external_H_world_Nms':h[k].tolist(),
            'gravity_reference_Ns':expected.tolist(), 'J_minus_gravity_Ns':jr.tolist(),
            'J_residual_norm_Ns':float(np.linalg.norm(jr)), 'H_norm_Nms':float(np.linalg.norm(h[k])),
            'linear_reference_scale_Ns':sj, 'angular_reference_scale_Nms':sh,
            'J_residual_over_gravity_scale':float(np.linalg.norm(jr)/sj) if sj else None,
            'H_over_characteristic_gravity_moment_scale':float(np.linalg.norm(h[k])/sh) if sh else None,
            'raw_delta_linear_momentum_world_Ns':(mass*(after[7:10]-before[7:10])).tolist(),
            'conditional_raw_delta_angular_momentum_world_Nms':(angular(after)-angular(before)).tolist(),
            'momentum_caveat':'Raw changes include the legitimate eccentric weld reaction; not external-only impulses. Angular calculation is conditional on captured body-frame inertia API convention.'})
    result = {'schema':'eccentric-fixture-independent-audit-v1','input':str(args.input),
        'protocol_sha256':sha(HERE/'protocol.json'),'capture_protocol':capture,
        'matrix_reader_sha256':READER_SHA, 'integrity_checks':checks,
        'all_integrity_checks_pass':all(checks.values()), 'steps_executed':n,
        'first_failure':report['first_failure'], 'upper_native_id':upper_pid,
        'actor_mass_inertia_damping_evidence':upper,
        'records':records, 'unknowns':['Independent raw weld force/couple unavailable','Damping and finite-step terms are recorded but not independently subtracted','COM distance is an alignment diagnostic, not proof of native callback event order','Break-step before/after event order must be kept distinct'],
        'conclusion':'Descriptive eccentric bookkeeping diagnostic only. No residual threshold establishes physical correctness or overload. Fixture failure is not a demonstrated lever-arm bug; fixture agreement does not validate redundant full300 lattice. Full300 idle and manipulation remain unvalidated.',
        'idle_validated':False,'full300_validated':False}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    lines=['# Eccentric fixture independent audit','',f"Integrity: {sum(checks.values())}/{len(checks)} checks. Steps: {n}.",'',
           '|Step|Event step|J residual (N s)|H norm (N m s)|J residual / gravity|H / characteristic gravity moment|','|---:|:---:|---:|---:|---:|---:|']
    for r in records:
        lines.append(f"|{r['step']}|{r['event_step']}|{r['J_residual_norm_Ns']:.8g}|{r['H_norm_Nms']:.8g}|{r['J_residual_over_gravity_scale']:.8g}|{r['H_over_characteristic_gravity_moment_scale']:.8g}|")
    lines += ['',result['conclusion'],'','Raw eccentric weld moments need not be zero. Native J/H are inferred after weld subtraction; gravity-relative residuals are not independently measured contact loads.']
    (args.output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    (args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'evaluation_sha256':sha(args.output/'evaluation.json'),'idle_validated':False})+'\n')


def main():
    if '--self-test' in os.sys.argv:
        assert np.allclose(rotation([math.sqrt(.5),0,0,math.sqrt(.5)])@[1,0,0],[0,1,0],atol=1e-12)
        assert np.allclose(rotation([-1,0,0,0]),np.eye(3))
        json.dumps({'count':int(np.sum([True,True]))},allow_nan=False)
        protocol = json.loads((HERE/'protocol.json').read_text())
        assert abs(float(np.float32(9.81))-9.81) <= protocol['serialization_tolerances']['gravity_vector_absolute_m_s2']
        assert abs(float(np.float32(1/120))-1/120) <= protocol['serialization_tolerances']['native_dump_dt_absolute_s']
        print('Tiny rotation/serialization contracts PASS; no capture data read')
        return
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Actual array audit requires default Pueue')
    audit(args)


if __name__ == '__main__':
    main()

"""Read-only analysis of one bounded1..8-step native diagnostic; no solver rerun."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
WATCHED = (836, 837)
CONTROLS = (832, 833, 922, 923)


def load_reader(path):
    spec = importlib.util.spec_from_file_location('existing_bricksim_matrix_reader', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_matrix


def capacity_summary(coefficients, capacities, native_utilization):
    import numpy as np
    if not len(capacities):
        return {'capacity_rows': 0, 'native_utilization': native_utilization}
    used = capacities[:, :3]@coefficients[:3]
    available = 1.-capacities[:, 3:]@coefficients[3:]
    ratios = np.full(len(used), 1e6)
    np.divide(used, available, out=ratios, where=available > 0)
    ratios[available > 0] = np.maximum(ratios[available > 0], 0.)
    worst = int(ratios.argmax())
    return {'capacity_rows': len(capacities), 'native_utilization': native_utilization,
        'recomputed_utilization': float(ratios[worst]), 'worst_row_index_within_clutch': worst,
        'worst_used_normalized': float(used[worst]), 'worst_available_normalized': float(available[worst]),
        'minimum_available_normalized': float(available.min()),
        'worst_capacity_coefficients': capacities[worst].tolist(),
        'physical_field_coefficients_not_wrench': coefficients.tolist(),
        'units': 'Native normalized capacity terms; coefficients have mixed force/position units, not one force value'}


def dump_order(path):
    match = re.fullmatch(r'breakage_debug_(\d{8}_\d{6})(?:_(\d+))?\.json', path.name)
    if not match:
        raise ValueError('Unexpected native dump filename: '+path.name)
    return match[1], int(match[2] or 0)


def relaxation_summary(hx_opt, hx_rlx, allowance_opt, allowance_raw, raw_v, info, epsilon):
    """Native dimensionless capacity bounds, not a force or a new tolerance."""
    import numpy as np
    if epsilon not in (1e-4, 1e-6):
        raise ValueError('Only the two declared coupled numerical epsilon diagnostics are supported')
    opt_gap = hx_opt-1.-allowance_opt
    rlx_gap = hx_rlx-allowance_raw-(1.-epsilon)
    return {'raw_v_k': float(raw_v), 'clamped_v_k': float(max(raw_v, 0.)),
        'stage3_max_Hx_minus_one': float(np.max(hx_opt-1.)),
        'stage3_Vv_range': [float(allowance_opt.min()), float(allowance_opt.max())],
        'stage3_max_signed_gap_to_1_plus_Vv_bound': float(opt_gap.max()),
        'stage3_max_positive_violation': float(max(opt_gap.max(), 0.)),
        'stage2_max_signed_gap_to_1_minus_epsilon_bound': float(rlx_gap.max()),
        'stage2_max_positive_violation': float(max(rlx_gap.max(), 0.)),
        'stage2_v_nonnegative_violation': float(max(-raw_v, 0.)),
        'serialized_stage3_prim_res': info.get('opt_info', {}).get('prim_res'),
        'serialized_stage2_prim_res': info.get('rlx_info', {}).get('prim_res'),
        'requested_eps_abs_and_eps_rel_reference': epsilon,
        'tolerance_status': 'Recorded request or legacy source-default assumption; native per-dump settings and auxiliary z/scaling were not serialized, so no exact row termination tolerance is claimed',
        'units': 'Dimensionless normalized capacity relaxation; v is not Newtons',
        'native_bounds': 'rlx_sol=[x,v_raw]; v=max(v_raw,0); stage2 H*x-V*v_raw<=1-epsilon; stage3 H*x<=1+V*v'}


def analyze(args):
    import numpy as np
    protocol = json.loads(Path(__file__).with_name('analysis_protocol.json').read_text())
    if hashlib.sha256(args.matrix_loader.read_bytes()).hexdigest() != protocol['matrix_loader_sha256']:
        raise ValueError('Matrix reader differs from the frozen existing BrickSim source')
    reader = load_reader(args.matrix_loader)
    diagnostic = json.loads((args.input/'diagnostic_report.json').read_text())
    count = diagnostic['steps_executed']
    if diagnostic['maximum_steps'] != 8 or not isinstance(count, int) or not 1 <= count <= 8:
        raise ValueError('Only a completed1..8-step diagnostic is supported')
    numerical = diagnostic.get('numerical_epsilon')
    epsilon = float(numerical['effective_requested']) if numerical else 1e-4
    if epsilon not in (1e-4, 1e-6):
        raise ValueError('Undeclared numerical epsilon; no general parameter sweep is supported')
    epsilon_provenance = {'effective_requested': epsilon,
        'source': 'recorded_diagnostic_report' if numerical else 'legacy_assumed_source_default_env_not_recorded',
        'recorded_environment': numerical,
        'interpretation': 'Coupled numerical epsilon: solver eps_abs/eps_rel, G lower bound and stage2 capacity margin change together; not a pure termination-tolerance test'}
    paths = sorted((args.input/'native_debug_tmp').rglob('breakage_debug_*.json'), key=dump_order)
    if len(paths) != count:
        raise ValueError('Native dump count must equal the recorded executed diagnostic steps')
    mappings = json.loads((args.input/'native_id_mappings.json').read_text())
    part_names = {int(value): key for key, value in mappings['physx'][0].items()}
    connection_names = {int(value): key for key, value in mappings['physx'][1].items()}
    if not part_names.get(273, '').endswith('/brick_9_0_3'):
        raise ValueError('Frozen part273 mapping does not identify the observed failed brick')
    trace = [json.loads(line) for line in (args.input/'diagnostic_trace.jsonl').read_text().splitlines()]
    steps = {row['step']: row for row in trace}
    if sorted(steps) != list(range(count+1)):
        raise ValueError('Trace must contain exactly steps0..recorded_steps_executed')
    gravity = np.asarray([0., 0., -9.81])
    records = []
    for step, path in enumerate(paths, 1):
        dump = json.loads(path.read_text())
        system, inp, solution = dump['system'], dump['input'], dump['solution']
        if system['num_parts'] != 301 or system['num_clutches'] != 930:
            raise ValueError('Dump does not describe the expected pre-break full component')
        pids, cids = list(map(int, system['part_ids'])), list(map(int, system['clutch_ids']))
        mass = reader(system['mass']).ravel()
        inertia = reader(system['I_CC'])
        v, w, centers = (reader(inp[key]) for key in ('v', 'w', 'c'))
        J, H = reader(inp['J']), reader(inp['H'])
        A = reader(system['A'])
        physical_x = reader(solution['x']).ravel()
        utilization = reader(solution['utilization']).ravel()
        state = dump['state']['solver_state']
        # A uses whitened variables; solution.x has already been unwhitened.
        solver_x = reader(state['opt_sol']).ravel()
        slack, b = reader(state['slack']).ravel(), reader(dump['b']).ravel()
        capacities = reader(system['capacities'])
        capacity_indices = np.asarray(system['capacity_clutch_indices'], int)
        relaxation = None
        if 'rlx_sol' in state:
            rlx_sol = reader(state['rlx_sol']).ravel()
            nx, nv = system['num_vars'], system['num_clutches']
            capacity_H, capacity_V = reader(system['H']), reader(system['V'])
            if (len(rlx_sol) != nx+nv or capacity_H.shape != (len(capacity_indices), nx)
                or capacity_V.shape != (len(capacity_indices), nv)):
                raise ValueError('Native [x,v] relaxation layout differs from the documented source')
            raw_v = rlx_sol[nx:]
            relaxation = {'H_opt': np.asarray(capacity_H@solver_x),
                'H_rlx': np.asarray(capacity_H@rlx_sol[:nx]), 'raw_v': raw_v,
                'V_clamped': np.asarray(capacity_V@np.maximum(raw_v, 0.)),
                'V_raw': np.asarray(capacity_V@raw_v), 'V': capacity_V}
        if len(solver_x) != A.shape[1] or len(b) != A.shape[0]:
            raise ValueError('Unexpected serialized solver dimensions')
        physical_solution_available = len(physical_x) == len(solver_x)
        utilization_available = len(utilization) == len(cids)
        if not all(np.isfinite(value).all() for value in (mass, inertia, v, w, centers, J, H,
                                                         physical_x, utilization, solver_x, slack, b)):
            raise ValueError('Nonfinite dump arrays; preserve raw input rather than infer a cause')
        residual = A@solver_x-b
        projected_residual = A@solver_x-(b-slack)
        rhs = b.reshape(len(pids), 6)
        interested = {273}
        clutches = {}
        for cid in WATCHED+CONTROLS:
            k = cids.index(cid)
            start = system['num_contact_vertices']+9*k
            block = A[:, start:start+9]
            endpoint_rows = np.flatnonzero(np.asarray(abs(block).sum(axis=1)).reshape(len(pids), 6).sum(axis=1) > 0)
            wrench = np.asarray(block@solver_x[start:start+9]).reshape(len(pids), 6)
            interested.update(pids[index] for index in endpoint_rows)
            native_utilization = float(utilization[k]) if utilization_available else None
            row = capacity_summary(physical_x[start:start+9], capacities[capacity_indices == k], native_utilization) if physical_solution_available else {
                'native_utilization': native_utilization, 'recomputed_utilization': None,
                'unavailable_reason': 'Native physical solution.x absent; consult serialized solver status'}
            row.update(connection_path=connection_names.get(cid), endpoint_contributions=[{
                'physics_part_id': pids[index], 'part_path': part_names.get(pids[index]),
                'force_CC_N': wrench[index, :3].tolist(),
                'torque_CC_Nm': (wrench[index, 3:]*system['L0']).tolist()}
                for index in endpoint_rows])
            public = steps[step]['utilization'].get(connection_names.get(cid, ''))
            row['public_utilization_after_step'] = public
            row['public_match_when_available'] = None if public is None or public < 0 or not utilization_available else bool(np.isclose(public, utilization[k], rtol=1e-8, atol=1e-8))
            row['relaxation'] = {'available': False, 'reason': 'rlx_sol absent from serialized state'}
            if relaxation is not None:
                selected_rows = capacity_indices == k
                selected_V = relaxation['V'][selected_rows]
                one_hot = (selected_rows.any() and np.all(selected_V.getnnz(axis=1) == 1)
                    and np.all(np.asarray(selected_V[:, k].toarray()).ravel() == 1.))
                if one_hot:
                    row['relaxation'] = {'available': True, 'V_rows_one_hot_to_this_clutch_verified': True,
                        **relaxation_summary(relaxation['H_opt'][selected_rows], relaxation['H_rlx'][selected_rows],
                            relaxation['V_clamped'][selected_rows], relaxation['V_raw'][selected_rows],
                            relaxation['raw_v'][k], solution.get('info', {}), epsilon)}
                else:
                    row['relaxation'] = {'available': False, 'reason': 'Serialized V rows do not verify one-hot clutch correspondence'}
            clutches[str(cid)] = row
        parts = {}
        for pid in sorted(interested):
            index = pids.index(pid)
            tensor = inertia[index].reshape(3, 3, order='F')
            nominal_gravity_impulse = mass[index]*gravity*inp['dt']
            parts[str(pid)] = {'part_path': part_names.get(pid), 'mass_kg': float(mass[index]),
                'inertia_CC_kg_m2': tensor.tolist(), 'inertia_eigenvalues_kg_m2': np.linalg.eigvalsh((tensor+tensor.T)/2).tolist(),
                'com_world_m': centers[index].tolist(), 'linear_velocity_world_m_s': v[index].tolist(),
                'angular_velocity_world_rad_s': w[index].tolist(), 'external_linear_impulse_world_Ns': J[index].tolist(),
                'external_angular_impulse_world_Nms': H[index].tolist(),
                'nominal_gravity_impulse_world_Ns': nominal_gravity_impulse.tolist(),
                'external_minus_nominal_gravity_Ns_not_contact_only': (J[index]-nominal_gravity_impulse).tolist(),
                'equation_rhs_force_CC_N': rhs[index, :3].tolist(),
                'equation_rhs_torque_CC_Nm': (rhs[index, 3:]*system['L0']).tolist()}
        info = solution.get('info', {})
        record = {'step': step, 'dump': str(path.relative_to(args.input)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'dt_s': inp['dt'],
            'system': {key: system[key] for key in ('num_parts', 'num_clutches', 'num_vars', 'total_mass', 'L0')},
            'thresholds': dump['thresholds'], 'solver_info_serialized': info,
            'slack_fraction_serialized': solution['slack_fraction'],
            'slack_fraction_recomputed': float(np.linalg.norm(slack)/max(np.linalg.norm(b), dump['thresholds']['slack_fraction_b_floor'])),
            'raw_rhs_residual_norm': float(np.linalg.norm(residual)),
            'projected_rhs_residual_norm': float(np.linalg.norm(projected_residual)),
            'rhs_norm': float(np.linalg.norm(b)), 'slack_norm': float(np.linalg.norm(slack)),
            'maximum_raw_rhs_residual_part': {'physics_part_id': pids[int(np.linalg.norm(residual.reshape(len(pids), 6), axis=1).argmax())]},
            'all_mass_range_kg': [float(mass.min()), float(mass.max())],
            'parts': parts, 'clutches': clutches, 'broken_connections_after_step': steps[step]['broken_connections']}
        records.append(record)
        del dump
    all_converged = all(row['solver_info_serialized'].get('converged') is True for row in records)
    matches = [c['public_match_when_available'] for row in records for c in row['clutches'].values()
               if c['public_match_when_available'] is not None]
    watched_overload = any(row['clutches'][str(cid)]['native_utilization'] is not None
        and row['clutches'][str(cid)]['native_utilization'] > 1 for row in records for cid in WATCHED)
    summary = {'schema': 'stage2-native-dump-audit-v3-coupled-epsilon', 'dump_count': len(records),
        'numerical_epsilon': epsilon_provenance,
        'part273_mapping': part_names.get(273), 'watched_connection_ids': list(WATCHED),
        'comparison_connection_ids': list(CONTROLS), 'all_serialized_solver_converged': all_converged,
        'all_available_selected_public_utilizations_match_dump': bool(matches) and all(matches),
        'first_utilization_over_one_step': {str(cid): next((r['step'] for r in records
            if r['clutches'][str(cid)]['native_utilization'] is not None and r['clutches'][str(cid)]['native_utilization'] > 1.), None) for cid in WATCHED+CONTROLS},
        'gravity_reference_world_m_s2': gravity.tolist(), 'records': records,
        'root_cause_status': ('Watched native capacity criterion exceeded before or at disconnection; this identifies a selection mechanism, not the underlying load origin.'
            if watched_overload else 'No watched capacity overload verified from available dump fields; underlying cause remains unresolved.'),
        'limitations': ['No solver or physics rerun, fit or parameter modification.',
            f'{count} dumps are paired chronologically with steps1..{count} under one full301/930component; selected public utilization comparisons audit this pairing.',
            'Solver status is reported only from serialized info; a converged capacity-relaxed optimization does not imply physical contact validation.',
            'Native J/H are momentum change minus internal weld impulses; gravity and contact were not independently logged. Gravity-subtracted values are a reference residual, not a contact sensor.',
            'CC-frame wrench reconstruction uses A and whitened opt_sol; native capacity terms use unwhitened solution.x.',
            'Stage3 intentionally permits Hx<=1+Vv after stage2 relaxation; utilization slightly above1 cannot be attributed solely to numerical solver error without inspecting v and the actual relaxed constraint gap.',
            'Cooldown only gates break selection and is not inferred as a cause.',
            'Updated fingertip geometry remains visual only; no grasping or hardware validation.']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'debug_analysis.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    lines = ['# Native breakage dump audit', '', 'Part273: '+str(summary['part273_mapping']), '',
        '|Step|Converged|Slack fraction|u836|u837|u832|u833|u922|u923|', '|---:|:---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in records:
        lines.append('|'+str(row['step'])+'|'+str(row['solver_info_serialized'].get('converged', 'unavailable'))+'|'+
            f"{row['slack_fraction_serialized']:.6g}|"+'|'.join('unavailable' if row['clutches'][str(cid)]['native_utilization'] is None else f"{row['clutches'][str(cid)]['native_utilization']:.6g}" for cid in WATCHED+CONTROLS)+'|')
    lines += ['', summary['root_cause_status'], '', 'Masses, inertia, impulses, normalized capacity terms, reconstructed wrenches and exact solver status/residuals are in debug_analysis.json.', '', 'The nominal gravity subtraction is not independently measured contact force. No parameter change is recommended from timing alone.']
    lines += ['', '## Watched relaxation bounds', '',
        '|Step|Clutch|v raw|v clamped|max Hx−1|max Vv|max relaxed gap|OSQP opt primal residual|',
        '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for row in records:
        for cid in WATCHED:
            values = row['clutches'][str(cid)]['relaxation']
            if values['available']:
                numeric = [values['raw_v_k'], values['clamped_v_k'], values['stage3_max_Hx_minus_one'],
                    values['stage3_Vv_range'][1], values['stage3_max_signed_gap_to_1_plus_Vv_bound'],
                    values['serialized_stage3_prim_res']]
                lines.append('|'+str(row['step'])+'|'+str(cid)+'|'+'|'.join('unavailable' if x is None else f'{x:.6g}' for x in numeric)+'|')
            else:
                lines.append(f"|{row['step']}|{cid}|unavailable||||||")
    lines += ['', f'Coupled numerical epsilon reference: {epsilon:g} ({epsilon_provenance["source"]}).',
        'v and Hx are normalized capacity quantities. Epsilon affects solver eps_abs/eps_rel, the G lower bound and the stage2 capacity margin together; this is not a pure termination-tolerance test. Exact per-row termination bounds are unavailable without solver z/scaling. This offline extension changes no physics and does not establish that any utilization excess is purely numerical.']
    (args.output/'REPORT.md').write_text('\n'.join(lines)+'\n')
    (args.output/'run_complete.json').write_text(json.dumps({'complete': True, 'dumps_analyzed': len(records),
        'analysis_sha256': hashlib.sha256((args.output/'debug_analysis.json').read_bytes()).hexdigest(),
        'matrix_loader_sha256': hashlib.sha256(args.matrix_loader.read_bytes()).hexdigest()})+'\n')
    print('DEBUG_DUMP_AUDIT_COMPLETE', len(records), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--matrix-loader', type=Path, default=Path(__file__).with_name('analysis_upstream')/'matrix_loader.py')
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Matrix dump analysis requires the frozen default Pueue queue')
    analyze(args)


if __name__ == '__main__':
    main()

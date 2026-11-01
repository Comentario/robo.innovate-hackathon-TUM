"""One frozen retrospective comparison; no simulation or controller installation."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from screen import screen_contact


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def numeric_cad(finger, side):
    return {'inner_plane_y_m': finger['inner_plane_y_m'],
        'expected_grip_normal_finger': [0, -1 if side == 'left' else 1, 0],
        **{role+'_surfaces': [{'vertices_finger_m': c['points_finger_m'],
            'triangle_indices': np.asarray(c['triangle_indices'], int).reshape(-1, 3).tolist()}
            for c in finger['colliders'] if c['enabled'] and c['role'] == role] for role in ('white', 'head')}}


def decisions(qualifier, associated, candidate, extra):
    """Labels never enter these two decisions; only the finite BODY term differs."""
    old = bool(qualifier['uniquely_pad_compatible'] and associated)
    expected = bool(qualifier['flat_face_compatible'] and qualifier['lateral_qualified']
        and min(qualifier['white_distance_m'], qualifier['head_distance_m']) > qualifier['tolerance_m']+extra and associated)
    return old, bool(candidate['compatible']), expected


def summarize(points):
    tables = {}
    for p in points:
        key = (p['case'], p['direction'], p['native_label'])
        row = tables.setdefault(key, {'case': key[0], 'direction': key[1], 'label': key[2],
            'count': 0, 'old_accepted': 0, 'candidate_accepted': 0, 'candidate_unknown': 0,
            'recovered_BODY': 0, 'lost_BODY': 0, 'forbidden_false_accepts': 0})
        row['count'] += 1; row['old_accepted'] += int(p['old_compatible'])
        row['candidate_accepted'] += int(p['candidate_compatible'])
        row['candidate_unknown'] += int(p['candidate_decision'] == 'UNKNOWN')
        row['recovered_BODY'] += int(p['native_label'] == 'BODY' and not p['old_compatible'] and p['candidate_compatible'])
        row['lost_BODY'] += int(p['native_label'] == 'BODY' and p['old_compatible'] and not p['candidate_compatible'])
        row['forbidden_false_accepts'] += int(p['native_label'] in ('WHITE', 'HEAD') and p['candidate_compatible'])
    return list(tables.values())


def audit(inputs):
    started = time.monotonic(); inputs = Path(inputs); protocol = json.loads(inputs.read_text())
    pins = protocol['input_sha256']; checks = {'execution_authorized': protocol['execution_authorized'] is True}
    checks['all_input_pins'] = all(sha(path) == digest for path, digest in pins.items())
    def read(path):
        path = Path(path).resolve()
        if str(path) not in pins:
            raise ValueError('Unpinned saved data: '+str(path))
        return json.loads(path.read_text())
    def raw(path):
        path = Path(path).resolve()
        if str(path) not in pins:
            raise ValueError('Unpinned contact array: '+str(path))
        with np.load(path, allow_pickle=False) as data:
            return {k: data[k].copy() for k in data.files}
    def trace(path):
        path = Path(path).resolve()
        if str(path) not in pins:
            raise ValueError('Unpinned saved trace')
        result = {}
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row['step'] in result: raise ValueError('Duplicate saved frame')
            result[row['step']] = row
        return result
    prior = protocol['prior_supervisor']
    checks['prior_clock_pin'] = sha(prior['path']) == prior['sha256']
    checks['prior_clock_value'] = json.loads(Path(prior['path']).read_text())['cumulative_case_seconds'] == protocol['prior_case_seconds']
    checks['bounded_budget'] = protocol['prior_case_seconds']+protocol['maximum_active_seconds'] <= protocol['aggregate_case_ceiling_seconds']
    manifest_path = inputs.parent.parent.parent/'manifest.json'
    # Normal snapshots retain the repo tree; the launcher manifest pins this code/protocol.
    manifest = json.loads(manifest_path.read_text())
    checks['snapshot_pins'] = all(sha(manifest_path.parent/p) == digest for p, digest in manifest['sha256'].items())
    mapper = load('frozen_counterfactual_mapper', ROOT/'experiments/stage2_collider_probe_20261025/evaluate.py')
    helper = mapper.load_helpers()
    legacy = load('frozen_rendered_association', ROOT/'experiments/stage2_closing_diagnostic_20261025/evaluate.py')
    contact = json.loads((ROOT/protocol['original_contact_protocol']).read_text())
    checks['frozen_thresholds'] = (protocol['force_floor_N'] == 1e-8 and protocol['parameters'] == {
        'point_surface_slack_m': contact['geometry']['pad_distance_allowance_m'],
        'white_head_clearance_extra_m': contact['geometry']['white_extra_clearance_m'],
        'minimum_outward_dot': contact['geometry']['side_contact']['minimum_outward_dot_grip_normal']})
    observations, current_bad_ids = [], set()
    for case in protocol['cases']:
        case_id = case['id']; snapshot = Path(case['snapshot']); capture = snapshot/'output'
        previous = read(case['audit']['path']); checks[case_id+'_audit_pin'] = sha(case['audit']['path']) == case['audit']['sha256']
        checks[case_id+'_validated_inputs'] = bool(previous.get('observation_contract_passed', previous.get('observation_complete', False)))
        public = trace(snapshot/case['trace']); geometry = read(snapshot/case['geometry'])
        observer = read(capture/'contact_observations/metadata.json')
        reciprocal = case['reciprocal_sensor']
        reciprocal_observer = observer if reciprocal == 'coupon' else read(capture/'evaluation_truth/contact_observations/metadata.json')
        private = public if reciprocal == 'coupon' else trace(snapshot/case['private_trace'])
        selection = None if case['kind'] == 'fixture_veto_stress' else read(snapshot/case['selection'])
        target = None if selection is None else reciprocal_observer['resolved_views'][reciprocal]['sensor_paths'][0]
        cads = {side: numeric_cad(finger, side) for side, finger in geometry['fingers'].items()}
        cad_before = json.dumps(cads, sort_keys=True)
        frame_proofs = [f for f in previous['frames'] if any(f['mapping'][s]['tensor_loaded_count'] for s in case['sensors'])]
        seen_rows = set(); counts = Counter(); reciprocal_counts = Counter()
        for f in frame_proofs:
            if time.monotonic()-started >= 8.5: raise TimeoutError('Fixed offline audit time exhausted; no partial promotion')
            step = f['step']; row = public[step]; source_row = private[step]
            event_finger_sides = {tuple(m['event']): side for side in case['sensors'] for m in f['mapping'][side]['matches']}
            reciprocal_events = {tuple(m['event']) for m in f['mapping'][reciprocal]['matches']}
            for sensor in [*case['sensors'], reciprocal]:
                is_reciprocal = sensor == reciprocal
                owner = source_row if is_reciprocal else row
                record = owner['contacts'][sensor]; data = raw(capture/record['file'])
                view = reciprocal_observer['resolved_views'][sensor] if is_reciprocal else observer['resolved_views'][sensor]
                paths = helper.filter_paths(view)
                loaded = mapper.tensor_points(data, paths, helper, 1/120, 1024, protocol['force_floor_N'])
                proof = f['mapping'][sensor]; mapping = {m['tensor_row']: m for m in proof['matches']}
                checks[f'{case_id}_{step}_{sensor}_coverage'] = (proof['status'] == 'MAPPED'
                    and len(loaded) == proof['tensor_loaded_count'] == len(mapping)
                    and {p['row'] for p in loaded} == set(mapping))
                online = {} if selection is None or is_reciprocal else {
                    p['row']: q for p, q in zip(sorted(loaded, key=lambda p: p['row']), row['point_ownership'][sensor])}
                for point in loaded:
                    index = point['row']; match = mapping[index]; event_id = tuple(match['event'])
                    side = event_finger_sides.get(event_id) if is_reciprocal else sensor
                    if side not in cads: raise ValueError('Reciprocal event has no unique finger-side association')
                    checks[f'{case_id}_{step}_{sensor}_event_pairing'] = checks.get(f'{case_id}_{step}_{sensor}_event_pairing', True) and event_id in reciprocal_events
                    identifier = f'{case_id}:{step}:{sensor}:{index}'
                    if identifier in seen_rows: raise ValueError('Duplicate scored raw row')
                    seen_rows.add(identifier)
                    if selection is None:
                        associated, association_scope = True, 'FORCED_TRUE_NEGATIVE_COMPONENT_STRESS_NO_PERCEPTION'
                    else:
                        associated = legacy.spatial_match(point['position'], selection['candidate'], selection['supported_upper_surface_m'])
                        association_scope = 'UNCHANGED_RENDERED_CANDIDATE_SPATIAL_FORMULA'
                        if not is_reciprocal:
                            checks[f'{identifier}_association'] = associated == online[index]['spatial_candidate_association']
                    pose = row['finger_poses_world_wxyz'][side]
                    outward = (1 if is_reciprocal else -1)*point['normal']
                    # No native label, path, partner or BODY geometry is an input to the candidate.
                    candidate = screen_contact(point['position'], point['separation'], outward, pose, cads[side], associated)
                    qualifier = helper.classify_point(point['position'], point['separation'], pose,
                        geometry['fingers'][side]['colliders'], contact, outward_world=outward,
                        flat_face_y_m=cads[side]['inner_plane_y_m'], expected_grip_normal_finger=cads[side]['expected_grip_normal_finger'])
                    old, new, expected = decisions(qualifier, associated, candidate, contact['geometry']['white_extra_clearance_m'])
                    checks[identifier+'_only_finite_term_removed'] = new == expected
                    checks[identifier+'_no_permission'] = candidate['body_ownership_established'] is False and candidate['pick_permission'] is False
                    evidence = candidate['evidence']
                    checks[identifier+'_numeric_evidence'] = all(abs(evidence[a]-qualifier[b]) <= 1e-10 for a, b in (
                        ('flat_plane_distance_m', 'flat_face_distance_m'), ('tolerance_m', 'tolerance_m'),
                        ('outward_dot_grip_normal', 'outward_dot_grip_normal'), ('white_distance_m', 'white_distance_m'), ('head_distance_m', 'head_distance_m')))
                    if selection is not None and not is_reciprocal:
                        checks[identifier+'_old_qualification'] = (qualifier['unique_body_geometry'] == online[index]['unique_body']
                            and qualifier['uniquely_pad_compatible'] == online[index]['lateral_qualified'])
                    label = match['role'].upper()  # Evaluator-only label attached AFTER both decisions.
                    (reciprocal_counts if is_reciprocal else counts)[label] += 1
                    partner_scope = ('FIXTURE_STRESS' if selection is None else 'UNKNOWN' if label not in ('BODY', 'WHITE', 'HEAD')
                                     else 'SELECTED' if is_reciprocal or point['partner'] == target else 'UNSELECTED')
                    observations.append({'id': identifier, 'case': case_id, 'step': step, 'sensor': sensor, 'side': side,
                        'direction': 'reciprocal_verification_only' if is_reciprocal else 'primary_finger',
                        'private_event_pair': list(event_id),
                        'raw_row': index, 'raw_index': int(data['normal_indices'][index]), 'native_label': label,
                        'private_partner_scope': partner_scope, 'association_scope': association_scope, 'rendered_association': associated,
                        'old_compatible': old, 'candidate_compatible': new, 'candidate_decision': candidate['decision'],
                        'candidate_reasons': candidate['reasons'], 'candidate_evidence': evidence,
                        'old_pad_distance_m': qualifier['pad_distance_m'], 'tolerance_m': qualifier['tolerance_m']})
        checks[case_id+'_all_primary_counts'] = dict(counts) == protocol['expected_counts'][case_id]
        checks[case_id+'_reciprocal_counts'] = dict(reciprocal_counts) == dict(counts)
        checks[case_id+'_cad_immutable'] = json.dumps(cads, sort_keys=True) == cad_before
        if case['kind'] == 'retrospective_closing':
            current_bad_ids.update(f"{case_id}:{p['step']}:{p['side']}:{p['tensor_row']}" for p in previous['current_bad_points'])
    checks['inputs_unchanged'] = all(sha(path) == digest for path, digest in pins.items())
    primary = [p for p in observations if p['direction'] == 'primary_finger']
    checks['238_primary_observations'] = len(primary) == 238
    pairs = {}
    for point in observations:
        key = (point['case'], point['step'], point['side'], tuple(point['private_event_pair']))
        pairs.setdefault(key, []).append(point)
    checks['exact_reciprocal_event_pairs'] = (len(pairs) == len(primary) and all(len(v) == 2
        and {p['direction'] for p in v} == {'primary_finger', 'reciprocal_verification_only'}
        and len({p['native_label'] for p in v}) == 1 for v in pairs.values()))
    disagreements = [sorted(p['id'] for p in v) for v in pairs.values() if len({(p['old_compatible'], p['candidate_compatible']) for p in v}) > 1]
    recovered = [p['id'] for p in primary if p['native_label'] == 'BODY' and not p['old_compatible'] and p['candidate_compatible']]
    lost = [p['id'] for p in primary if p['native_label'] == 'BODY' and p['old_compatible'] and not p['candidate_compatible']]
    complete = all(checks.values())
    return mapper.json_native({'evaluation_complete': complete, 'proceed_gate_passed': False, 'counterfactual_only': True,
        'checks': checks, 'failed_checks': [k for k, v in checks.items() if not v], 'tables': summarize(observations),
        'primary_finger_observations': len(primary), 'reciprocal_observations_verification_only': len(observations)-len(primary),
        'recovered_BODY_ids': recovered, 'lost_BODY_ids': lost,
        'current_bad_point_counterfactual_recovered': sorted(current_bad_ids.intersection(recovered)),
        'reciprocal_decision_disagreements_verification_only': disagreements,
        'partner_scopes': {scope: sum(p['private_partner_scope'] == scope for p in primary)
                           for scope in ('FIXTURE_STRESS', 'SELECTED', 'UNSELECTED', 'UNKNOWN')}, 'points': observations,
        'wall_seconds': time.monotonic()-started, 'policy_installed': False, 'grasp_or_hardware_permission': False,
        'interpretation': protocol['interpretation']})


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False); parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Saved-array work requires default Pueue')
    args.output.mkdir(parents=True, exist_ok=True)
    try: result = audit(args.inputs)
    except Exception as error:
        result = {'evaluation_complete': False, 'proceed_gate_passed': False, 'counterfactual_only': True,
                  'error': str(error), 'policy_installed': False, 'grasp_or_hardware_permission': False}
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__': main()

"""Saved handoff equivalence/binding audit, not a new color or grasp benchmark."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
CONTROLS = {'no_candidate', 'frame_mismatch', 'stale_frame', 'rgb_content_mismatch',
    'depth_content_mismatch', 'calibration_mismatch', 'candidate_geometry_mismatch', 'abort', 'slip', 'historical_abort'}
CONTROL_REASONS = {'no_candidate': 'no_final_candidate', 'frame_mismatch': 'frame_mismatch',
    'stale_frame': 'stale_frame', 'rgb_content_mismatch': 'rgb_array_sha256_mismatch',
    'depth_content_mismatch': 'depth_array_sha256_mismatch', 'calibration_mismatch': 'calibration_sha256_mismatch',
    'candidate_geometry_mismatch': 'candidate_geometry_mismatch', 'abort': 'abort', 'slip': 'slip',
    'historical_abort': 'recorded_controller_abort'}


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value): return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def calibration_numbers(cal):
    return {'K': [[float(x) for x in row] for row in cal['K']],
        'R': [[float(x) for x in row] for row in cal['R']], 't': [float(x) for x in cal['t']]}


def indexed(rows, keys):
    result = {}
    for row in rows:
        key = tuple(row[k] for k in keys)
        if key in result: raise ValueError('Duplicate transaction key: '+str(key))
        result[key] = row
    return result


def no_held_claim(row):
    return row['held_identity'] == 'UNKNOWN' and row['held_color'] is None and row['transfer_authorized'] is False


def denied(row):
    return (no_held_claim(row) and row['status'] == 'INVALIDATED' and row['invalidated'] is True
        and bool(row['invalidation_reasons']) and row['freshness_verified'] is False)


def binding_checks(transaction, candidate, frame, rgb_hash, depth_hash, cal, refs, timed):
    binding = transaction['observation_binding']
    return {'identity': transaction['frame_id'] == frame['frame_id'] and transaction['candidate_id'] == candidate['candidate_id']
            and binding['frame_id'] == frame['frame_id'] and binding['candidate_id'] == candidate['candidate_id'],
        'clock': binding['measurement_time_s'] == frame['measurement_time_s']
            and transaction['classified_at_time_s'] == frame['measurement_time_s']
            and transaction['freshness_verified'] is timed,
        'candidate': binding['candidate_sha256'] == binding['expected_candidate_sha256'] == digest(candidate),
        'file_hashes': binding['rgb_file_sha256'] == rgb_hash and binding['depth_file_sha256'] == depth_hash,
        'calibration': binding['calibration'] == cal and binding['calibration_sha256'] == digest(cal),
        'arrays_bound': all(binding['input_digests'][key] == binding[key] and isinstance(binding[key], str)
            and len(binding[key]) == 64 for key in ('rgb_array_sha256', 'depth_array_sha256', 'calibration_sha256')),
        'frozen_references': all(binding[key] == value for key, value in refs.items()),
        'source_only': no_held_claim(transaction) and transaction['status'] == 'SOURCE_ONLY'
            and transaction['invalidated'] is False and transaction['invalidation_reasons'] == []}


def evaluate(inputs, baselines, predictions):
    inputs, baselines, predictions = map(Path, (inputs, baselines, predictions))
    plan = read(HERE/'protocol.json'); replay = read(predictions/'replay.json')
    original = Path(plan['source_color_snapshot']); repository = original.parent.parent
    pins = plan['frozen_inputs_sha256']
    checks = {'execution_authorized': plan['execution_authorized'] is True,
        'completed': replay['completed'] is True,
        'fixed_frames_processed': replay['processed_frame_ids'] == plan['frame_ids'] == ['f000', 'f001', 'f002', 'f004', 'f006'],
        'one_frozen_replay': plan['maximum_jobs'] == 1 and plan['maximum_improvement_rounds'] == 0 and plan['automatic_retry'] is False}
    for relative, expected in pins.items(): checks['frozen_'+relative] = sha(repository/relative) == expected
    prefix = 'runs/'+original.name+'/'
    expected_refs = {'classifier_sha256': pins[prefix+'code/color.py'], 'settings_sha256': pins[prefix+'code/settings.json'],
        'prototypes_sha256': pins[prefix+'predictions/prototypes.json']}
    for key, filename in [('classifier_sha256', 'color.py'), ('settings_sha256', 'settings.json'), ('prototypes_sha256', 'prototypes.json')]:
        checks['copied_'+filename] = sha(inputs/filename) == expected_refs[key] == replay['source_pins'][key]
    expected_refs.update(settings_content_sha256=digest(read(inputs/'settings.json')),
        prototypes_content_sha256=digest(read(inputs/'prototypes.json')))
    checks['source_content_refs'] = all(replay['source_pins'][k] == v for k, v in expected_refs.items())
    checks['adapter_pin'] = replay['source_pins']['adapter_sha256'] == sha(HERE/'adapter.py')
    package, frames = read(inputs/'calibration.json'), read(inputs/'frames.json')
    checks['copied_frame_package'] = sha(inputs/'frames.json') == pins[prefix+'public/frames.json'] and sha(inputs/'calibration.json') == pins[prefix+'public/calibration.json']
    transactions = indexed(replay['transactions'], ('case_id', 'frame_id', 'candidate_id'))
    expected_keys = set(); counts = {}; raw_known = raw_unknown = 0
    for frame_id in plan['frame_ids']:
        frame = next(f for f in frames if f['id'] == frame_id)
        packet = read(inputs/frame['candidates']); baseline = read(baselines/(frame_id+'.json'))
        checks[frame_id+'_baseline_pin'] = sha(baselines/(frame_id+'.json')) == pins[prefix+'predictions/'+frame_id+'.json']
        for kind in ('rgb', 'depth', 'candidates'):
            checks[frame_id+'_'+kind+'_pin'] = sha(inputs/frame[kind]) == pins[prefix+'public/'+frame[kind]]
        baseline_rows = indexed(baseline['classifications'], ('frame_id', 'candidate_id'))
        candidates = indexed(packet['candidates'], ('candidate_id',))
        checks[frame_id+'_candidate_inventory'] = packet['frame_id'] == baseline['frame_id'] == frame_id and set(baseline_rows) == {(frame_id, c[0]) for c in candidates}
        view = package['views'][frame['camera']]
        cal = calibration_numbers({'K': package['K'], 'R': view['R_world_to_camera'], 't': view['t_world_to_camera_m']})
        counts[frame_id] = {'candidates': len(candidates), 'known': 0, 'unknown': 0}
        for (candidate_id,), candidate in candidates.items():
            key = ('stage1_'+frame_id, frame_id, candidate_id); expected_keys.add(key)
            transaction = transactions.get(key)
            checks[frame_id+'_'+candidate_id+'_exists'] = transaction is not None
            if transaction is None: continue
            checks[frame_id+'_'+candidate_id+'_exact_color_equivalence'] = transaction['source_color'] == baseline_rows[(frame_id, candidate_id)]
            for name, passed in binding_checks(transaction, candidate, {'frame_id': frame_id, 'measurement_time_s': None},
                    sha(inputs/frame['rgb']), sha(inputs/frame['depth']), cal, expected_refs, False).items():
                checks[frame_id+'_'+candidate_id+'_'+name] = passed
            decision = transaction['source_color']['decision'] if transaction['source_color'] else 'missing'
            if decision in counts[frame_id]: counts[frame_id][decision] += 1
        raw_known += counts[frame_id]['known']; raw_unknown += counts[frame_id]['unknown']
    selected_root = Path(plan['selected_pick_snapshot'])/'output'
    full_selection = read(selected_root/'online/selection.json'); reduced = read(inputs/'selected_stage2/selection.json')
    expected_selection_hash = sha(selected_root/'online/selection.json')
    checks['selected_original_pin'] = reduced['original_selection_sha256'] == replay['selected_selection_sha256'] == expected_selection_hash
    checks['selected_final_candidate'] = all(reduced[k] == full_selection[k] for k in ('frame_id', 'measurement_time_s', 'candidate'))
    selected_views = [v for v in full_selection['geometry_views'] if v['frame_id'] == full_selection['frame_id']]
    if len(selected_views) != 1: raise ValueError('Selected observation calibration is missing or ambiguous')
    cal = calibration_numbers({k: selected_views[0]['calibration'][k] for k in ('K', 'R', 't')})
    checks['selected_calibration'] = reduced['calibration'] == cal
    checks['selected_RGB_original'] = sha(inputs/'selected_stage2/rgb.png') == sha(selected_root/full_selection['rgb'])
    checks['selected_depth_original'] = sha(inputs/'selected_stage2/depth.npz') == sha(selected_root/full_selection['depth'])
    key = ('stage2_selected', reduced['frame_id'], reduced['candidate']['candidate_id']); expected_keys.add(key)
    selected = transactions.get(key); checks['selected_record_exists'] = selected is not None
    checks['exact_transaction_inventory'] = set(transactions) == expected_keys
    if selected:
        for name, passed in binding_checks(selected, reduced['candidate'], reduced,
                sha(inputs/'selected_stage2/rgb.png'), sha(inputs/'selected_stage2/depth.npz'), cal, expected_refs, True).items():
            checks['selected_'+name] = passed
        source = selected['source_color']
        checks['selected_color_identity'] = source is not None and source['frame_id'] == reduced['frame_id'] and source['candidate_id'] == reduced['candidate']['candidate_id'] and source['source_decision'] == reduced['candidate']['decision']
    marker = read(inputs/'selected_stage2/capture_complete.json')
    checks['historical_marker_pin'] = sha(inputs/'selected_stage2/capture_complete.json') == sha(selected_root/'position_pick_complete.json')
    checks['historical_run_aborted'] = marker['controller_status'] == replay['stage2_recorded_outcome']['controller_status'] == 'aborted' and marker == replay['stage2_recorded_outcome']
    controls = indexed(replay['controls'], ('id',)); checks['all_fixed_controls'] = {k[0] for k in controls} == CONTROLS
    for (name,), entry in controls.items():
        transaction = entry['transaction']; checks[name+'_denied'] = denied(transaction)
        checks[name+'_reason'] = CONTROL_REASONS.get(name) in transaction['invalidation_reasons']
        if name in ('abort', 'slip', 'historical_abort') and selected:
            checks[name+'_source_evidence_immutable'] = transaction['source_color'] == selected['source_color'] and transaction['observation_binding'] == selected['observation_binding']
        elif name != 'stale_frame': checks[name+'_no_classification'] = transaction['source_color'] is None
    final = replay['stage2_final_transaction']
    checks['historical_abort_final'] = final == controls.get(('historical_abort',), {}).get('transaction') and denied(final) and final['invalidated_at_time_s'] is None and 'recorded_controller_abort' in final['invalidation_reasons']
    checks['no_held_or_transfer_claims'] = all(no_held_claim(row) for row in replay['transactions'])
    prior = read(original/'audit/evaluation.json')
    return {'handoff_contract_passed': bool(all(checks.values())), 'checks': checks,
        'failed_checks': [k for k, v in checks.items() if not v], 'raw_equivalence_counts': counts,
        'raw_known_including_calibration': raw_known, 'raw_unknown': raw_unknown,
        'prior_accuracy_only': {k: prior['summary'][k] for k in ('correct', 'eligible_present_observations', 'all_visible_observations', 'eligible_present_unique_objects')},
        'prior_limitations_preserved': prior['limitations'], 'new_accuracy_evaluated': False,
        'selected_source_color': selected['source_color'] if selected else None,
        'selected_final_status': final['status'], 'held_identity': 'UNKNOWN', 'transfer_authorized': False,
        'grasp_or_retention_claim': False,
        'scope': 'Saved adapter replay equivalence and source-observation binding; live Stage2 callsite and manipulation not executed.',
        'protocol_sha256': sha(HERE/'protocol.json')}


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('--inputs', type=Path, required=True); parser.add_argument('--baselines', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    start = time.monotonic(); result = evaluate(args.inputs, args.baselines, args.predictions)
    result['audit_seconds'] = time.monotonic()-start; args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    if not result['handoff_contract_passed']: raise SystemExit(1)


if __name__ == '__main__': main()

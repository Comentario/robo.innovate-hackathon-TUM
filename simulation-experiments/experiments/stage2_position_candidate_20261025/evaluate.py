"""Round1 admission audit; inherited physical checks and real force data stay intact."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


parent = load('frozen_plane_pick_parent', ROOT/'experiments/stage2_plane_pick_20261025/evaluate.py')


def raw_position_sample(row, meta, plan, raw_forces=None):
    indices = meta['finger_joint_indices']; commands = np.asarray(row['joint_commands'])[indices]
    actual = np.asarray(row['q'])[indices]; errors = actual-commands
    endpoint = meta['endpoint_preflight']
    left = endpoint['fingers']['left']['opening_axis_hand'][1]
    right = endpoint['fingers']['right']['opening_axis_hand'][1]
    actual_gap = endpoint['gap_intercept_m']+left*actual[0]-right*actual[1]
    command_gap = endpoint['gap_intercept_m']+left*commands[0]-right*commands[1]
    at_endpoint = (row['phase'] == 'close' and abs(row['finger_command_scalar_m']-endpoint['endpoint_q_m']) <= plan['endpoint_command_tolerance_m'])
    forces = row['normal_force_per_pad_N'] if raw_forces is None else raw_forces
    sample = bool(at_endpoint and not row['stop_reasons'] and all(v > plan['position_contact_floor_N'] for v in forces.values())
        and np.all(errors > plan['blocked_finger_allowance_m']) and actual_gap-command_gap > plan['blocked_gap_allowance_m'])
    return sample, errors, float(actual_gap), float(command_gap)


class AdmissionAudit(parent.ContactAudit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.position_count = 0; self.position_candidate = None; self.admission = None
        self.force_only_reference = Counter(); self.window = []; self.admission_window = []

    def closure(self, row, geometry, detail, checks):
        super().closure(row, geometry, detail, checks)
        sample, errors, actual_gap, command_gap = raw_position_sample(row, self.meta, self.plan, detail['peak_N'])
        self.position_count = self.position_count+1 if sample else 0
        at_endpoint = row['phase'] == 'close' and abs(row['finger_command_scalar_m']-self.meta['endpoint_preflight']['endpoint_q_m']) <= self.plan['endpoint_command_tolerance_m']
        if at_endpoint:
            indices = self.meta['finger_joint_indices']
            self.window = (self.window+[{'step': row['step'], 'endpoint_settle_completed_commands': self.endpoint_count,
                'sample_passed': sample, 'forces_N': row['normal_force_per_pad_N'],
                'actual_finger_q_m': np.asarray(row['q'])[indices].tolist(),
                'commanded_finger_q_m': np.asarray(row['joint_commands'])[indices].tolist(),
                'finger_tracking_errors_m': errors.tolist(), 'actual_joint_gap_m': actual_gap,
                'commanded_joint_gap_m': command_gap}])[-self.plan['candidate_consecutive_steps']:]
        else:
            self.window = []
        checks['position_sample_matches_raw'] = (row['position_candidate_sample'] is sample
            and row['position_candidate_consecutive_steps'] == self.position_count
            and np.max(abs(np.asarray(row['finger_tracking_errors_m'])-errors)) <= 1e-12
            and abs(row['actual_joint_gap_m']-actual_gap) <= 1e-12
            and abs(row['commanded_joint_gap_m']-command_gap) <= 1e-12)
        commands = np.asarray(row['joint_commands'])[self.meta['finger_joint_indices']]
        if self.admission is None and not row['stop_reasons']:
            if self.confirmation is not None:
                self.admission = {'kind': 'force_confirmation', 'step': row['step'], 'command_q_m': float(commands[0])}
            elif (self.endpoint_count == self.plan['endpoint_settle_steps']
                    and self.position_count >= self.plan['candidate_consecutive_steps']):
                self.position_candidate = {'status': 'GRASP_CANDIDATE', 'step': row['step'],
                    'command_q_m': float(commands[0]), 'commanded_finger_q_m': commands.tolist(),
                    'consecutive_steps': self.position_count, 'endpoint_settle_completed_commands': self.endpoint_count,
                    'window': list(self.window)}
                self.admission_window = list(self.window)
                self.admission = {'kind': 'position_candidate', 'step': row['step'], 'command_q_m': float(commands[0])}
        # The old force-only check is reference evidence, never a fabricated force pass.
        if 'no_lift_before_confirmation' in checks:
            self.force_only_reference['no_lift_before_confirmation'] += int(not checks.pop('no_lift_before_confirmation'))
        checks['admission_before_lift'] = row['phase'] not in ('lift', 'hold') or self.admission is not None
        if self.admission:
            frozen = self.confirmation if self.admission['kind'] == 'force_confirmation' else self.position_candidate
            checks['last_command_targets_held_after_admission'] = bool(np.all(commands == frozen['command_q_m']))


def amend_force_prerequisites(result, adapter):
    """Replace only the force-dependent sequencing checks; preserve all outcome values."""
    checks = result['checks']; reference = {}
    for name in ('positive_force_trigger', 'detachment_after_grasp_trigger'):
        if name in checks: reference[name] = checks.pop(name)
    failures = result.get('frame_failure_counts', {})
    old_frames = failures.pop('force_trigger_before_lift', 0)
    if 'all_measured_frame_guards' in checks: checks['all_measured_frame_guards'] = not failures
    checks['positive_lift_admission'] = adapter.admission is not None
    detached = result['metrics'].get('first_singleton_step')
    checks['detachment_after_lift_admission'] = (detached is not None and adapter.admission is not None and detached >= adapter.admission['step'])
    result['force_only_reference_checks'] = reference
    result['force_only_reference_frame_failures'] = {'force_trigger_before_lift': old_frames,
                                                    **dict(adapter.force_only_reference)}
    return result


def audit(folder, started):
    folder = Path(folder); plan = read(HERE/'protocol.json')
    parent.HERE = HERE  # Same inherited audit, current method protocol and source_science.
    parent_load, parent_read, adapters = parent.load, parent.read, []
    def load_with_admission(name, path):
        module = parent_load(name, path)
        if name == 'immutable_full_pick_audit':
            original = module.audit
            def with_force_references(*args, **kwargs):
                result = original(*args, **kwargs)
                if adapters: result = amend_force_prerequisites(result, adapters[-1])
                return result
            module.audit = with_force_references
        return module
    def current_marker(path):
        if Path(path) == folder/'plane_pick_complete.json': return read(folder/'position_pick_complete.json')
        return parent_read(path)
    class CurrentAdmission(AdmissionAudit):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs); adapters.append(self)
    parent.load = load_with_admission; parent.read = current_marker; parent.ContactAudit = CurrentAdmission
    result = parent.audit(folder, started)
    adapter = adapters[-1]; meta = adapter.meta; checks = result['checks']
    checks['round1_only'] = plan['improvement_round'] == plan['maximum_authorized_improvement_rounds'] == 1
    evidence = plan['baseline_failure_evidence']
    for key, item in evidence.items():
        if isinstance(item, dict) and 'sha256' in item:
            checks['baseline_failure_'+key+'_pin'] = sha(item['path']) == item['sha256']
    failed = read(evidence['audit']['path'])
    checks['baseline_failure_preserved'] = failed['physics_extraction_passed'] is False and failed['force_confirmation'] is None
    snapshot = Path(plan['source_snapshot']); manifest = read(snapshot/'manifest.json')
    relative = 'experiments/stage2_plane_pick_20261025/evaluate.py'
    checks['frozen_parent_auditor'] = sha(ROOT/relative) == manifest['sha256'][relative]
    checks['position_candidate_record'] = meta['position_candidate'] == adapter.position_candidate
    checks['lift_admission_record'] = meta['lift_admission'] == adapter.admission
    checks['no_fabricated_force_confirmation'] = (adapter.admission is None or adapter.admission['kind'] != 'position_candidate'
                                                  or meta['grasp_confirmation'] is None and adapter.confirmation is None)
    checks['force_reference_record_consistent'] = meta['force_confirmation_reference_passed'] is (meta['grasp_confirmation'] is not None)
    passed = all(checks.values())
    result.update(physics_extraction_passed=passed, proceed_gate_passed=passed, checks=checks,
        failed_checks=[k for k, v in checks.items() if not v], position_candidate=meta['position_candidate'],
        lift_admission=meta['lift_admission'], last_fresh_position_window=adapter.window,
        verified_admission_position_window=adapter.admission_window,
        force_confirmation=meta['grasp_confirmation'], phase_admission_only_amended=True,
        secure_grasp_claim_from_candidate=False, transfer_authorized=False, H_authorized=False, automatic_retry=False,
        wall_seconds=time.monotonic()-started)
    mapper = load('native_json_normalizer', ROOT/'experiments/stage2_collider_probe_20261025/evaluate.py')
    return mapper.json_native(result)


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False); parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True); args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    args.output.mkdir(parents=True, exist_ok=True); started = time.monotonic()
    try: result = audit(args.input, started)
    except Exception as error:
        result = {'physics_extraction_passed': False, 'proceed_gate_passed': False, 'error': str(error),
                  'transfer_authorized': False, 'H_authorized': False, 'automatic_retry': False}
    (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


if __name__ == '__main__': main()

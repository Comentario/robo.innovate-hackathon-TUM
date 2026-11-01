"""JSON-only dependency coverage check; never opens an NPZ or runs a screen."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def trace(path):
    return {row['step']: row for row in map(json.loads, Path(path).read_text().splitlines())}


def requirements(protocol):
    required, empty = set(), set()
    for case in protocol['cases']:
        snapshot = Path(case['snapshot']); report = read(case['audit']['path'])
        public = trace(snapshot/case['trace'])
        private = trace(snapshot/case['private_trace']) if 'private_trace' in case else public
        for frame in report['frames']:
            if not any(frame['mapping'][side]['tensor_loaded_count'] for side in case['sensors']):
                continue
            for sensor in [*case['sensors'], case['reciprocal_sensor']]:
                owner = private if sensor == case['reciprocal_sensor'] else public
                path = str((snapshot/'output'/owner[frame['step']]['contacts'][sensor]['file']).resolve())
                required.add(path)
                if frame['mapping'][sensor]['tensor_loaded_count'] == 0:
                    empty.add(path)
    return required, empty


def main():
    protocol = read(HERE/'protocol.json'); repair = protocol['manifest_repair']
    required, empty = requirements(protocol)
    pins = protocol['input_sha256']
    assert required <= set(pins), sorted(required-set(pins))
    assert all(Path(path).is_file() for path in required)
    original = Path(repair['original_result']['path'])
    old = read(original.parent.parent/'experiments/stage2_contact_screen_20261025/protocol.json')
    added = set(pins)-set(old['input_sha256'])
    assert added == required-set(old['input_sha256']) and added <= empty
    assert len(added) == 18 and len(pins) == 156
    assert all(pins[path] == digest for path, digest in old['input_sha256'].items())
    for key in ('cases', 'parameters', 'expected_counts', 'force_floor_N', 'interpretation',
                'reciprocal_semantics', 'original_contact_protocol', 'source_snapshot'):
        assert protocol[key] == old[key], key
    for name, digest in repair['candidate_and_evaluator_unchanged'].items():
        assert hashlib.sha256((HERE/name).read_bytes()).hexdigest() == digest, name
    assert hashlib.sha256(original.read_bytes()).hexdigest() == repair['original_result']['sha256']
    failed = read(original)
    assert failed['evaluation_complete'] is False and 'Unpinned contact array' in failed['error']
    assert 'points' not in failed and 'tables' not in failed
    print(f'PASS: {len(required)} required contact files pinned; exactly18 added empty opposite-finger dependencies; no NPZ opened; candidate/scorer unchanged')


if __name__ == '__main__': main()

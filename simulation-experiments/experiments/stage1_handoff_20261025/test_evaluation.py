"""Tiny handoff-audit contract tests; no image/depth or saved-data processing."""
import copy
from evaluate import indexed, denied, no_held_claim, binding_checks, digest, calibration_numbers


def main():
    assert indexed([], ('id',)) == {}
    assert indexed([{'id': 'a'}], ('id',)) == {('a',): {'id': 'a'}}
    try: indexed([{'id': 'a'}, {'id': 'a'}], ('id',))
    except ValueError: pass
    else: raise AssertionError('Duplicate accepted')
    value = {'held_identity': 'UNKNOWN', 'held_color': None, 'transfer_authorized': False,
        'status': 'INVALIDATED', 'invalidated': True, 'invalidation_reasons': ['abort'], 'freshness_verified': False}
    assert denied(value) and no_held_claim(value)
    assert not denied({**value, 'transfer_authorized': True})
    assert not denied({**value, 'held_color': 'tan'})
    assert not denied({**value, 'freshness_verified': True})
    assert not denied({**value, 'status': 'SOURCE_ONLY'})
    candidate = {'candidate_id': 'second_candidate', 'decision': 'present', 'image_polygon': [[0, 0], [1, 0], [1, 1], [0, 1]]}
    frame = {'frame_id': 'f', 'measurement_time_s': 1.}
    cal = calibration_numbers({'K': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 'R': [[1, 0, 0], [0, 1, 0], [0, 0, 1]], 't': [0, 0, 0]})
    refs = {'classifier_sha256': 'classifier'}
    binding = {**frame, 'candidate_id': candidate['candidate_id'], 'candidate_sha256': digest(candidate),
        'expected_candidate_sha256': digest(candidate), 'rgb_file_sha256': 'rgb', 'depth_file_sha256': 'depth',
        'rgb_array_sha256': 'a'*64, 'depth_array_sha256': 'b'*64, 'calibration_sha256': digest(cal),
        'calibration': cal, **refs}
    binding['input_digests'] = {k: binding[k] for k in ('rgb_array_sha256', 'depth_array_sha256', 'calibration_sha256')}
    row = {'frame_id': 'f', 'candidate_id': candidate['candidate_id'], 'observation_binding': binding,
        'classified_at_time_s': 1., 'freshness_verified': True, 'held_identity': 'UNKNOWN', 'held_color': None,
        'transfer_authorized': False, 'status': 'SOURCE_ONLY', 'invalidated': False, 'invalidation_reasons': []}
    assert all(binding_checks(row, candidate, frame, 'rgb', 'depth', cal, refs, True).values())
    stale = {**row, 'classified_at_time_s': 2.}
    assert not all(binding_checks(stale, candidate, frame, 'rgb', 'depth', cal, refs, True).values())
    changed = copy.deepcopy(candidate); changed['image_polygon'][0][0] += 1
    assert not all(binding_checks(row, changed, frame, 'rgb', 'depth', cal, refs, True).values())
    print('PASS: unique joins, empty frame, exact final candidate/time binding and no held/transfer promotion')


if __name__ == '__main__': main()

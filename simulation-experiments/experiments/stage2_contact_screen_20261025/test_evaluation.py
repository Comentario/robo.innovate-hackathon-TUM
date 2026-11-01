"""Synthetic scoring and denominator checks; no saved observations are read."""
import json
from evaluate import decisions, numeric_cad, summarize


def main():
    q = {'uniquely_pad_compatible': False, 'flat_face_compatible': True, 'lateral_qualified': True,
         'white_distance_m': .02, 'head_distance_m': .03, 'tolerance_m': .00005}
    assert decisions(q, True, {'compatible': True}, .0001) == (False, True, True)
    assert decisions(q, False, {'compatible': False}, .0001) == (False, False, False)
    q['uniquely_pad_compatible'] = True
    assert decisions(q, True, {'compatible': True}, .0001) == (True, True, True)
    q['white_distance_m'] = .0001; q['uniquely_pad_compatible'] = False
    assert decisions(q, True, {'compatible': False}, .0001) == (False, False, False)
    rows = [
        {'case': 'synthetic', 'direction': 'primary_finger', 'native_label': 'BODY',
         'old_compatible': False, 'candidate_compatible': True, 'candidate_decision': 'UNVERIFIED_GRIP_PLANE_COMPATIBLE'},
        {'case': 'synthetic', 'direction': 'reciprocal_verification_only', 'native_label': 'BODY',
         'old_compatible': False, 'candidate_compatible': True, 'candidate_decision': 'UNVERIFIED_GRIP_PLANE_COMPATIBLE'},
        {'case': 'synthetic', 'direction': 'primary_finger', 'native_label': 'WHITE',
         'old_compatible': False, 'candidate_compatible': False, 'candidate_decision': 'INCOMPATIBLE'}]
    tables = summarize(rows)
    assert sum(t['count'] for t in tables if t['direction'] == 'primary_finger') == 2
    assert sum(t['count'] for t in tables if t['direction'] == 'reciprocal_verification_only') == 1
    assert sum(t['recovered_BODY'] for t in tables if t['direction'] == 'primary_finger') == 1
    assert sum(t['forbidden_false_accepts'] for t in tables) == 0
    surfaces = [{'enabled': True, 'role': role, 'points_finger_m': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                 'triangle_indices': [[0, 1, 2]], 'path': '/PRIVATE/'+role} for role in ('body', 'white', 'head')]
    cad = numeric_cad({'inner_plane_y_m': 0., 'colliders': surfaces}, 'left')
    assert set(cad) == {'inner_plane_y_m', 'expected_grip_normal_finger', 'white_surfaces', 'head_surfaces'}
    assert 'PRIVATE' not in json.dumps(cad) and 'body' not in json.dumps(cad).lower()
    assert len(cad['white_surfaces']) == len(cad['head_surfaces']) == 1
    print('PASS: finite-term-only scoring, separate primary/reciprocal denominators and numeric-only candidate CAD')


if __name__ == '__main__': main()

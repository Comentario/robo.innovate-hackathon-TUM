"""Synthetic attribution/privacy checks only; no captured files are opened."""
import copy
import json
from evaluate import attribution, finite_body_extent, private_free, spatial_match


def main():
    body = {'event': [0, 1, 2], 'role': 'body', 'collider': '/Robot/finger/body'}
    reciprocal = [{'event': [0, 1, 2]}]
    qualifier = {'flat_face_compatible': True, 'lateral_qualified': True,
        'unique_body_geometry': False, 'pad_distance_m': .0013,
        'white_distance_m': .025, 'head_distance_m': .018, 'tolerance_m': .000051}
    result = attribution(body, reciprocal, 'selected', 'selected', qualifier, .0001)
    assert result['status'] == 'IDENTIFIED_CURRENT_POINT' and result['finite_surface_only_failure']
    for source in ([], [{'event': [0, 1, 9]}]):
        result = attribution(body, source, 'selected', 'selected', qualifier, .0001)
        assert result['status'] == 'UNKNOWN' and result['robot_role'] is None
    result = attribution(body, reciprocal, 'selected', 'neighbor', qualifier, .0001)
    assert result['status'] == 'UNKNOWN' and not result['finite_surface_only_failure']
    for role in ('white', 'head', 'UNKNOWN'):
        assert not finite_body_extent(qualifier, role, .0001)
    for field in ('white_distance_m', 'head_distance_m'):
        ambiguous = copy.deepcopy(qualifier); ambiguous[field] = .0001
        assert not finite_body_extent(ambiguous, 'body', .0001)
    inside = copy.deepcopy(qualifier); inside['pad_distance_m'] = .00001
    assert not finite_body_extent(inside, 'body', .0001)
    off_plane = copy.deepcopy(qualifier); off_plane['flat_face_compatible'] = False
    assert not finite_body_extent(off_plane, 'body', .0001)
    assert private_free({'contacts': {'left': {'file': 'contact_observations/x.npz'}}, 'point_ownership': []})
    for value in ({'native_events_file': 'x'}, {'nested': [{'actor0': 'secret'}]}, {'id': '/World/brick'}):
        assert not private_free(value)
    candidate = {'table_xy_m': [0., 0.], 'yaw_table_rad': 0.}
    assert spatial_match([0., 0., .095], candidate, .1)
    assert not spatial_match([.1, 0., .095], candidate, .1)
    assert not spatial_match([0., 0., .2], candidate, .1)
    json.dumps(result, allow_nan=False)
    print('PASS: current-only dual-view attribution, neighbor/WHITE/HEAD ambiguity, finite BODY extent and public identity quarantine')


if __name__ == '__main__': main()

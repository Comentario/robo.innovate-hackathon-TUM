"""Read-only evidence from the unchanged 128-cap STOP; never promotes a candidate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('baseline', 'replay', 'diagnostic', 'scope', 'protocol', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1':
        raise RuntimeError('Default Pueue required')
    started = time.monotonic()
    def timeout(*_):
        raise TimeoutError('Fixed 10-second read-only audit budget exhausted')
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 10)
    import numpy as np
    from scipy.spatial import ConvexHull, cKDTree
    baseline, replay, failure, scope, protocol = [json.loads(p.read_text()) for p in
        (args.baseline, args.replay, args.diagnostic, args.scope, args.protocol)]
    checks = {}
    checks['baseline_pin'] = sha(args.baseline) == scope['baseline_artifact_sha256']
    checks['unchanged_protocol'] = (sha(args.protocol) == scope['construction_protocol_sha256'] ==
        baseline['protocol_sha256'] == replay['protocol_sha256'] == failure['construction_protocol_sha256'])
    checks['source_pins'] = all(failure[key] == protocol[key] for key in
        ('source_stl_sha256', 'source_features_sha256'))
    checks['scope_and_replay_pin'] = (replay['diagnostic_scope_sha256'] == sha(args.scope) and
        scope['resource_cap_change_authorized'] is False and scope['geometry_change_authorized'] is False)
    checks['unchanged_128_stop'] = (protocol['maximum_vertices_per_cell'] == 128 and
        failure['status'] == 'UNCHANGED128CAP_STOP' and all(
        item['status'] == 'STOP' and 'Fixed128-vertex CPU cap exceeded; no splitting' in item['error'] and
        item['proceed_gate_passed'] is False and item['cooking_authorized'] is False for item in (baseline, replay)) and
        failure['proceed_gate_passed'] is False)
    old, new = baseline['cells'], replay['cells']
    differing = [i for i in range(max(len(old), len(new))) if i >= len(old) or i >= len(new) or old[i] != new[i]]
    checks['all_27_retained_records_exact'] = len(old) == len(new) == 27 and not differing
    checks['failed_identity'] = (failure['id'] == 'front_body_bored_11' and
        failure['region'] == 'front_body_bored' and failure['sector'] == 11)
    d = failure['details']
    raw = np.asarray(d['raw_HSI_intersections_mm'], float)
    vertices = np.asarray(d['final_vertices_mm'], float)
    indices = np.asarray(d['first_hull_extreme_indices'], int)
    triangles = np.asarray(d['final_hull_triangles'], int)
    planes = np.asarray(d['final_hull_equations'], float)
    construction = np.asarray(d['construction_planes_mm'], float)
    checks['finite_arrays'] = all(np.isfinite(a).all() for a in (raw, vertices, planes, construction,
        np.asarray(d['LP_interior_mm']), np.asarray(d['LP_clearance_mm'])))
    first = ConvexHull(raw)
    hull = ConvexHull(vertices)
    checks['raw_extreme_provenance'] = np.array_equal(indices, first.vertices) and np.array_equal(vertices, raw[indices])
    checks['final_hull_provenance'] = np.array_equal(triangles, hull.simplices) and np.array_equal(planes, hull.equations)
    exact_planes = len(set(map(tuple, planes)))
    checks['counts_and_volume'] = (d['vertex_cap'] == 128 and len(vertices) > 128 and
        d['final_vertex_count'] == len(vertices) and d['raw_HSI_intersection_count'] == len(raw) and
        d['exact_unique_raw_HSI_intersections'] == len(np.unique(raw, axis=0)) and
        d['exact_unique_final_vertices'] == len(np.unique(vertices, axis=0)) and
        d['final_triangular_facet_count'] == len(triangles) and d['exact_unique_final_plane_rows'] == exact_planes and
        np.isfinite(hull.volume) and hull.volume > 0 and d['LP_clearance_mm'] > protocol['minimum_LP_clearance_mm'])
    nearest = cKDTree(vertices).query(vertices, k=2)[0][:, 1]
    cumulative = scope['baseline_process_wall_seconds'] + replay['construction_wall_seconds'] + time.monotonic() - started
    checks['cumulative_budget'] = cumulative <= scope['cumulative_construction_plus_audit_limit_seconds']
    report = {'schema': 'unchanged-128cap-readonly-audit-v1', 'proceed_gate_passed': False,
        'cooking_authorized': False, 'diagnostic_integrity_passed': all(checks.values()), 'checks': checks,
        'retained_cells': len(new), 'differing_retained_record_indices': differing, 'failed_cell': failure['id'],
        'raw_HSI_intersections': len(raw), 'final_vertices': len(vertices),
        'recomputed_final_hull_extreme_vertices': len(hull.vertices), 'triangulated_facets': len(triangles),
        'exact_unique_plane_rows_descriptive_only': exact_planes, 'final_hull_volume_mm3': float(hull.volume),
        'minimum_final_vertex_separation_mm': float(nearest.min()),
        'cumulative_construction_and_audit_seconds': cumulative,
        'input_sha256': {key: sha(getattr(args, key)) for key in ('baseline', 'replay', 'diagnostic', 'scope', 'protocol')},
        'limitations': ['Plane-row and triangle counts are not cooked polygon counts.',
            'Only the first failed cell is assessed; later cells and native cookability remain untested.',
            'No clustering, deduplication, fitting, cap change, geometry acceptance or cooking.']}
    signal.setitimer(signal.ITIMER_REAL, 0)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'evaluation.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    if not report['diagnostic_integrity_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

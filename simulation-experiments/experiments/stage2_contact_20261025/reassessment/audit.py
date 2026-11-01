"""One queued descriptive audit of saved LEFT query data; never promotes R3."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import struct
import sys
import time

import numpy as np
from scipy.spatial import ConvexHull, QhullError

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def topology(triangles):
    edges = np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]])
    counts = Counter(map(tuple, np.sort(edges, axis=1)))
    oriented = Counter(map(tuple, edges))
    return {'edge_count': len(counts), 'non_two_incident_edges': sum(c != 2 for c in counts.values()),
            'oriented_edge_mismatch': sum(abs(c-oriented[(b, a)]) for (a, b), c in oriented.items())}


def describe(hull, epsilon):
    vertices = np.asarray(hull['vertices_m'], float)
    planes = np.asarray(hull['planes'], float)
    if not np.isfinite(vertices).all() or not np.isfinite(planes).all():
        raise ValueError('Nonfinite saved hull')
    lengths = np.linalg.norm(planes[:, :3], axis=1)
    if np.any(lengths == 0) or not np.isfinite(lengths).all(): raise ValueError('Invalid saved SDK normal')
    planes = planes / lengths[:, None]
    faces = hull['polygons']
    if any(len(f) < 3 or min(f) < 0 or max(f) >= len(vertices) for f in faces):
        raise ValueError('Invalid saved polygon index range')
    triangles = np.asarray([[f[0], f[k], f[k+1]] for f in faces for k in range(1, len(f)-1)])
    t = vertices[triangles]; normals = np.cross(t[:, 1]-t[:, 0], t[:, 2]-t[:, 0])
    lengths = np.linalg.norm(normals, axis=1); degenerate = int(np.count_nonzero(lengths <= 1e-20))
    volume = float(np.sum(t[:, 0]*np.cross(t[:, 1], t[:, 2]))/6)
    direction = 1 if volume >= 0 else -1
    unit = direction*normals/np.maximum(lengths[:, None], 1e-30)
    fan_excess = float(np.max(np.einsum('fvi,fi->fv', vertices[None]-t[:, :1], unit)))
    own = max(float(np.max(abs(vertices[f]@p[:3]+p[3]))) for f, p in zip(faces, planes))
    planar = 0.
    for f in faces:
        p = vertices[f]
        for k in range(1, len(p)-1):
            n = np.cross(p[k]-p[0], p[k+1]-p[0]); length = np.linalg.norm(n)
            if length > 1e-20: planar = max(planar, float(np.max(abs((p-p[0])@(n/length)))))
    try: qhull = ConvexHull(vertices)
    except QhullError: qhull = None
    report = {**topology(triangles), 'vertices': len(vertices), 'polygons': len(faces),
              'triangles': len(triangles), 'degenerate_fan_triangles': degenerate,
              'signed_fan_volume_m3': volume, 'vertex_hull_volume_m3': float(qhull.volume) if qhull is not None else None,
              'vertex_hull_status': 'computed' if qhull is not None else 'unknown; Qhull rejected unmodified vertices',
              'absolute_volume_difference_m3': abs(abs(volume)-float(qhull.volume)) if qhull is not None else None,
              'polygon_fan_nonplanarity_max_m': planar, 'fan_convexity_excess_m': fan_excess,
              'SDK_own_polygon_plane_residual_max_m': own,
              'SDK_all_vertex_plane_residual_max_m': float(np.max(vertices@planes[:, :3].T+planes[:, 3]))}
    report['indexed_winding_eligible'] = bool(not report['non_two_incident_edges'] and
        not report['oriented_edge_mismatch'] and not degenerate and abs(volume) > 1e-24 and fan_excess <= epsilon)
    return report, (vertices, triangles, planes, qhull.equations if qhull is not None else None)


def membership(point, vertices, triangles, eligible, epsilon, allowance, distance, winding):
    d = distance(point, vertices, triangles)
    if not eligible or d <= epsilon:
        return {'state': 'unknown', 'surface_distance_m': d, 'winding': None}
    _, w = winding(point, vertices, triangles)
    state = 'outside' if abs(w) < allowance else 'inside' if abs(abs(w)-1) < allowance else 'unknown'
    return {'state': state, 'surface_distance_m': d, 'winding': w}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['input', 'stl', 'output']: parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB') != '1': raise RuntimeError('Default Pueue required')
    protocol = json.loads((HERE/'protocol.json').read_text()); started = time.monotonic()
    result = {'schema': protocol['schema'], 'proceed_gate_passed': False, 'R3_status': 'FAILED; closed',
              'protocol_sha256': sha(HERE/'protocol.json'), 'physical_collider_suitability': 'UNKNOWN'}
    def timeout(*_): raise TimeoutError('Frozen 60-second analysis budget exhausted; no retry')
    signal.signal(signal.SIGALRM, timeout); signal.setitimer(signal.ITIMER_REAL, protocol['maximum_wall_seconds'])
    try:
        if sha(args.input) != protocol['input_sha256'] or sha(args.stl) != protocol['stl_sha256']:
            raise ValueError('Frozen input hash mismatch')
        for name, digest in protocol['helper_sha256'].items():
            if sha(HERE.parent/'evaluation'/name) != digest: raise ValueError('Pinned helper changed: '+name)
        sys.path.insert(0, str(HERE.parent/'evaluation'))
        from evaluate import surface_distance
        from union_geometry import outside_winding
        data = json.loads(args.input.read_text()); config = data['config']; tip = data['tips']['left']
        if set(data['tips']) != {'left'} or len(tip['cooked_hulls']) != 32: raise ValueError('Expected retained LEFT32 only')
        epsilon = protocol['membership_epsilon_m']; allowance = protocol['winding_integer_allowance']
        described = [describe(h, epsilon) for h in tip['cooked_hulls']]
        result['hulls'] = [r for r, _ in described]
        raw = args.stl.read_bytes(); count = struct.unpack_from('<I', raw, 80)[0]
        if len(raw) != 84+50*count: raise ValueError('Unexpected frozen STL encoding')
        points = np.asarray([list(struct.iter_unpack('<fff', raw[84+50*i+12:84+50*i+48])) for i in range(count)])
        v, inverse = np.unique(points.reshape(-1, 3), axis=0, return_inverse=True); tri = inverse.reshape(-1, 3)
        r = config['registration']['left']; a = math.radians(r['rotation_z_deg'])
        rotation = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
        v = v*config['stl_unit_m']@rotation.T+r['translation_m']; st = topology(tri)
        constants = protocol['numerical_reporting_constants']; triangles = v[tri]
        reference_finite = bool(np.isfinite(v).all())
        reference_degenerate = int(np.count_nonzero(np.linalg.norm(np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0]), axis=1) <= constants['degenerate_fan_cross_product_norm_m2']))
        reference_volume = float(np.sum(triangles[:, 0]*np.cross(triangles[:, 1], triangles[:, 2]))/6) if reference_finite else None
        result['reference_STL_topology'] = {**st, 'finite': reference_finite, 'degenerate_triangles': reference_degenerate, 'signed_volume_m3': reference_volume}
        reference_eligible = bool(reference_finite and not reference_degenerate and abs(reference_volume) > constants['minimum_nonzero_signed_volume_m3'] and not st['non_two_incident_edges'] and not st['oriented_edge_mismatch'])
        witnesses = []; f = config['fidelity']
        for x in f['bore_x_cad_mm']:
            for k in range(f['bore_witnesses_per_x']):
                offset = np.zeros(2) if k == 0 else f['bore_witness_radius_mm']*np.array([math.cos((k-1)*math.pi/4), math.sin((k-1)*math.pi/4)])
                point = np.r_[x, np.asarray(f['bore_center_cad_yz_mm'])+offset]*config['stl_unit_m']@rotation.T+r['translation_m']
                reference = membership(point, v, tri, reference_eligible, epsilon, allowance, surface_distance, outside_winding)
                sdk = []; vertex = []; indexed = []
                for report, (hv, ht, hp, vp) in described:
                    sdk.append(float(np.max(hp[:, :3]@point+hp[:, 3])))
                    vertex.append(float(np.max(vp[:, :3]@point+vp[:, 3])) if vp is not None else None)
                    indexed.append(membership(point, hv, ht, report['indexed_winding_eligible'], epsilon, allowance, surface_distance, outside_winding))
                def union(values):
                    valid = [v for v in values if v is not None]
                    return 'inside' if any(v < -epsilon for v in valid) else 'outside' if len(valid) == len(values) and all(v > epsilon for v in valid) else 'unknown'
                wi = 'inside' if any(i['state'] == 'inside' for i in indexed) else 'outside' if all(i['state'] == 'outside' for i in indexed) else 'unknown'
                witnesses.append({'position_finger_m': point.tolist(), 'reference': reference,
                    'reference_free': reference['state'] == 'outside' and reference['surface_distance_m'] > protocol['reference_free_clearance_m'],
                    'SDK_halfspace_union': union(sdk), 'vertex_hull_union': union(vertex), 'indexed_winding_union': wi,
                    'indexed_per_hull': indexed, 'SDK_per_hull_max_residual_m': sdk, 'vertex_per_hull_max_residual_m': vertex,
                    'physical_interpretation': 'UNKNOWN; candidate representation comparison only'})
        if len(witnesses) != 27: raise ValueError('Frozen 27-witness contract changed')
        result.update(status='descriptive_complete', witnesses=witnesses, bounds_failure_preserved=protocol['bounds_failure_preserved'], missing_tip='right, untested')
    except Exception as error:
        result.update(status='STOP', error=repr(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0); result['wall_seconds'] = time.monotonic()-started
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output/'evaluation.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    if result['status'] != 'descriptive_complete': raise SystemExit(1)


if __name__ == '__main__': main()

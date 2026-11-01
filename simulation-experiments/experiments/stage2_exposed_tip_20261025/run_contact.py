"""Reuse the signed-force B0 runner for one frozen exposed-tip G/D/R sequence."""
import argparse
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE),str(ROOT),str(ROOT/'experiments/stage2_contact_20261025')]
from experiments.stage2_contact_20261025 import run_contact as baseline
from experiments.stage2_contact_20261025 import geometry as stock
from model import Adapter

def main():
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False);parser.add_argument('--phase',choices=('G','D','R'),required=True)
    parser.add_argument('--geometry-audit',type=Path);parser.add_argument('--side-authorization',type=Path)
    parser.add_argument('--predecessor-D',dest='predecessor_D',type=Path)
    args,remaining=parser.parse_known_args();sys.argv=[sys.argv[0],*remaining]
    if args.phase=='R' and (args.predecessor_D is None or not json.loads(args.predecessor_D.read_text())['proceed_gate_passed']):raise RuntimeError('Reserved requires independent D PASS')
    adapter=Adapter(args.phase,args.geometry_audit,args.side_authorization)
    baseline.audit=adapter.audit
    def ownership(point,separation,finger,protocol,outward=None):
        result=stock.own_point(point,separation,finger,protocol,outward)
        head=[stock.distance_to_triangles(point,c['points_finger_m'],c['triangle_indices']) for c in finger['colliders'] if c.get('role')=='head']
        white=[stock.distance_to_triangles(point,c['points_finger_m'],c['triangle_indices']) for c in finger['colliders'] if c.get('role')=='white']
        result.update(distance_head_m=min(head),distance_white_m=min(white),compatible_roles=[role for role,distance in (('body',result['distance_pad_m']),('head',min(head)),('white',min(white))) if distance<=result['tolerance_m']])
        import numpy as np
        expected=np.array([0.,-1. if finger['body_path'].endswith('leftfinger') else 1.,0.])
        normal=np.asarray(outward,float) if outward is not None else np.zeros(3)
        length=np.linalg.norm(normal)
        valid=bool(np.isfinite(normal).all() and length>0)
        normal=normal/length if valid else None
        dot=float(np.dot(normal,expected)) if valid else None
        distance=abs(float(point[1])-finger['inner_plane_y_m'])
        flat=distance<=result['tolerance_m']
        lateral=bool(flat and valid and dot>=protocol['observation']['force_direction_cosine_min'])
        result.update(unique_body_geometry=result['unique_pad'],flat_face_distance_m=distance,
            flat_face_compatible=bool(flat),outward_normal_finger=normal.tolist() if valid else None,
            expected_grip_normal_finger=expected.tolist(),outward_dot_grip_normal=dot,
            lateral_qualified=lateral,unique_pad=bool(result['unique_pad'] and lateral))
        return result
    baseline.own_point=ownership
    baseline.main(adapter=adapter)

if __name__=='__main__':main()

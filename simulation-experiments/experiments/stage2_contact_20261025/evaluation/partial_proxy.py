"""Descriptive residuals from retained partial R3 cook; never a proceed audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Actual hull arrays require default Pueue')
    file=args.input/'proxy_geometry.json';artifact=json.loads(file.read_text());config=artifact['config']
    epsilon=config['fidelity']['membership_epsilon_m'];tips={}
    for label,tip in artifact.get('tips',{}).items():
        records=[];vertices=[]
        for index,hull in enumerate(tip.get('cooked_hulls',[])):
            v=np.asarray(hull['vertices_m'],float);p=np.asarray(hull['planes'],float)
            finite=bool(np.isfinite(v).all() and np.isfinite(p).all())
            row={'hull':index,'vertex_count':len(v),'plane_count':len(p),'polygon_count':len(hull['polygons']),'finite':finite}
            if not finite or not len(v) or not len(p) or p.ndim!=2 or p.shape[1]!=4:
                row['residual_status']='unavailable_invalid_arrays';records.append(row);continue
            lengths=np.linalg.norm(p[:,:3],axis=1)
            row['raw_plane_normal_length_min_max']=[float(lengths.min()),float(lengths.max())]
            if np.any(lengths==0):
                row['residual_status']='unavailable_zero_normal';records.append(row);continue
            normalized=p/lengths[:,None];residual=v@normalized[:,:3].T+normalized[:,3]
            worst=np.unravel_index(int(residual.argmax()),residual.shape);own=[];indices_valid=True
            for i,polygon in enumerate(hull['polygons']):
                if i>=len(normalized) or not polygon or min(polygon)<0 or max(polygon)>=len(v):indices_valid=False;continue
                own.append(float(abs(v[polygon]@normalized[i,:3]+normalized[i,3]).max()))
            row.update(residual_status='computed_descriptively',normalized_vertex_plane_min_m=float(residual.min()),
                normalized_vertex_plane_max_m=float(residual.max()),outside_vertex_plane_pairs_above_frozen_epsilon=int((residual>epsilon).sum()),
                vertices_outside_any_plane_above_epsilon=int((residual>epsilon).any(axis=1).sum()),
                worst_vertex_index=int(worst[0]),worst_plane_index=int(worst[1]),worst_vertex_m=v[worst[0]].tolist(),
                worst_normalized_plane=normalized[worst[1]].tolist(),polygon_indices_valid=indices_valid,
                maximum_own_polygon_absolute_plane_residual_m=max(own) if own else None)
            records.append(row);vertices.append(v)
        bounds=None
        if vertices:
            all_v=np.concatenate(vertices);reference=np.asarray(tip['stl_points_finger_m'],float)
            actual=np.array([all_v.min(axis=0),all_v.max(axis=0)]);expected=np.array([reference.min(axis=0),reference.max(axis=0)])
            bounds={'cooked_bounds_m':actual.tolist(),'exported_registered_STL_bounds_m':expected.tolist(),
                'difference_m':(actual-expected).tolist(),'maximum_absolute_difference_m':float(abs(actual-expected).max()),
                'frozen_bound_limit_m':config['fidelity']['maximum_outer_bound_error_m']}
        tips[label]={'cooking_result':tip.get('cooking_result'),'hull_count':len(tip.get('cooked_hulls',[])),'records':records,'bounds':bounds}
    result={'schema':'partial-R3-hull-residuals-v1','source_partial_sha256':sha(file),'frozen_membership_epsilon_m':epsilon,
        'available_tips':list(tips),'missing_tips':[x for x in ['left','right'] if x not in tips],'tips':tips,
        'proceed_gate_passed':False,'G_fidelity':'UNTESTED: no completed G capture or independent full fidelity audit',
        'D_contact':'NOT_RUN','R_reserved':'NOT_RUN','round3_status':'Closed; no retry, new cook, threshold change or retrospective promotion',
        'scope':'Retained raw arrays only. Normalize each plane by its existing normal length to express residuals in meters; no sign/frame fitting, recooking, geometry replacement or criterion relaxation.'}
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'proceed_gate_passed':False,'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')


if __name__=='__main__':main()

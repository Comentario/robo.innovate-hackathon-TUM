"""Queued independent stock-pad contact audit, no simulation or physics solve."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rotation(q):
    q = np.asarray(q,float)
    if not np.isfinite(q).all() or np.linalg.norm(q) == 0:
        raise ValueError('Invalid finger WXYZ orientation')
    w,x,y,z = q/np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
        [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
        [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def surface_distance(point, vertices, indices):
    """Exact triangle-surface distance, including triangle edges and vertices."""
    triangles = np.asarray(vertices,float)[np.asarray(indices,int).reshape(-1,3)]
    if not len(triangles):
        return float('inf')
    a,b,c = triangles[:,0],triangles[:,1],triangles[:,2]
    ab,ac = b-a,c-a
    n = np.cross(ab,ac); n2 = np.sum(n*n,axis=1)
    ap = np.asarray(point)-a
    heights = np.sum(ap*n,axis=1)
    projected = np.asarray(point)-n*(np.divide(heights,n2,out=np.zeros_like(heights),where=n2>1e-30))[:,None]
    v = projected-a
    d00,d01,d11 = np.sum(ab*ab,axis=1),np.sum(ab*ac,axis=1),np.sum(ac*ac,axis=1)
    d20,d21 = np.sum(v*ab,axis=1),np.sum(v*ac,axis=1)
    den = d00*d11-d01*d01
    u = np.divide(d11*d20-d01*d21,den,out=np.full(len(den),-np.inf),where=abs(den)>1e-30)
    w = np.divide(d00*d21-d01*d20,den,out=np.full(len(den),-np.inf),where=abs(den)>1e-30)
    inside = (u>=0)&(w>=0)&(u+w<=1)&(n2>1e-30)
    face = np.divide(abs(heights),np.sqrt(n2),out=np.full(len(n2),np.inf),where=inside)
    distances = [face]
    for start,end in [(a,b),(b,c),(c,a)]:
        edge = end-start; length = np.sum(edge*edge,axis=1)
        t = np.divide(np.sum((np.asarray(point)-start)*edge,axis=1),length,out=np.zeros_like(length),where=length>1e-30)
        nearest = start+np.clip(t,0,1)[:,None]*edge
        distances.append(np.linalg.norm(np.asarray(point)-nearest,axis=1))
    return float(np.min(np.concatenate(distances)))


def classify_point(point_world, separation, pose, colliders, protocol, hulls=None, outward_world=None, proxy_config=None, flat_face_y_m=None, expected_grip_normal_finger=None):
    point = rotation(pose[3:7]).T@(np.asarray(point_world)-np.asarray(pose[:3]))
    distances = [(c['role'],surface_distance(point,c['points_finger_m'],c['triangle_indices'])) for c in colliders if c['enabled']]
    pad = min((d for role,d in distances if role=='body'),default=float('inf'))
    white = min((d for role,d in distances if role=='white'),default=float('inf'))
    head = min((d for role,d in distances if role=='head'),default=float('inf'))
    tolerance = abs(float(separation))+protocol['geometry']['pad_distance_allowance_m']
    boundary=True
    if hulls is not None:
        from union_geometry import hull_triangles,boundary_contact
        pad=min(surface_distance(point,h['vertices_m'],hull_triangles(h)[0]) for h in hulls)
        boundary=boundary_contact(point,rotation(pose[3:7]).T@np.asarray(outward_world),hulls,tolerance,proxy_config)
    unique_body=bool(boundary and np.isfinite([pad,white,head]).all() and pad<=tolerance and min(white,head)>tolerance+protocol['geometry']['white_extra_clearance_m'])
    outward=rotation(pose[3:7]).T@np.asarray(outward_world,float) if outward_world is not None else np.zeros(3)
    length=np.linalg.norm(outward);normal=outward/length if np.isfinite(outward).all() and length>0 else None
    flat_distance=abs(point[1]-flat_face_y_m) if flat_face_y_m is not None else float('inf')
    dot=float(np.dot(normal,expected_grip_normal_finger)) if normal is not None and expected_grip_normal_finger is not None else None
    lateral=bool(flat_distance<=tolerance and dot is not None and dot>=protocol['geometry']['side_contact']['minimum_outward_dot_grip_normal'])
    return {'point_finger_m':point.tolist(),'pad_distance_m':pad if np.isfinite(pad) else None,'white_distance_m':white if np.isfinite(white) else None,'head_distance_m':head if np.isfinite(head) else None,'tolerance_m':tolerance,
        'unique_body_geometry':unique_body,'flat_face_distance_m':float(flat_distance) if np.isfinite(flat_distance) else None,'flat_face_compatible':bool(flat_distance<=tolerance),
        'outward_normal_finger':normal.tolist() if normal is not None else None,'expected_grip_normal_finger':expected_grip_normal_finger,'outward_dot_grip_normal':dot,'lateral_qualified':lateral,
        'compatible_roles':[role for role,d in [('body',pad),('white',white),('head',head)] if d<=tolerance],
        'external_union_boundary_crossing':boundary,
        'uniquely_pad_compatible':unique_body and lateral}


def close(a,b,absolute,relative):
    a,b = np.asarray(a,float),np.asarray(b,float)
    return bool(np.linalg.norm(a-b) <= max(absolute,relative*max(np.linalg.norm(a),np.linalg.norm(b))))


def angle_between(q0,q):
    q0,q=np.asarray(q0,float),np.asarray(q,float)
    if not np.isfinite([q0,q]).all() or np.linalg.norm(q0)*np.linalg.norm(q)==0:
        return float('inf')
    return float(2*np.arccos(np.clip(abs(np.dot(q0,q))/(np.linalg.norm(q0)*np.linalg.norm(q)),0,1)))


def filter_paths(view):
    paths = view['filter_paths']
    if len(paths)==1 and isinstance(paths[0],list):
        paths=paths[0]
    return paths


def pair_rows(data, index, capacity):
    counts,starts = data['normal_counts'].reshape(-1),data['normal_starts'].reshape(-1)
    active = np.asarray(data['normal_indices'],int)
    n,start = int(counts[index]),int(starts[index])
    if n<0 or n and (start<0 or start+n>capacity):
        raise ValueError('Invalid pair range')
    wanted=np.arange(start,start+n,dtype=int); positions=np.searchsorted(active,wanted)
    if n and (np.max(positions)>=len(active) or not np.array_equal(active[positions],wanted)):
        raise ValueError('Pair range not present in copied active data')
    return positions


def ranges_valid(data, capacity):
    all_indices=[]
    counts=data['normal_counts'].reshape(-1);starts=data['normal_starts'].reshape(-1)
    for count,start in zip(counts,starts):
        count,start=int(count),int(start)
        if count<0 or count and (start<0 or start+count>capacity):
            return False
        if count:all_indices.extend(range(start,start+count))
    return len(all_indices)<capacity and len(set(all_indices))==len(all_indices) and np.array_equal(sorted(all_indices),data['normal_indices'])


def run_lengths(values):
    count=0;maximum=0;first=None
    for step,value in values:
        count=count+1 if value else 0
        maximum=max(maximum,count)
        if count>=3 and first is None:first=step
    return maximum,first


def view_summary(data, paths, protocol, dt):
    rules=protocol['contact_reporting'];capacity=rules['capacity_per_view']
    finite=all(np.isfinite(data[key]).all() for key in data.keys())
    checks={'finite':finite,'normal_ranges_complete_unsaturated':ranges_valid(data,capacity)}
    normal_force=np.asarray(data['normal_forces_N'],float).reshape(-1)
    impulses=np.asarray(data['normal_impulses_Ns'],float).reshape(-1)
    normals=np.asarray(data['normal_vectors_world'],float)
    checks['normal_unit_vectors']=bool(np.all(abs(np.linalg.norm(normals,axis=1)-1)<=1e-3))
    checks['normal_dt_scaling']=close(impulses,normal_force*dt,rules['dt_scaling_absolute_tolerance_Ns'],rules['dt_scaling_relative_tolerance'])
    matrix=np.asarray(data['filtered_normal_impulse_matrix_world_Ns'],float).reshape(-1,3)/dt
    net=np.asarray(data['all_body_net_normal_impulse_world_Ns'],float).reshape(-1,3)[0]/dt
    checks['matrix_net_agreement']=close(matrix.sum(axis=0),net,rules['aggregate_absolute_tolerance_N'],rules['aggregate_relative_tolerance'])
    if len(matrix)!=len(paths) or data['normal_counts'].size!=len(paths):
        raise ValueError('Resolved filter order differs from contact matrix/ranges')
    pairs={}
    for i,path in enumerate(paths):
        index=pair_rows(data,i,capacity)
        vector=(normal_force[index,None]*normals[index]).sum(axis=0)
        signs=[sign for sign in [1,-1] if close(sign*vector,matrix[i],rules['aggregate_absolute_tolerance_N'],rules['aggregate_relative_tolerance'])]
        pairs[path]={'raw_signed_coefficient_sum_N':float(normal_force[index].sum()),
            'normal_magnitude_N':float(abs(normal_force[index]).sum()),
            'all_normal_magnitudes_N':float(abs(normal_force[index]).sum()),
            'matrix_force_N':matrix[i].tolist(),'point_sum_vector_N':vector.tolist(),
            'possible_signs':signs,'active_rows':index.tolist(),
            'force_carrying_rows':index[abs(normal_force[index])>protocol['force_response']['force_carrying_magnitude_floor_N']].tolist()}
    checks['all_pairs_point_matrix_agree']=all(pair['possible_signs'] for pair in pairs.values())
    friction_count=data['friction_counts'].reshape(-1);friction_start=data['friction_starts'].reshape(-1)
    friction_indices=[]
    for count,start in zip(friction_count,friction_start):
        count,start=int(count),int(start)
        if count<0 or count and (start<0 or start+count>capacity):
            checks['friction_ranges_complete_unsaturated']=False
            break
        if count:friction_indices.extend(range(start,start+count))
    else:
        checks['friction_ranges_complete_unsaturated']=len(friction_indices)<capacity and len(set(friction_indices))==len(friction_indices) and np.array_equal(sorted(friction_indices),data['friction_indices'])
    checks['friction_dt_scaling']=close(data['friction_impulses_world_Ns'],data['friction_forces_world_N']*dt,rules['dt_scaling_absolute_tolerance_Ns'],rules['dt_scaling_relative_tolerance'])
    return {'checks':checks,'pairs':pairs,'normal_point_count':len(normal_force),'friction_anchor_count':len(data['friction_indices'])}


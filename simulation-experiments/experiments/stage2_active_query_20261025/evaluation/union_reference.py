"""Bounded convex-union samples and membership, not a general CSG library."""
import hashlib
import json
import time

import numpy as np


def check_time(deadline):
    if time.monotonic()>deadline:
        raise TimeoutError('Frozen capture-plus-audit time budget exhausted')


def contains(points,hulls,epsilon):
    points=np.asarray(points,float).reshape(-1,3);inside=np.zeros(len(points),bool)
    for h in hulls:
        planes=np.asarray(h['planes'],float)
        for start in range(0,len(points),2048):
            p=points[start:start+2048]
            inside[start:start+len(p)]|=np.all(p@planes[:,:3].T+planes[:,3]<=epsilon,axis=1)
    return inside


def canonical_hash(hulls,config):
    q=config['canonical_hash'];items=[]
    for h in hulls:
        vertices=sorted(set(map(tuple,np.rint(np.asarray(h['vertices_m'])/q['vertex_quantum_m']).astype(np.int64))))
        planes=np.asarray(h['planes'],float);planes=planes/np.linalg.norm(planes[:,:3],axis=1)[:,None]
        planes=planes/np.array([q['unit_plane_normal_quantum']]*3+[q['plane_offset_quantum_m']])
        planes=sorted(set(map(tuple,np.rint(planes).astype(np.int64))))
        items.append({'vertices':[[int(v) for v in p] for p in vertices],'planes':[[int(v) for v in p] for p in planes]})
    items.sort(key=lambda x:json.dumps(x,sort_keys=True))
    return hashlib.sha256(json.dumps(items,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def hull_triangles(hull):
    indices=[];normals=[]
    for face,plane in zip(hull['polygons'],hull['planes']):
        for i in range(1,len(face)-1):
            indices.append([face[0],face[i],face[i+1]]);normals.append(plane[:3])
    return np.asarray(indices,int),np.asarray(normals,float)


def samples(vertices,triangles,spacing,cap,deadline,normals=None):
    points=[];directions=[];total=0
    for index,t in enumerate(np.asarray(vertices)[triangles]):
        check_time(deadline)
        n=max(1,int(np.ceil(max(np.linalg.norm(t[1]-t[0]),np.linalg.norm(t[2]-t[0]),np.linalg.norm(t[2]-t[1]))/spacing)))
        number=(n+1)*(n+2)//2;total+=number
        if total>cap:raise ValueError('Frozen surface candidate cap exceeded; no coarsening')
        for i in range(n+1):
            v=np.arange(n-i+1)/n
            cloud=t[0]+(i/n)*(t[1]-t[0])+v[:,None]*(t[2]-t[0])
            points.append(cloud)
            if normals is not None:directions.append(np.repeat(normals[index][None],len(cloud),axis=0))
    return np.concatenate(points),np.concatenate(directions) if normals is not None else None


def external_cloud(hulls,config,deadline):
    f=config['fidelity'];clouds=[];count=0
    for hull in hulls:
        tri,normals=hull_triangles(hull)
        cloud,normals=samples(hull['vertices_m'],tri,f['surface_sample_spacing_m'],f['maximum_hull_samples_per_tip']-count,deadline,normals)
        count+=len(cloud);offset=f['external_probe_offset_m']
        keep=~contains(cloud+offset*normals,hulls,f['membership_epsilon_m']) & contains(cloud-offset*normals,hulls,f['membership_epsilon_m'])
        clouds.append(cloud[keep]);check_time(deadline)
    exposed=np.concatenate(clouds)
    if not len(exposed):raise ValueError('No sampled external cooked-union boundary')
    return exposed,count


def boundary_contact(point,outward,hulls,tolerance,config):
    n=np.asarray(outward,float);length=np.linalg.norm(n)
    if not np.isfinite(n).all() or length==0:return False
    n/=length;f=config['fidelity'];distance=tolerance+f['contact_ray_extra_m']
    return bool(not contains([point+distance*n],hulls,f['membership_epsilon_m'])[0] and contains([point-distance*n],hulls,f['membership_epsilon_m'])[0])


def outside_winding(point,vertices,triangles):
    t=np.asarray(vertices)[triangles]-np.asarray(point)
    a,b,c=t[:,0],t[:,1],t[:,2];la,lb,lc=(np.linalg.norm(v,axis=1) for v in [a,b,c])
    determinant=np.sum(a*np.cross(b,c),axis=1)
    denominator=la*lb*lc+np.sum(a*b,axis=1)*lc+np.sum(b*c,axis=1)*la+np.sum(c*a,axis=1)*lb
    winding=float(np.sum(2*np.arctan2(determinant,denominator))/(4*np.pi))
    return abs(winding)<.1,winding

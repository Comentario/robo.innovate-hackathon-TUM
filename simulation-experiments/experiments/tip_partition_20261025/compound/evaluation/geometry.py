"""Small fixed-sample analytic-cell audit helpers; no CSG or proxy cooking."""
import time
import numpy as np


def deadline_check(deadline):
    if time.monotonic()>deadline:raise TimeoutError('Shared180second budget exhausted; no adaptation')


def contains(points,cells,epsilon,deadline):
    inside=np.zeros(len(points),bool)
    for c in cells:
        deadline_check(deadline);p=np.asarray(c['planes_mm']);v=np.asarray(c['vertices_mm'])
        active=~inside
        if epsilon==0:
            # Conservative pruning only; the actual membership test remains <=0.
            active&=np.all(points>=v.min(axis=0)-1e-5,axis=1)&np.all(points<=v.max(axis=0)+1e-5,axis=1)
        ids=np.flatnonzero(active)
        for begin in range(0,len(ids),2048):
            ii=ids[begin:begin+2048];inside[ii]|=np.all(points[ii]@p[:,:3].T+p[:,3]<=epsilon,axis=1)
    return inside


def triangle_distances(points,triangles,deadline):
    """Exact face/edge/vertex minimum;128points x512triangles scratch <128MiB."""
    result=np.full(len(points),np.inf)
    for begin in range(0,len(points),128):
        deadline_check(deadline);x=points[begin:begin+128];best=np.full(len(x),np.inf)
        for first in range(0,len(triangles),512):
            t=triangles[first:first+512];a,b,c=t[:,0],t[:,1],t[:,2];ab,ac=b-a,c-a
            n=np.cross(ab,ac);n2=np.sum(n*n,axis=1);r=x[:,None]-a
            signed=np.einsum('qti,ti->qt',r,n);d00=np.sum(ab*ab,axis=1);d01=np.sum(ab*ac,axis=1);d11=np.sum(ac*ac,axis=1)
            d20=np.einsum('qti,ti->qt',r,ab);d21=np.einsum('qti,ti->qt',r,ac);den=d00*d11-d01*d01
            u=np.divide(d11*d20-d01*d21,den,out=np.full_like(d20,-np.inf),where=abs(den)>1e-30)
            w=np.divide(d00*d21-d01*d20,den,out=np.full_like(d21,-np.inf),where=abs(den)>1e-30)
            distance=np.divide(signed*signed,n2,out=np.full_like(signed,np.inf),where=n2>1e-30)
            distance[(u<0)|(w<0)|(u+w>1)]=np.inf
            for start,end in [(a,b),(b,c),(c,a)]:
                edge=end-start;length=np.sum(edge*edge,axis=1);r=x[:,None]-start;dot=np.einsum('qti,ti->qt',r,edge)
                fraction=np.clip(np.divide(dot,length,out=np.zeros_like(dot),where=length>1e-30),0,1)
                distance=np.minimum(distance,np.sum(r*r,axis=2)-2*fraction*dot+fraction*fraction*length)
            best=np.minimum(best,np.min(distance,axis=1))
        result[begin:begin+len(x)]=np.sqrt(np.maximum(best,0))
    return result


def mesh_samples(vertices,faces,seed,count,cap,normal_floor):
    t=vertices[faces];cross=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);length=np.linalg.norm(cross,axis=1)
    volume=float(np.sum(t[:,0]*np.cross(t[:,1],t[:,2]))/6)
    if np.any(length<=normal_floor) or volume<=0:raise ValueError('Invalid/negative-winding mesh; no repair')
    face_normals=cross/length[:,None];vn=np.zeros_like(vertices)
    for k in range(3):np.add.at(vn,faces[:,k],cross)
    norms=np.linalg.norm(vn,axis=1)
    if np.any(norms<=normal_floor) or not np.isfinite(vn).all():raise ValueError('Undefined fixed vertex normal; STOP')
    vn/=norms[:,None]
    if count+len(vertices)+len(faces)>cap:raise ValueError('Fixed sample cap exceeded; no truncation')
    rng=np.random.Generator(np.random.PCG64(seed));chosen=rng.choice(len(faces),count,p=length/length.sum())
    uv=rng.random((count,2));s=np.sqrt(uv[:,0]);sample=(1-s[:,None])*t[chosen,0]+s[:,None]*(1-uv[:,1,None])*t[chosen,1]+s[:,None]*uv[:,1,None]*t[chosen,2]
    return np.vstack([sample,vertices,t.mean(axis=1)]),np.vstack([face_normals[chosen],vn,face_normals]),volume


def union_samples(cells,seed,count,cap,floor):
    vertices=[];faces=[];offset=0
    for c in cells:
        v=np.asarray(c['vertices_mm']);f=np.asarray(c['triangles'],int)
        vertices.append(v);faces.append(f+offset);offset+=len(v)
    # Separate indexed copies at touching cells preserve each fixed incident normal.
    return mesh_samples(np.concatenate(vertices),np.concatenate(faces),seed,count,cap,floor)


def outside_winding(points,triangles):
    values=[]
    for p in points:
        a,b,c=(triangles[:,i]-p for i in range(3));la,lb,lc=(np.linalg.norm(v,axis=1) for v in [a,b,c])
        numerator=np.sum(a*np.cross(b,c),axis=1)
        denominator=la*lb*lc+np.sum(a*b,axis=1)*lc+np.sum(b*c,axis=1)*la+np.sum(c*a,axis=1)*lb
        values.append(float(np.sum(2*np.arctan2(numerator,denominator))/(4*np.pi)))
    return np.asarray(values)

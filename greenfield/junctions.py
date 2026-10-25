"""Guided tangent transfer paths, sampled by arc length for motion and rendering."""
import math

def curve(a,b,reach=None,n=48):
    reach=reach or (b[0]-a[0])*.42
    p=[a,[a[0]+reach,a[1],a[2]],[b[0]-reach,b[1],b[2]],b];out=[]
    for k in range(n+1):
        t=k/n;v=1-t
        q=[v**3*p[0][j]+3*v*v*t*p[1][j]+3*v*t*t*p[2][j]+t**3*p[3][j] for j in range(3)]
        d=[3*v*v*(p[1][j]-p[0][j])+6*v*t*(p[2][j]-p[1][j])+3*t*t*(p[3][j]-p[2][j]) for j in range(3)]
        out.append(q+[-math.atan2(d[2],d[0])])
    return out

def length(path):return sum(math.dist(a[:3],b[:3]) for a,b in zip(path,path[1:]))

def at(path,u):
    if u<=0:return path[0][:]
    if u>=1:return path[-1][:]
    wanted=length(path)*u
    for a,b in zip(path,path[1:]):
        span=math.dist(a[:3],b[:3])
        if wanted<=span:
            f=wanted/span if span else 0
            return [x+(y-x)*f for x,y in zip(a,b)]
        wanted-=span
    return path[-1][:]

"""Semantic fingerprints for a stopped reference scene, independent of ROS message timestamps."""
from copy import deepcopy
import math
from integration.recovery import digest


def without_timestamps(value,in_header=False):
    if isinstance(value,dict):
        return {key:without_timestamps(item,key=='header') for key,item in value.items() if not (in_header and key=='stamp')}
    if isinstance(value,(list,tuple)):return [without_timestamps(v) for v in value]
    return value


def scene_digest(scene):
    return digest(without_timestamps(scene))


def require_same_scene(scene,expected):
    actual=scene_digest(scene)
    if actual!=expected:raise ValueError('robot joints, gripper or collision scene changed since reconciliation')
    return actual


def same_pose(a,b,position_tolerance=.003,angle_tolerance=.03):
    for value in (a,b):
        if len(value['position_m'])!=3 or len(value['orientation_xyzw'])!=4:return False
        if any(not math.isfinite(x) for x in value['position_m']+value['orientation_xyzw']):return False
        if not math.isclose(sum(x*x for x in value['orientation_xyzw']),1.,abs_tol=1e-5):return False
    if math.dist(a['position_m'],b['position_m'])>position_tolerance:return False
    dot=abs(sum(x*y for x,y in zip(a['orientation_xyzw'],b['orientation_xyzw'])))
    return 2*math.acos(min(1.,dot))<=angle_tolerance


def compose_poses(parent,child):
    """Compose world→object and object→primitive, including rotated local offsets."""
    for value in (parent,child):
        if not same_pose(value,value):raise ValueError('invalid pose in scene transform')
    x,y,z,w=parent['orientation_xyzw'];a,b,c,d=child['orientation_xyzw']
    vx,vy,vz=child['position_m']
    tx,ty,tz=2*(y*vz-z*vy),2*(z*vx-x*vz),2*(x*vy-y*vx)
    rotated=[vx+w*tx+y*tz-z*ty,vy+w*ty+z*tx-x*tz,vz+w*tz+x*ty-y*tx]
    return dict(position_m=[p+v for p,v in zip(parent['position_m'],rotated)],orientation_xyzw=[w*a+x*d+y*c-z*b,w*b-x*c+y*d+z*a,w*c+x*b-y*a+z*d,w*d-x*a-y*b-z*c])

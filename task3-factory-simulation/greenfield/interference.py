"""Continuous translating-AABB versus oriented-box SAT checks against exported static scene meshes.

Tests whole straight paths, independent of temporal sampling or speed profile.
Not a full-machine proof: moving obstacles, cables, contact and deforming loads
are outside this audit. Cylinder/sphere boxes can be conservative false positives.
"""
from collections import defaultdict
from itertools import product
import math

def sweep_hit(p,q,half,obstacle,tolerance=1e-4,moving_axes=None):
    broad_half=half if moving_axes is None else [sum(abs(moving_axes[k][a])*half[k] for k in range(3)) for a in range(3)]
    start,end=0.,1.
    for a in range(3):
        low=obstacle['min'][a]-broad_half[a]+tolerance;high=obstacle['max'][a]+broad_half[a]-tolerance;delta=q[a]-p[a]
        if abs(delta)<1e-10:
            if not low<p[a]<high:return None
        else:
            lo,hi=sorted(((low-p[a])/delta,(high-p[a])/delta));start=max(start,lo);end=min(end,hi)
            if start>=end:return None
    if moving_axes is None and all(max(abs(v) for v in axis)>1-1e-9 for axis in obstacle.get('axes',[[1,0,0],[0,1,0],[0,0,1]])):return start
    axes=obstacle.get('axes',[[1,0,0],[0,1,0],[0,0,1]])
    center=obstacle.get('center',[(lo+hi)/2 for lo,hi in zip(obstacle['min'],obstacle['max'])])
    extents=obstacle.get('half',[(hi-lo)/2 for lo,hi in zip(obstacle['min'],obstacle['max'])])
    world=moving_axes or [[1,0,0],[0,1,0],[0,0,1]]
    def dot(a,b):return sum(x*y for x,y in zip(a,b))
    tests=world+axes+[[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]] for u in world for v in axes]
    start,end=0.,1.
    for axis in tests:
        norm=math.sqrt(dot(axis,axis))
        if norm<1e-9:continue
        axis=[v/norm for v in axis]
        radius=sum(abs(dot(axis,world[a]))*half[a] for a in range(3))+sum(abs(dot(axis,axes[a]))*extents[a] for a in range(3))-tolerance
        origin=dot([p[a]-center[a] for a in range(3)],axis);delta=dot([q[a]-p[a] for a in range(3)],axis)
        if abs(delta)<1e-10:
            if abs(origin)>=radius:return None
        else:
            lo,hi=sorted(((-radius-origin)/delta,(radius-origin)/delta))
            start=max(start,lo);end=min(end,hi)
            if start>=end:return None
    return start


def audit_scene(report,scene,reserve_only=False):
    grid=defaultdict(list)
    def cells(lo,hi):
        return product(*(range(math.floor(lo[a]/.4),math.floor(hi[a]/.4)+1) for a in range(3)))
    for n,o in enumerate(scene):
        for key in cells(o['min'],o['max']):grid[key].append(n)
    hits=[];checks=strokes=0;counts=defaultdict(int);checked_loops=set();checked_paths=set()
    excluded_labels=('Contained collection; settling abstracted','Contained discard cart collection; settling abstracted','Contained disposal area unloading; settling abstracted')
    for identity,seq in report['mechanics']['tracks'].items():
        if identity.startswith('PICKER-'):
            specs=[('head',[0,-.01625,0],[.10,.06875,.068]),('ram',[0,1.25,0],[.025,1.25,.025])]
        elif identity.startswith('B'):specs=[('brick',[0,0,0],[.1225,.0345,.0335])]
        else:continue
        for stroke in seq:
            if reserve_only and not stroke['station'].endswith('_reserve'):continue
            if stroke['label'] in excluded_labels:continue
            strokes+=1
            if 'loop_s0' in stroke:
                cell=stroke['loop_cell']
                if cell in checked_loops:continue
                checked_loops.add(cell)
                from .flow import loop_pose
                geometry=report['mechanics']['loop_geometry'];perimeter=geometry['perimeter'];half=[.1225,.0345,.0335]
                for k in range(math.ceil(perimeter/.05)+1):
                    point,yaw=loop_pose(k*perimeter/math.ceil(perimeter/.05),report['mechanics']['cell_z'][cell],geometry['x1'])
                    co,si=math.cos(yaw),math.sin(yaw);axes=[[co,0,-si],[0,1,0],[si,0,co]]
                    candidates=set()
                    for key in cells([point[a]-(.13 if a!=1 else .0345) for a in range(3)],[point[a]+(.13 if a!=1 else .0345) for a in range(3)]):candidates.update(grid.get(key,()))
                    for n in candidates:
                        checks+=1
                        if sweep_hit(point,point,half,scene[n],moving_axes=axes) is not None:
                            counts['brick / Continuous common-drive mixing conveyor']+=1
                            if len(hits)<12:hits.append({'identity':identity,'part':'brick','label':stroke['label'],'loop_cell':cell,'distance_m':k*perimeter/math.ceil(perimeter/.05),'obstacle':scene[n]})
                continue
            if 'path' in stroke:
                signature=tuple(tuple(p) for p in stroke['path'])
                if signature in checked_paths:continue
                checked_paths.add(signature)
                from .junctions import at
                half=[.1225,.0345,.0335]
                for k in range(65):
                    pose=at(stroke['path'],k/64);point=pose[:3];co,si=math.cos(pose[3]),math.sin(pose[3]);axes=[[co,0,-si],[0,1,0],[si,0,co]]
                    candidates=set()
                    for key in cells([point[a]-(.13 if a!=1 else .0345) for a in range(3)],[point[a]+(.13 if a!=1 else .0345) for a in range(3)]):candidates.update(grid.get(key,()))
                    for n in candidates:
                        checks+=1
                        if sweep_hit(point,point,half,scene[n],moving_axes=axes) is not None:
                            counts['brick / '+stroke['label']]+=1
                            if len(hits)<12:hits.append({'identity':identity,'label':stroke['label'],'path_fraction':k/64,'obstacle':scene[n]})
                continue
            for part,offset,half in specs:
                p=[stroke['from'][a]+offset[a] for a in range(3)];q=[stroke['to'][a]+offset[a] for a in range(3)]
                tilt=None;broad_half=half
                if stroke['label']=='Powered downward diagonal reject transfer':
                    angle=math.atan2(p[1]-q[1],p[0]-q[0]);co,si=math.cos(angle),math.sin(angle)
                    tilt=[[co,si,0],[-si,co,0],[0,0,1]]
                    broad_half=[sum(abs(tilt[k][a])*half[k] for k in range(3)) for a in range(3)]
                if 'pitch_from' in stroke:
                    broad_half=[.13,.09,.034]
                candidates=set()
                for key in cells([min(p[a],q[a])-broad_half[a] for a in range(3)],[max(p[a],q[a])+broad_half[a] for a in range(3)]):candidates.update(grid.get(key,()))
                for n in candidates:
                    # Nose rotation/contact is a separate approximation, not a translating-box proof.
                    if scene[n].get('support_contact') and stroke['station'].endswith('_decline'):continue
                    checks+=1
                    if 'pitch_from' in stroke:
                        u=None
                        for sample in range(33):
                            f=sample/32;phi=stroke['pitch_from']+(stroke['pitch_to']-stroke['pitch_from'])*f;co,si=math.cos(phi),math.sin(phi)
                            point=[p[a]+(q[a]-p[a])*f for a in range(3)]
                            if sweep_hit(point,point,half,scene[n],moving_axes=[[co,si,0],[-si,co,0],[0,0,1]]) is not None:u=f;break
                    else:u=sweep_hit(p,q,half,scene[n],moving_axes=tilt)
                    if u is not None:
                        counts[part+' / '+stroke['label']]+=1
                        if sum(x['label']==stroke['label'] for x in hits)<2:hits.append({'identity':identity,'part':part,'label':stroke['label'],'stroke_start':stroke['t0'],'path_fraction':u,'obstacle':scene[n]})
    return {'passed':not counts,'loop_paths_sampled':len(checked_loops),'scene_boxes':len(scene),'pair_checks':checks,'strokes':strokes,'intersections':sum(counts.values()),'counts':dict(counts),'examples':hits,'scope':'Continuous straight-path SAT tests (material AABB / static oriented bounds) against exported static meshes. Moving obstacles, inter-object dynamic collisions, cables and contact are not certified. Enclosed-bin settling excluded. Decline belt support contact and nose pitch transitions are not contact-certified; other static obstacles remain checked, with an oriented brick on the straight slope. Varying-pitch nose paths use 33 oriented-box samples per short segment, not a continuous rotating-body proof. Guided transfer curves use 65 arc-length samples with tangent-oriented bricks. Shared-drive loop paths are checked once per cell at <=50 mm intervals with oriented bricks; identical encoder paths are reused for every loop occupant. This is a sampled curve audit, not a continuous curve proof. Faces touching within 0.1 mm are allowed.'}

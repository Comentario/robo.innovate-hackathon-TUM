"""Exact swept-AABB test of axis-aligned payloads against fixed equipment solids.

No rigid-body dynamics. Touching support surfaces is allowed. This audits fixed
posts, beams, cameras and light panels; it is not a full tool/cable collision check.
"""

def structure_boxes():
    solids=[]
    def add(name,x,y,z,sx,sy,sz):solids.append({'name':name,'center':[x,y,z],'size':[sx,sy,sz]})
    for name,xmin,xmax,zmin,zmax,top in [
        ('dehacker',-.6,2.3,-1.6,1.6,3.),('separator',8.4,12.4,-3.5,3.5,3.),
        ('correction',12.8,15.8,-6.5,6.5,3.6),('pairer',16.,20.,-3.5,3.5,3.),
        ('stacker',22.,25.5,-1.6,1.6,3.)]:
        for x in (xmin,xmax):
            for z in (zmin,zmax):add(name+' post',x,top/2,z,.12,top,.12)
        for z in (zmin,zmax):add(name+' rail',(xmin+xmax)/2,top,z,xmax-xmin+.2,.15,.13)
    for lane,z in enumerate((-2,2)):
        for zz in (z-1.35,z+1.35):add(f'camera {lane+1} post',13,1.45,zz,.065,1.2,.065)
        add(f'camera {lane+1} bridge',13,2.05,z,.08,.07,2.75)
        add(f'camera {lane+1} body',13,1.96,z,.16,.12,.2)
        add(f'camera {lane+1} light',13,1.9,z,.5,.03,1.7)
    return solids


def segment_hits(p,q,box,half,epsilon=1e-5):
    low=0.;high=1.
    for axis in range(3):
        radius=box['size'][axis]/2+half[axis]-epsilon
        lo=box['center'][axis]-radius;hi=box['center'][axis]+radius
        delta=q[axis]-p[axis]
        if abs(delta)<1e-12:
            if p[axis]<=lo or p[axis]>=hi:return False
        else:
            a=(lo-p[axis])/delta;b=(hi-p[axis])/delta
            low=max(low,min(a,b));high=min(high,max(a,b))
            if low>=high:return False
    return high>max(0,low) and low<1


def audit_clearances(m):
    w,h,d=m['brick_dimensions_m'];solids=structure_boxes();hits=[];segments=0
    for identity,seq in m['tracks'].items():
        for motion in seq:
            for p,q in zip(motion['points'],motion['points'][1:]):
                segments+=1
                for box in solids:
                    # Cheap Y rejection removes overhead beams from belt motion checks.
                    if min(p[2],q[2])-h/2>=box['center'][1]+box['size'][1]/2:continue
                    if max(p[2],q[2])+h/2<=box['center'][1]-box['size'][1]/2:continue
                    if segment_hits(p[1:],q[1:],box,[d/2,h/2,w/2]):
                        hits.append({'brick':identity,'station':motion['station'],'solid':box['name'],
                                     't0':motion['t0'],'kind':motion['kind']})
                        if len(hits)>=30:break
                if len(hits)>=30:break
            if len(hits)>=30:break
        if len(hits)>=30:break
    return {'scope':'Swept axis-aligned BRICK bounds versus fixed posts/rails/cameras/lights. Excludes tools, cables, brick-brick and dynamics.',
            'tested_segments':segments,'fixed_solids':len(solids),'collisions':hits,'passed':not hits}

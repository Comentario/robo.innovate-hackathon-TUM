"""Fixed exposed-body/head references; no native calls or hidden-bore gate."""
import math
import struct
import numpy as np
from scipy.spatial import ConvexHull
from query_reference import ray_reference,transform,direction


def source_body(path,cfg,label):
    raw=path.read_bytes();n=struct.unpack_from('<I',raw,80)[0]
    if len(raw)!=84+50*n:raise ValueError('Unexpected STL encoding')
    f=np.asarray([list(struct.iter_unpack('<fff',raw[84+50*i+12:84+50*i+48])) for i in range(n)])
    cut=cfg['body_min_cad_x_mm'];eps=cfg['source_cut_epsilon_mm'];selected=f[np.all(f[:,:,0]>=cut-eps,axis=1)]
    v=np.unique(f.reshape(-1,3),axis=0);v=v[v[:,0]>=cut-eps];h=ConvexHull(v);v=v[h.vertices];h=ConvexHull(v)
    faces=h.simplices.copy()
    for i,(face,plane) in enumerate(zip(faces,h.equations)):
        t=v[face]
        if np.dot(np.cross(t[1]-t[0],t[2]-t[0]),plane[:3])<0:faces[i]=face[::-1]
    s=cfg['scene_fingertip_spec'];sign=1 if label=='left' else -1;R=np.array([[0,-sign,0],[-sign,0,0],[0,0,-1.]])
    offset=np.array([sign*s['width_center_cad_y_mm']*.001,sign*(s['stock_pad_backplane_abs_finger_y_m']+cut*.001),s['stock_pad_proximal_finger_z_m']+s['broad_end_cad_z_mm']*.001])
    return v*.001@R.T+offset,faces,selected*.001@R.T+offset,selected,v,R,offset


def mesh_hit(o,d,L,triangles,protocol):
    v=triangles.reshape(-1,3);f=np.arange(len(v)).reshape(-1,3);r=ray_reference(o,d,L,v,f,protocol)
    if r['hit']:
        t=triangles[r['triangle']];p=o+d*r['distance_m'];dist=[]
        for a,b in zip(t,np.roll(t,-1,axis=0)):
            e=b-a;u=np.clip(np.dot(p-a,e)/np.dot(e,e),0,1);dist.append(np.linalg.norm(p-a-u*e))
        r['edge_clearance_m']=float(min(dist));r['clear']=bool(min(dist)>=protocol['model_config']['query']['edge_clearance_m'] and abs(np.dot(r['normal_finger'],d))>=protocol['model_config']['query']['grazing_abs_dot_min'])
    return r


def cylinder_hit(o,d,L,head):
    p=np.asarray(o)-head['center_finger_m'];r=head['radius_m'];half=head['height_m']/2;hits=[]
    a=d[0]**2+d[2]**2;b=2*(p[0]*d[0]+p[2]*d[2]);c=p[0]**2+p[2]**2-r*r
    if a>1e-24 and b*b-4*a*c>=0:
        root=math.sqrt(b*b-4*a*c)
        for t in [(-b-root)/(2*a),(-b+root)/(2*a)]:
            if 0<=t<=L and abs(p[1]+t*d[1])<=half+1e-12:hits.append(t)
    if abs(d[1])>1e-12:
        for y in [-half,half]:
            t=(y-p[1])/d[1];q=p+t*d
            if 0<=t<=L and q[0]**2+q[2]**2<=r*r+1e-18:hits.append(t)
    return {'hit':bool(hits),'distance_m':float(min(hits)) if hits else None,'clear':True}


def specifications(v,head,cfg,label,world_finger,world_hand):
    lo,hi=v.min(axis=0),v.max(axis=0);pad=cfg['query']['ray_padding_m'];sign=1 if label=='left' else -1;out=[]
    for ix,x in enumerate(cfg['query']['grid_hand_x_offsets_m']):
        xlocal=transform(transform([x,0,0],world_hand),np.linalg.inv(world_finger))[0]
        for iz,z in enumerate(np.linspace(lo[2]+.001,hi[2]-.001,9)):
            out.append((f'{label}_grid_{ix}_{iz}',[xlocal,lo[1]-pad if sign==1 else hi[1]+pad,z],[0,sign,0],hi[1]-lo[1]+2*pad,'contact_grid','body'))
    for axis in range(3):
        for direct in [-1,1]:
            o=(lo+hi)/2;o[axis]=lo[axis]-pad if direct==1 else hi[axis]+pad;d=np.zeros(3);d[axis]=direct
            out.append((f'{label}_bbox_{axis}_{direct}',o,d,hi[axis]-lo[axis]+2*pad,'bounds_axis','body'))
    for iz,z in enumerate(cfg['query']['distal_z_m']):
        for direct in [-1,1]:out.append((f'{label}_distal_{iz}_{direct}',[0,lo[1]-pad if direct==1 else hi[1]+pad,z],[0,direct,0],hi[1]-lo[1]+2*pad,'distal_taper','body'))
    center=np.asarray(head['center_finger_m']);r=head['radius_m'];height=head['height_m']
    for axis,direct in [(0,-1),(0,1),(1,-1),(1,1)]:
        extent=r if axis==0 else height/2;o=center.copy();o[axis]-=direct*(extent+pad);d=np.zeros(3);d[axis]=direct
        out.append((f'{label}_head_{axis}_{direct}',o,d,2*(extent+pad),'head_hit','head'))
    for direct in [-1,1]:out.append((f'{label}_head_miss_{direct}',center+[0,-direct*(height/2+pad),r+.001],[0,direct,0],height+2*pad,'head_miss','head'))
    return out


def check_rays(stl,geometry,report,queries,cfg,protocol):
    byid={q['id']:q for q in queries};checks={};quality={};details={};expected=set()
    for label,tip in geometry['tips'].items():
        v,f,source,source_cad,body_cad,R,offset=source_body(stl,cfg,label);parts=tip['parts'];frame=np.asarray(report['frames'][label]['world_from_finger']);hand=np.asarray(report['world_from_hand']);records=[]
        checks[label+'_body_source_transform']=bool(np.allclose(sorted(map(tuple,parts['body']['vertices_finger_m'])),sorted(map(tuple,v)),atol=1e-9,rtol=0))
        for identity,o,d,L,group,kind in specifications(v,tip['head'],cfg,label,frame,hand):
            expected.add(identity);q=byid[identity];o=np.asarray(o);d=np.asarray(d)
            checks[identity+'_probe']=bool(q['group']==group and np.linalg.norm(np.asarray(q['origin_finger_m'])-o)<=2e-6 and np.linalg.norm(np.asarray(q['origin_world_m'])-transform(o,frame))<=2e-6 and np.linalg.norm(np.asarray(q['direction_world'])-direction(d,frame))<=1e-6 and abs(q['length_m']-L)<=2e-6)
            ref=mesh_hit(o,d,L,v[f],protocol) if kind=='body' else cylinder_hit(o,d,L,tip['head'])
            target=parts[kind]['path'];hits=[(i,h) for i,h in enumerate(q['hits']) if h['collision']==target];nearest=min(hits,key=lambda x:x[1]['distance_m']) if hits else None
            valid=True
            for h in q['hits']:
                p=np.asarray(h['position_world_m']);n=np.asarray(h['normal_world']);distance=h['distance_m']
                valid=valid and np.isfinite([*p,*n,distance]).all() and 0<=distance<=L+1e-5 and np.linalg.norm(p-(np.asarray(q['origin_world_m'])+distance*np.asarray(q['direction_world'])))<=1e-5 and abs(np.linalg.norm(n)-1)<=.001
            checks[identity+'_hit_data']=bool(valid and all(h['rigid_body']=='/World/envs/env_0/Robot/fr3_'+label+'finger' for _,h in hits))
            error=nearest[1]['distance_m']-ref['distance_m'] if nearest and ref['hit'] else None;parity=bool(nearest)==ref['hit'];original=None;eligible=False
            if kind=='body':
                original=mesh_hit(o,d,L,source,protocol)
                if original['hit']:
                    tri=source_cad[original['triangle']];normal=np.cross(tri[1]-tri[0],tri[2]-tri[0]);normal/=np.linalg.norm(normal);support=float(np.max((body_cad-tri[0])@normal))*.001
                    backing=normal[0]<-protocol['source_backing_axis_cosine'] and np.max(abs(tri[:,0]-cfg['body_min_cad_x_mm']))<=cfg['source_cut_epsilon_mm']
                    eligible=bool(support<=protocol['source_exterior_support_allowance_m'] and not backing);original.update(exposed_eligible=eligible,support_residual_m=support,buried_backing=bool(backing))
            original_error=nearest[1]['distance_m']-original['distance_m'] if nearest and original and original['hit'] else None
            records.append({'id':identity,'group':group,'role':kind,'reference':ref,'source_exterior_reference':original,'hit_parity':parity,'actual_firsthit_error_m':error,'source_exterior_error_m':original_error,'nearest_target':{'raw_index':nearest[0],**nearest[1]} if nearest else None,'all_raw_hit_paths':[h['collision'] for h in q['hits']]})
        quality[label+'_all106parities']=len(records)==106 and all(r['hit_parity'] for r in records)
        clear=[r for r in records if r['reference']['hit'] and r['reference'].get('clear')]
        quality[label+'_design_clear_100um']=bool(clear and all(r['actual_firsthit_error_m'] is not None and abs(r['actual_firsthit_error_m'])<=.0001 for r in clear))
        exposed=[r for r in records if r['source_exterior_reference'] and r['source_exterior_reference'].get('exposed_eligible') and r['source_exterior_reference'].get('clear')]
        quality[label+'_source_exposed_clear_100um']=bool(exposed and all(r['source_exterior_error_m'] is not None and abs(r['source_exterior_error_m'])<=.0001 for r in exposed))
        quality[label+'_clear_grip_and_outward_taper']=any(r['group']=='contact_grid' and np.dot(r['source_exterior_reference']['normal_finger'],[0,-1 if label=='left' else 1,0])>.9 for r in exposed) and any(r['group']=='distal_taper' and abs(r['source_exterior_reference']['normal_finger'][2])>.1 and r['source_exterior_reference']['normal_finger'][1]*(1 if label=='left' else -1)>.1 and np.dot(r['source_exterior_reference']['normal_finger'],byid[r['id']]['direction_finger'])<0 for r in exposed)
        details[label]=records
    checks['exact_tip_probe_ids']=set(byid)-{'control_hit','control_miss','control_inside','control_outside'}==expected
    return checks,quality,details

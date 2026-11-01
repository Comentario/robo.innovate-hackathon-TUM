"""One saved-mesh seat inspection; candidate circles are not physical-fit proof."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import time

NATIVE_SHA='0bafcf1d6c335094c5cf745e5eeaeb155681b333715e1a5ef6fc78bb9b0504eb'
FEATURE_SHA='832c8397779b1261582ab681947fa32d3db17989f4173469a10fa426d5935b17'
RULES={'maximum_seconds':10,'axis_normal_cross_component_limit':1e-4,'face_Y_span_m':1e-6,
    'plane_Y_group_quantum_m':1e-6,'circle_min_vertices':8,'circle_radius_range_m':[.0005,.01],
    'circle_max_radial_residual_m':.0001,'circle_max_angle_gap_rad':math.pi/3}


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def circle(points):
    import numpy as np
    p=np.asarray(points,float);a=np.c_[2*p,np.ones(len(p))]
    fit,_,rank,_=np.linalg.lstsq(a,np.sum(p*p,axis=1),rcond=None)
    if rank!=3:return {'status':'rank_deficient'}
    center=fit[:2];r2=fit[2]+center@center
    if r2<=0:return {'status':'invalid_radius'}
    radius=math.sqrt(r2);res=np.linalg.norm(p-center,axis=1)-radius
    angles=np.sort(np.arctan2(p[:,1]-center[1],p[:,0]-center[0]));gap=np.diff(np.r_[angles,angles[0]+2*math.pi]).max()
    return {'status':'fit_computed','center':center.tolist(),'radius':radius,'max_radial_residual':float(abs(res).max()),
        'rms_radial_residual':float(np.sqrt(np.mean(res*res))),'maximum_angle_gap_rad':float(gap)}


def boundary_loops(faces):
    counts=Counter(tuple(sorted((int(a),int(b)))) for tri in faces for a,b in zip(tri,[tri[1],tri[2],tri[0]]))
    edges=[(int(a),int(b)) for tri in faces for a,b in zip(tri,[tri[1],tri[2],tri[0]]) if counts[tuple(sorted((int(a),int(b))))]==1]
    adj=defaultdict(set)
    for a,b in edges:adj[a].add(b);adj[b].add(a)
    if any(n>2 for n in counts.values()) or not adj or any(len(v)!=2 for v in adj.values()):
        return [],{'status':'open_branched_or_nonmanifold','edge_multiplicity':dict(Counter(counts.values()))}
    remaining=set(adj);loops=[];directed=set(edges)
    while remaining:
        start=min(remaining);order=[start];previous=None;node=start
        while True:
            nxt=min(adj[node]-({previous} if previous is not None else set()))
            if nxt==start:break
            if nxt in order:return [],{'status':'invalid_cycle'}
            order.append(nxt);previous,node=node,nxt
        remaining-=set(order)
        if (order[0],order[1]) not in directed:order=order[::-1]
        loops.append(order)
    return loops,{'status':'closed_unbranched','loops':len(loops),'connectivity':'Exact equal coordinates only; no welding tolerance or repair'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['native-audit','features','output']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    started=time.monotonic();result={'schema':'saved-native-seat-inspection-v1','physical_fit_verified':False,'rules':RULES}
    def stop(*_):raise TimeoutError('Fixed10second seat inspection exhausted; no adaptation')
    signal.signal(signal.SIGALRM,stop);signal.setitimer(signal.ITIMER_REAL,10)
    try:
        import numpy as np
        if sha(args.native_audit)!=NATIVE_SHA or sha(args.features)!=FEATURE_SHA:raise ValueError('Frozen source provenance mismatch')
        records=json.loads(args.native_audit.read_text());features=json.loads(args.features.read_text())
        section=next(s for s in features['sections'] if s['x_mm']==-10.5)
        loops=section['graph']['components']
        if len(loops)!=2 or not all(c['closed_unbranched_unique_edges'] for c in loops):raise ValueError('CAD boss section ambiguous')
        outer=max(loops,key=lambda c:c['absolute_area_mm2']);cadfit=circle(outer['quantized_loop_yz_mm'])
        result['CAD_boss_axis']={'source_x_section_mm':-10.5,'center_yz_mm':cadfit.get('center'),'circle_fit_mm':cadfit,
            'source_section_face_ids':section['source_face_ids'],'feature_sha256':FEATURE_SHA,'section_coordinate_quantum_mm':1e-5,
            'body_mount_plane_cluster':316,'body_mount_plane':features['plane_clusters'][316]}
        result['fingers']={}
        for record in records:
            name=record['finger'];raw=np.asarray(record['points_finger_m'],float)
            if len(record['face_counts'])!=624 or any(c!=3 for c in record['face_counts']):raise ValueError('Expected native624triangle combined visual')
            v,inverse=np.unique(raw,axis=0,return_inverse=True);f=inverse[np.asarray(record['face_indices'],int).reshape(-1,3)]
            white=next(s['face_indices'] for s in record['material_subsets'] if s['path'].endswith('/material_0'))
            if len(white)!=362:raise ValueError('White support subset changed')
            groups=defaultdict(list)
            for identity in white:
                t=v[f[identity]];normal=np.cross(t[1]-t[0],t[2]-t[0]);length=np.linalg.norm(normal)
                if length==0:continue
                normal/=length
                if max(abs(normal[0]),abs(normal[2]))<=RULES['axis_normal_cross_component_limit'] and np.ptp(t[:,1])<=RULES['face_Y_span_m']:
                    groups[(1 if normal[1]>0 else -1,int(round(t[:,1].mean()/RULES['plane_Y_group_quantum_m'])))].append(identity)
            patches=[];candidates=[]
            for patchid,((sign,_),ids) in enumerate(sorted(groups.items())):
                orders,connectivity=boundary_loops(f[ids]);plane=float(np.mean(v[np.unique(f[ids]),1]));entry={'id':patchid,'normal_Y_sign':sign,'plane_Y_m':plane,'source_face_ids':ids,'connectivity':connectivity,'loops':[]}
                for loopid,order in enumerate(orders):
                    points=v[order];fit=circle(points[:,[0,2]]);projected=points[:,[0,2]];area=float(np.sum(projected[:,0]*np.roll(projected[:,1],-1)-projected[:,1]*np.roll(projected[:,0],-1))/2)
                    ok=fit['status']=='fit_computed' and len(order)>=8 and .0005<=fit['radius']<=.01 and fit['max_radial_residual']<=.0001 and fit['maximum_angle_gap_rad']<=math.pi/3
                    row={'id':loopid,'points_finger_m':points.tolist(),'exact_weld_vertex_ids':order,'original_point_ids_per_vertex':[np.flatnonzero(inverse==i).tolist() for i in order],
                        'planarity_Y_max_residual_m':float(abs(points[:,1]-plane).max()),'circle_fit_XZ_m':fit,'circle_candidate':bool(ok),'boundary_role_by_winding':'hole' if area*sign>0 else 'outer','signed_projected_area_m2':area}
                    entry['loops'].append(row)
                    if ok:candidates.append({'patch_id':patchid,'loop_id':loopid,'center_finger_m':[fit['center'][0],plane,fit['center'][1]],'radius_m':fit['radius'],'max_radial_residual_m':fit['max_radial_residual'],'boundary_role_by_winding':row['boundary_role_by_winding']})
                patches.append(entry)
            result['fingers'][name]={'source_path':record['path'],'patches':patches,'circular_candidates':candidates,'status':'unique_circle_candidate_not_physical_fit' if len(candidates)==1 else 'ambiguous_multiple_circles' if candidates else 'no_identifiable_circle_approximate_registration_required'}
        result.update(status='inspection_complete',native_audit_sha256=NATIVE_SHA,scope='Nativevisual topology only; no collider, source point, robot/layout/camera or historical experiment changes. Recess identity/seating is not certified by circle fit; ambiguity remains explicit.')
    except Exception as error:result.update(status='STOP',error=repr(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);result['wall_seconds']=time.monotonic()-started;args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'seat_inspection.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if result['status']!='inspection_complete':raise SystemExit(1)


if __name__=='__main__':main()

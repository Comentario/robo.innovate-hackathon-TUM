"""One independent offline48-cell audit; no cooking/contact or adaptive model."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import struct
import time

PROCESS_STARTED=time.monotonic()
import numpy as np
from scipy.spatial import ConvexHull
from geometry import contains,triangle_distances,mesh_samples,union_samples,outside_winding,deadline_check

HERE=Path(__file__).resolve().parent


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def normalized(p):
    p=np.asarray(p,float);length=np.linalg.norm(p[:,:-1],axis=1)
    if np.any(length==0) or not np.isfinite(p).all():raise ValueError('Invalid plane')
    return p/length[:,None]


def plane_sets_equal(a,b,tolerance):
    a,b=normalized(a),normalized(b)
    return bool(np.all(np.min(np.max(abs(a[:,None]-b[None]),axis=2),axis=1)<=tolerance) and np.all(np.min(np.max(abs(b[:,None]-a[None]),axis=2),axis=1)<=tolerance))


def topology(faces):
    e=np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]);c=Counter(map(tuple,np.sort(e,axis=1)));d=Counter(map(tuple,e))
    return all(n==2 for n in c.values()) and all(n==d[(b,a)] for (a,b),n in d.items())


def loops(faces):
    e=np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]);counts=Counter(map(tuple,np.sort(e,axis=1)));adj=defaultdict(set)
    for (a,b),n in counts.items():
        if n==1:adj[a].add(b);adj[b].add(a)
    if not adj or any(len(v)!=2 for v in adj.values()):raise ValueError('Source patch loop ambiguous')
    pending=set(adj);result=[]
    while pending:
        start=min(pending);order=[start];previous=None;node=start
        while True:
            following=min(adj[node]-({previous} if previous is not None else set()))
            if following==start:break
            if following in order:raise ValueError('Invalid source loop')
            order.append(following);previous,node=node,following
        pending-=set(order);result.append(order)
    return result


def polygon_area_centroid(p):
    q=np.roll(p,-1,axis=0);w=p[:,0]*q[:,1]-q[:,0]*p[:,1];s=w.sum()
    return abs(s)/2,np.sum((p+q)*w[:,None],axis=0)/(3*s)


def manifest_checks(candidate,v,faces,feature,cfg,rules):
    cells=candidate['cells'];p=candidate['provenance'];tol=rules['plane_comparison_tolerance'];margin=cfg['numerical_margin_mm'];checks={}
    ids={name:feature['plane_clusters'][index]['face_ids'] for name,index in cfg['source_feature_clusters'].items()}
    checks['source_face_provenance']=p['source_face_ids']==ids
    cuts={k:float(np.median(v[np.unique(faces[f])][:,0])) for k,f in ids.items()}
    checks['source_cuts']=all(abs(p['cuts_x_mm'][k]-x)<=margin and np.max(abs(v[np.unique(faces[ids[k]])][:,0]-x))<=margin for k,x in cuts.items())
    cap=loops(faces[ids['blind_bore_cap']]);boss=loops(faces[ids['boss_front_annulus']])
    if len(cap)!=1 or len(boss)!=2:raise ValueError('Unexpected source feature loops')
    inner=v[cap[0],1:];boss.sort(key=lambda f:polygon_area_centroid(v[f,1:])[0],reverse=True);outer=v[boss[0],1:];_,center=polygon_area_centroid(inner)
    checks['original_loop_vertices']=np.allclose(sorted(map(tuple,p['inner_source_loop_yz_mm'])),sorted(map(tuple,inner)),atol=tol,rtol=0) and np.allclose(sorted(map(tuple,p['source_outer_boss_loop_yz_mm'])),sorted(map(tuple,outer)),atol=tol,rtol=0)
    theta=cfg['fixed_normal_phase_rad']+np.arange(16)*2*np.pi/16;n=np.c_[np.cos(theta),np.sin(theta)]
    ip=np.c_[n,-np.max(n@inner.T,axis=1)-margin]
    iv=np.asarray([np.linalg.solve(n[[i,(i+1)%16]],-ip[[i,(i+1)%16],2]) for i in range(16)])
    source_outer=ConvexHull(outer).equations;radius=float(np.min(-(source_outer[:,:2]@center+source_outer[:,2]))-margin)
    radial=iv-center;bv=center+radius*radial/np.linalg.norm(radial,axis=1)[:,None];bp=ConvexHull(bv).equations
    body_ids=np.flatnonzero(v[:,0]>=cuts['body_front']-margin);body=ConvexHull(v[body_ids]).equations
    checks['derived_hole_and_boss']=np.allclose(p['source_hole_centroid_yz_mm'],center,atol=tol,rtol=0) and plane_sets_equal(p['inner16_planes_yz_mm'],ip,tol) and np.allclose(p['inner16_vertices_yz_mm'],iv,atol=tol,rtol=0) and abs(p['safe_boss_radius_mm']-radius)<=tol and np.allclose(p['boss16_vertices_yz_mm'],bv,atol=tol,rtol=0) and plane_sets_equal(p['boss16_planes_yz_mm'],bp,tol)
    checks['body_source_hull']=p['body_source_vertex_indices']==body_ids.tolist() and plane_sets_equal(p['body_planes_mm'],body,tol)
    regions=[('boss_annular',cuts['boss_front_annulus'],cuts['body_front']),('front_body_bored',cuts['body_front'],cuts['blind_bore_cap']),('rear_body_solid',cuts['blind_bore_cap'],cuts['rear_plane'])]
    expected={(name,i) for name,_,_ in regions for i in range(16)}
    checks['exact48_unique_regions']=len(cells)==48 and {(c['region'],c['sector']) for c in cells}==expected and len({c['id'] for c in cells})==48
    cell_reports=[]
    for c in cells:
        region=c['region'];i=c['sector'];_,lo,hi=next(r for r in regions if r[0]==region)
        a,b=radial[(i-1)%16],radial[i];ln=np.array([a[1],-a[0]]);un=np.array([-b[1],b[0]])
        wedge=np.array([[0,*ln,-ln@center],[0,*un,-un@center]])
        base=np.c_[np.zeros(len(bp)),bp] if region=='boss_annular' else body
        original=np.vstack([base,[[-1,0,0,lo],[1,0,0,-hi]],wedge])
        if region!='rear_body_solid':original=np.vstack([original,[0,*(-ip[i,:2]),-ip[i,2]]])
        cv=np.asarray(c['vertices_mm'],float);cf=np.asarray(c['triangles'],int);cp=normalized(c['planes_mm']);construction=normalized(c['construction_planes_mm']);h=ConvexHull(cv)
        good=4<=len(cv)<=cfg['maximum_vertices_per_cell'] and np.isfinite(cv).all() and topology(cf) and c['axial_interval_mm']==[lo,hi] and plane_sets_equal(construction,original,tol) and plane_sets_equal(cp,h.equations,tol)
        good=good and np.max(cv@construction[:,:3].T+construction[:,3])<=margin and np.max(cv@cp[:,:3].T+cp[:,3])<=margin and h.volume>rules['minimum_cell_volume_mm3']
        # Every final hull facet must be an original construction boundary:
        # together with vertex containment this verifies the intended intersection.
        good=good and np.all(np.min(np.max(abs(cp[:,None]-normalized(original)[None]),axis=2),axis=1)<=tol)
        interior=np.asarray(c['lp_interior_mm']);slack=-(construction[:,:3]@interior+construction[:,3]).max()
        good=good and slack>cfg['minimum_LP_clearance_mm']-tol and abs(c['volume_mm3']-h.volume)<=max(tol,h.volume*1e-8)
        t=cv[cf];cross=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);length=np.linalg.norm(cross,axis=1)
        if np.any(length<=rules['normal_floor_mm2']):good=False
        else:good=good and np.max(np.einsum('fvi,fi->fv',cv[None]-t[:,:1],cross/length[:,None]))<=margin
        cell_reports.append({'id':c['id'],'passed':bool(good),'vertices':len(cv),'volume_mm3':float(h.volume),'LP_clearance_verified_mm':float(slack)})
    checks['all_cells_convex_valid']=all(r['passed'] for r in cell_reports)
    checks['sector_slab_partition_and_blind_cap']=checks['exact48_unique_regions'] and checks['all_cells_convex_valid'] and checks['source_cuts'] and checks['derived_hole_and_boss'] and checks['body_source_hull']
    return {k:bool(x) for k,x in checks.items()},cell_reports


def main():
    started=PROCESS_STARTED;parser=argparse.ArgumentParser(description=__doc__)
    for name in ['stl','features','candidate','probe-config','supervisor','output']:parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Actual construction/geometry audit requires default Pueue')
    protocol=read(HERE/'protocol.json');cfg=protocol['construction_config'];rules=protocol['audit'];result={'schema':protocol['schema'],'offline_candidate_passed':False,'cooking_authorized':False,'physical_collision_validated':False,'protocol_sha256':sha(HERE/'protocol.json'),'supervisor_sha256':sha(args.supervisor)}
    def stop(*_):raise TimeoutError('Shared construction+audit180s exhausted; no retry')
    signal.signal(signal.SIGALRM,stop);signal.setitimer(signal.ITIMER_REAL,cfg['maximum_construction_plus_audit_seconds'])
    try:
        supervisor=read(args.supervisor);prior_wall=protocol['budget']['charged_prior_wall_seconds'];capture_wall=float(supervisor['capture_wall_seconds']);reported_remaining=float(supervisor['remaining_independent_audit_seconds'])
        expected_remaining=cfg['maximum_construction_plus_audit_seconds']-prior_wall-capture_wall
        if supervisor['construction_completed'] is not True or not math.isfinite(capture_wall) or not math.isfinite(reported_remaining) or capture_wall<0 or expected_remaining<=0 or abs(reported_remaining-expected_remaining)>1e-9 or cfg['prior_consumed_active_seconds']!=prior_wall:raise ValueError('Invalid actual supervisor budget/completion')
        remaining=expected_remaining-(time.monotonic()-started)
        if remaining<=0:raise TimeoutError('No actual cumulative audit time remains')
        signal.setitimer(signal.ITIMER_REAL,remaining);deadline=started+expected_remaining
        result.update(charged_prior_wall_seconds=prior_wall,capture_wall_seconds=capture_wall,remaining_independent_audit_seconds=expected_remaining)
        if sha(args.stl)!=cfg['source_stl_sha256'] or sha(args.features)!=cfg['source_features_sha256'] or sha(args.probe_config)!=protocol['probe_config_sha256']:raise ValueError('Frozen reference hash mismatch')
        raw=args.stl.read_bytes();count=struct.unpack_from('<I',raw,80)[0]
        if len(raw)!=84+50*count:raise ValueError('Unexpected original STL')
        original=np.asarray([list(struct.iter_unpack('<fff',raw[84+50*i+12:84+50*i+48])) for i in range(count)])
        v,ix=np.unique(original.reshape(-1,3),axis=0,return_inverse=True);f=ix.reshape(-1,3)
        if not topology(f) or not np.isfinite(v).all():raise ValueError('Original source mesh invalid')
        # Source normals and samples are fixed before reading any candidate data.
        source_points,source_normals,source_volume=mesh_samples(v,f,cfg['validation']['source_sample_seed'],100000,125000,rules['normal_floor_mm2'])
        candidate=read(args.candidate);construction_wall=candidate['construction_wall_seconds']
        if candidate['status']!='candidate_constructed_requires_independent_audit' or candidate['construction_config']!=cfg or candidate['source_stl_sha256']!=cfg['source_stl_sha256'] or candidate['source_features_sha256']!=cfg['source_features_sha256'] or candidate['protocol_sha256']!=protocol['construction_protocol_sha256']:raise ValueError('Incomplete or changed single candidate')
        checks,cell_reports=manifest_checks(candidate,v,f,read(args.features),cfg,rules);result.update(checks=checks,cells=cell_reports)
        if not all(checks.values()):raise ValueError('Structural/provenance gate failed; no fallback')
        cells=candidate['cells'];all_vertices=np.concatenate([np.asarray(c['vertices_mm']) for c in cells]);all_triangles=np.concatenate([np.asarray(c['vertices_mm'])[np.asarray(c['triangles'],int)] for c in cells])
        bounds_error=float(abs(np.array([all_vertices.min(axis=0),all_vertices.max(axis=0)])-np.array([v.min(axis=0),v.max(axis=0)])).max())
        volume=sum(r['volume_mm3'] for r in cell_reports);volume_error=abs(volume-source_volume)/abs(source_volume)
        sampled,normals,_=union_samples(cells,cfg['validation']['candidate_sample_seed'],100000,125000,rules['normal_floor_mm2'])
        eps=cfg['validation']['union_membership_epsilon_mm'];bracket=cfg['validation']['candidate_external_bracket_mm'];limit=cfg['validation']['maximum_sampled_boundary_bound_mm']
        plus=contains(sampled+bracket*normals,cells,eps,deadline);minus=contains(sampled-bracket*normals,cells,eps,deadline);external=~plus&minus
        distances=triangle_distances(sampled[external],original,deadline)
        inside=contains(source_points,cells,0,deadline);outside_distance=triangle_distances(source_points[~inside],all_triangles,deadline)
        endpoint_inside=contains(source_points[inside]+limit*source_normals[inside],cells,eps,deadline)
        checks.update(bounds_100um=bounds_error<=cfg['validation']['maximum_outer_bound_error_mm'],volume_1percent=volume_error<=cfg['validation']['maximum_relative_volume_error'],candidate_sampled_boundary_100um=bool(len(distances)>0 and np.max(distances)+bracket<=limit),source_outside_exact_distance_100um=bool(not len(outside_distance) or outside_distance.max()<=limit),source_inside_fixed_normal_bound=bool(not endpoint_inside.any()))
        probes=read(args.probe_config)['fidelity'];points=[]
        for x in probes['bore_x_cad_mm']:
            for k in range(probes['bore_witnesses_per_x']):
                off=np.zeros(2) if k==0 else probes['bore_witness_radius_mm']*np.array([math.cos((k-1)*math.pi/4),math.sin((k-1)*math.pi/4)])
                points.append(np.r_[x,np.asarray(probes['bore_center_cad_yz_mm'])+off])
        points=np.asarray(points);reference_clear=triangle_distances(points,original,deadline);winding=outside_winding(points,original);void_inside=contains(points,cells,0,deadline);void_distance=triangle_distances(points,all_triangles,deadline)
        checks['all27_reference_free_spheres']=bool(len(points)==27 and np.all(abs(winding)<.1) and np.all(reference_clear>.25))
        checks['all27_candidate_free_spheres']=bool(not void_inside.any() and np.all(void_distance>cfg['validation']['void_sphere_radius_mm']))
        elapsed=time.monotonic()-started;checks['shared_180s_budget']=prior_wall+capture_wall+elapsed<=cfg['maximum_construction_plus_audit_seconds']
        result.update(status='offline_audit_complete',checks={k:bool(x) for k,x in checks.items()},offline_candidate_passed=bool(all(checks.values())),
            bounds_error_mm=bounds_error,source_volume_mm3=source_volume,candidate_volume_mm3=volume,relative_volume_error=volume_error,
            candidate_samples={'total':len(sampled),'confirmed_exterior':int(external.sum()),'both_probes_inside':int((plus&minus).sum()),'other_filtered':int((~external&~(plus&minus)).sum()),'max_exact_STL_distance_mm':float(distances.max()) if len(distances) else None,'boundary_bracket_margin_mm':bracket},
            source_samples={'total':len(source_points),'strict_inside':int(inside.sum()),'outside_exact_distance_max_mm':float(outside_distance.max()) if len(outside_distance) else None,'inside_normal_endpoints_still_inside':int(endpoint_inside.sum()),'inside_metric':'Fixed100um-normal endpoint upper-bound test only; not nearest Euclidean or Hausdorff distance'},
            bore_witnesses=[{'CAD_mm':p.tolist(),'reference_clearance_mm':float(a),'candidate_distance_mm':float(b),'candidate_inside':bool(c)} for p,a,b,c in zip(points,reference_clear,void_distance,void_inside)],construction_wall_seconds=construction_wall,audit_wall_seconds=elapsed,total_wall_seconds=prior_wall+capture_wall+elapsed,
            scope='One fixed sampled CAD candidate; not global certification, mounting confirmation, native cooking or contact validation. Old failed benchmarks remain closed.')
    except Exception as error:result.update(status='STOP',error=repr(error),audit_wall_seconds=time.monotonic()-started)
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);args.output.mkdir(parents=True,exist_ok=True)
        (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
        (args.output/'run_complete.json').write_text(json.dumps({'evaluation_completed':True,'offline_candidate_passed':result['offline_candidate_passed'],'cooking_authorized':False,'evaluation_sha256':sha(args.output/'evaluation.json')})+'\n')


if __name__=='__main__':main()

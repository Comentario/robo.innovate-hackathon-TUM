"""One asset-specific48-cell CAD candidate; no Kit, cooking or contact."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import time

HERE=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def boundary_loops(faces):
    """Exact indexed boundary of a declared source face patch; no mesh repair."""
    edges=[tuple(sorted((int(a),int(b)))) for tri in faces for a,b in zip(tri,[tri[1],tri[2],tri[0]])]
    boundary=[edge for edge,count in Counter(edges).items() if count==1];adj=defaultdict(set)
    for a,b in boundary:adj[a].add(b);adj[b].add(a)
    if not adj or any(len(v)!=2 for v in adj.values()):raise ValueError('Source patch boundary is open/branched')
    remaining=set(adj);loops=[]
    while remaining:
        root=min(remaining);order=[root];previous=None;node=root
        while True:
            other=min(adj[node]-({previous} if previous is not None else set()))
            if other==root:break
            if other in order:raise ValueError('Invalid source boundary cycle')
            order.append(other);previous,node=node,other
        remaining-=set(order);loops.append(order)
    return loops


def area_centroid(points):
    import numpy as np
    other=np.roll(points,-1,axis=0);cross=points[:,0]*other[:,1]-other[:,0]*points[:,1];twice=cross.sum()
    if abs(twice)<1e-12:raise ValueError('Zero source polygon area')
    return abs(twice)/2,np.sum((points+other)*cross[:,None],axis=0)/(3*twice)


class VertexCapStop(ValueError):
    def __init__(self,details):
        super().__init__(f"Fixed{details['vertex_cap']}-vertex CPU cap exceeded; no splitting")
        self.details=details


def cell(planes,minimum_clearance,vertex_cap):
    import numpy as np
    from scipy.optimize import linprog
    from scipy.spatial import HalfspaceIntersection,ConvexHull
    planes=np.asarray(planes,float);planes/=np.linalg.norm(planes[:,:3],axis=1)[:,None]
    lp=linprog([0,0,0,-1],A_ub=np.c_[planes[:,:3],np.ones(len(planes))],b_ub=-planes[:,3],
        bounds=[(None,None)]*3+[(0,None)],method='highs')
    if not lp.success or lp.x[3]<=minimum_clearance:raise ValueError('Cell lacks strict LP interior; no fallback')
    intersections=HalfspaceIntersection(planes,lp.x[:3]).intersections
    if not np.isfinite(intersections).all():raise ValueError('Nonfinite cell intersections')
    first_hull=ConvexHull(intersections);vertices=intersections[first_hull.vertices];h=ConvexHull(vertices)
    if len(vertices)>vertex_cap:
        raise VertexCapStop({'vertex_cap':vertex_cap,'final_vertex_count':len(vertices),
            'raw_HSI_intersection_count':len(intersections),'exact_unique_raw_HSI_intersections':len(np.unique(intersections,axis=0)),
            'exact_unique_final_vertices':len(np.unique(vertices,axis=0)),'raw_HSI_intersections_mm':intersections.tolist(),
            'first_hull_extreme_indices':first_hull.vertices.tolist(),'final_vertices_mm':vertices.tolist(),
            'final_hull_triangles':h.simplices.tolist(),'final_hull_equations':h.equations.tolist(),
            'final_triangular_facet_count':len(h.simplices),
            'exact_unique_final_plane_rows':len(set(map(tuple,h.equations))),
            'construction_planes_mm':planes.tolist(),'LP_interior_mm':lp.x[:3].tolist(),'LP_clearance_mm':float(lp.x[3])})
    triangles=[]
    for face,plane in zip(h.simplices,h.equations):
        face=face.copy();t=vertices[face]
        if np.dot(np.cross(t[1]-t[0],t[2]-t[0]),plane[:3])<0:face=face[::-1]
        triangles.append(face.tolist())
    return {'vertices_mm':vertices.tolist(),'planes_mm':h.equations.tolist(),
        'construction_planes_mm':planes.tolist(),'triangles':triangles,
        'volume_mm3':float(h.volume),'lp_interior_mm':lp.x[:3].tolist(),'lp_clearance_mm':float(lp.x[3])}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['stl','features','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--cap-diagnostic',action='store_true')
    args=p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    cfg=json.loads((HERE/'protocol.json').read_text());start=time.monotonic();args.output.mkdir(parents=True,exist_ok=True)
    diagnostic=json.loads((HERE/'diagnostic_scope.json').read_text()) if args.cap_diagnostic else None
    if diagnostic and sha(HERE/'protocol.json')!=diagnostic['construction_protocol_sha256']:raise ValueError('Diagnostic constructionprotocol changed')
    result={'schema':cfg['schema'],'proceed_gate_passed':False,'cooking_authorized':False,'coordinate_frame':cfg['coordinate_frame'],
        'protocol_sha256':sha(HERE/'protocol.json'),'cells':[],'prior_benchmarks':'Closed and unchanged'}
    def timeout(*_):raise TimeoutError('Fixed construction budget exhausted; no retry/alternate cells')
    signal.signal(signal.SIGALRM,timeout);signal.setitimer(signal.ITIMER_REAL,diagnostic['maximum_wall_seconds'] if diagnostic else cfg['maximum_construction_seconds'])
    try:
        import numpy as np
        import scipy
        from scipy.spatial import ConvexHull
        if sha(args.stl)!=cfg['source_stl_sha256'] or sha(args.features)!=cfg['source_features_sha256']:raise ValueError('Frozen source hash mismatch')
        feature=json.loads(args.features.read_text());raw=args.stl.read_bytes();count=struct.unpack_from('<I',raw,80)[0]
        if len(raw)!=84+50*count:raise ValueError('Unexpected binary STL encoding')
        xyz=np.asarray([list(struct.iter_unpack('<fff',raw[84+50*i+12:84+50*i+48])) for i in range(count)])
        vertices,inverse=np.unique(xyz.reshape(-1,3),axis=0,return_inverse=True);faces=inverse.reshape(-1,3)
        if not np.isfinite(vertices).all():raise ValueError('Nonfinite source')
        margin=cfg['numerical_margin_mm'];clusters=feature['plane_clusters'];ids={name:clusters[index]['face_ids'] for name,index in cfg['source_feature_clusters'].items()}
        cuts={name:float(np.median(vertices[np.unique(faces[indices])][:,0])) for name,indices in ids.items()}
        for name,indices in ids.items():
            if np.max(abs(vertices[np.unique(faces[indices])][:,0]-cuts[name]))>margin:raise ValueError('Source cut is not an axial plane')
        if not cuts['boss_front_annulus']<cuts['body_front']<cuts['blind_bore_cap']<cuts['rear_plane']:raise ValueError('Axial source ordering failed')
        loops=boundary_loops(faces[ids['blind_bore_cap']])
        if len(loops)!=1:raise ValueError('Blind cap must supply one source inner boundary')
        inner=vertices[loops[0],1:];inner_area,center=area_centroid(inner)
        annulus=boundary_loops(faces[ids['boss_front_annulus']])
        if len(annulus)!=2:raise ValueError('Boss annulus must have exactly two source boundaries')
        annulus.sort(key=lambda loop:area_centroid(vertices[loop,1:])[0],reverse=True)
        outer=vertices[annulus[0],1:];outer_hull=ConvexHull(outer);outer_planes=outer_hull.equations
        # Source loop must itself be convex to justify an inscribed-radius construction.
        signed=sum(np.cross(outer[(i+1)%len(outer)]-outer[i],outer[(i+2)%len(outer)]-outer[(i+1)%len(outer)]) for i in range(len(outer)))
        if signed<0:outer=outer[::-1]
        for a,b in zip(outer,np.roll(outer,-1,axis=0)):
            n=np.array([b[1]-a[1],a[0]-b[0]]);n/=np.linalg.norm(n)
            if np.max((outer-a)@n)>margin:raise ValueError('Source boss outer loop is nonconvex; no fallback')
        safe_radius=float(np.min(-(outer_planes[:,:2]@center+outer_planes[:,2]))-margin)
        if safe_radius<=0:raise ValueError('Inner centroid is not safely inside source boss')
        theta=cfg['fixed_normal_phase_rad']+np.arange(cfg['sectors'])*2*np.pi/cfg['sectors'];normals=np.c_[np.cos(theta),np.sin(theta)]
        support=np.max(normals@(inner-center).T,axis=1)+margin
        inner_planes=np.c_[normals,-support-normals@center]
        polygon=np.asarray([np.linalg.solve(normals[[i,(i+1)%16]],-inner_planes[[i,(i+1)%16],2]) for i in range(16)])
        radial=polygon-center;boss_polygon=center+safe_radius*radial/np.linalg.norm(radial,axis=1)[:,None]
        boss_planes=ConvexHull(boss_polygon).equations
        body_points=vertices[vertices[:,0]>=cuts['body_front']-margin];body=ConvexHull(body_points)
        body_planes=body.equations
        provenance={'source_face_ids':ids,'cuts_x_mm':cuts,'inner_source_loop_yz_mm':inner.tolist(),'inner_area_mm2':inner_area,
            'source_hole_centroid_yz_mm':center.tolist(),'source_outer_boss_loop_yz_mm':outer.tolist(),
            'safe_boss_radius_mm':safe_radius,'inner16_vertices_yz_mm':polygon.tolist(),'inner16_planes_yz_mm':inner_planes.tolist(),
            'boss16_vertices_yz_mm':boss_polygon.tolist(),'boss16_planes_yz_mm':boss_planes.tolist(),
            'body_source_vertex_indices':np.flatnonzero(vertices[:,0]>=cuts['body_front']-margin).tolist(),'body_planes_mm':body_planes.tolist(),'sector_planes_mm':[]}
        regions=[('boss_annular',cuts['boss_front_annulus'],cuts['body_front']),('front_body_bored',cuts['body_front'],cuts['blind_bore_cap']),('rear_body_solid',cuts['blind_bore_cap'],cuts['rear_plane'])]
        for region,lo,hi in regions:
            for i in range(16):
                a,b=radial[(i-1)%16],radial[i]
                lower=np.array([a[1],-a[0]]);upper=np.array([-b[1],b[0]])
                wedge=np.array([[0,*lower,-lower@center],[0,*upper,-upper@center]])
                if region=='boss_annular':base=np.c_[np.zeros(len(boss_planes)),boss_planes]
                else:base=body_planes.copy()
                planes=np.vstack([base,[[-1,0,0,lo],[1,0,0,-hi]],wedge])
                if region!='rear_body_solid':planes=np.vstack([planes,[0,*(-inner_planes[i,:2]),-inner_planes[i,2]]])
                formed=cell(planes,cfg['minimum_LP_clearance_mm'],cfg['maximum_vertices_per_cell'])
                formed.update(id=f'{region}_{i:02d}',region=region,sector=i,axial_interval_mm=[lo,hi])
                result['cells'].append(formed)
                if region=='boss_annular':provenance['sector_planes_mm'].append((wedge/np.linalg.norm(wedge[:,:3],axis=1)[:,None]).tolist())
        if len(result['cells'])!=cfg['required_parts']:raise ValueError('Fixed48-cell inventory failed')
        if diagnostic:raise RuntimeError('Expected128capSTOP did not recur; diagnostic only, no candidate acceptance')
        points=np.concatenate([np.asarray(c['vertices_mm']) for c in result['cells']])
        result.update(status='candidate_constructed_requires_independent_audit',source_stl_sha256=sha(args.stl),source_features_sha256=sha(args.features),
            construction_config=cfg,provenance=provenance,union_bounds_mm=[points.min(axis=0).tolist(),points.max(axis=0).tolist()],
            total_cell_volume_mm3=sum(c['volume_mm3'] for c in result['cells']),versions={'numpy':np.__version__,'scipy':scipy.__version__})
    except Exception as error:
        result.update(status='STOP',error=repr(error))
        if diagnostic and isinstance(error,VertexCapStop):
            failure={'schema':diagnostic['schema'],'proceed_gate_passed':False,'status':'UNCHANGED128CAP_STOP',
                'id':f'{region}_{i:02d}','region':region,'sector':i,'axial_interval_mm':[lo,hi],
                'construction_protocol_sha256':sha(HERE/'protocol.json'),'source_stl_sha256':sha(args.stl),
                'source_features_sha256':sha(args.features),'details':error.details}
            (args.output/'vertex_cap_diagnostic.json').write_text(json.dumps(failure,indent=2,allow_nan=False)+'\n')
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);result['construction_wall_seconds']=time.monotonic()-start
        result['remaining_independent_audit_seconds']=max(0.,cfg['maximum_construction_plus_audit_seconds']-(diagnostic['baseline_process_wall_seconds'] if diagnostic else cfg.get('prior_consumed_active_seconds',0.))-result['construction_wall_seconds'])
        if diagnostic:result['diagnostic_scope_sha256']=sha(HERE/'diagnostic_scope.json')
        (args.output/'compound.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if result['status']!='candidate_constructed_requires_independent_audit':raise SystemExit(1)


if __name__=='__main__':main()

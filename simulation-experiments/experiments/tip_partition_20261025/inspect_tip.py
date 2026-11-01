"""One queued original-STL inspection; no proxy construction or cooking."""
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

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def segment_graph(lines,quantum):
    """Descriptive quantized connectivity; never heal an open section."""
    import numpy as np
    keys=np.rint(np.asarray(lines)[:,:,1:]/quantum).astype('int64')
    edges=[tuple(sorted((tuple(a),tuple(b)))) for a,b in keys]
    counts=Counter(edges);adj=defaultdict(set)
    for a,b in counts:
        adj[a].add(b);adj[b].add(a)
    pending=set(adj);components=[]
    while pending:
        root=min(pending);todo=[root];nodes=set()
        while todo:
            node=todo.pop()
            if node not in nodes:nodes.add(node);todo.extend(adj[node]-nodes)
        pending-=nodes;valid=all(len(adj[n])==2 for n in nodes) and all(a!=b and c==1 for (a,b),c in counts.items() if a in nodes)
        record={'nodes':len(nodes),'degree_histogram':dict(Counter(len(adj[n]) for n in nodes)),
                'closed_unbranched_unique_edges':valid,'quantized_loop_yz_mm':None,'absolute_area_mm2':None}
        if valid:
            order=[root];previous=None;node=root
            while True:
                next_node=min(adj[node]-({previous} if previous is not None else set()))
                if next_node==root:break
                order.append(next_node);previous,node=node,next_node
                if len(order)>len(nodes):raise ValueError('Unexpected section traversal')
            points=np.asarray(order,float)*quantum
            record.update(quantized_loop_yz_mm=points.tolist(),absolute_area_mm2=float(abs(np.sum(points[:,0]*np.roll(points[:,1],-1)-points[:,1]*np.roll(points[:,0],-1)))/2))
        components.append(record)
    return {'raw_segments':len(lines),'quantized_unique_edges':len(counts),'duplicate_edges':sum(c-1 for c in counts.values()),
            'zero_length_quantized_edges':sum(a==b for a,b in counts),'components':components,
            'interpretation':'Quantized endpoint connectivity only; loop orientation and outer/hole nesting are not inferred.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stl',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required for STL inspection')
    protocol=json.loads((HERE/'protocol.json').read_text());started=time.monotonic()
    result={'schema':protocol['schema'],'proceed_gate_passed':False,'parts_constructed':False,
            'prior_benchmarks':'Closed and unchanged','protocol_sha256':sha(HERE/'protocol.json')}
    args.output.mkdir(parents=True,exist_ok=True)
    def deadline(*_):raise TimeoutError('Frozen60second inspection exhausted; no retry/adaptation')
    signal.signal(signal.SIGALRM,deadline);signal.setitimer(signal.ITIMER_REAL,protocol['maximum_wall_seconds'])
    try:
        import numpy as np
        import scipy
        from scipy.spatial import ConvexHull
        import trimesh
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.collections import PolyCollection,LineCollection
        if sha(args.stl)!=protocol['source_stl_sha256']:raise ValueError('Original STL hash mismatch')
        config_path=ROOT/protocol['configuration_reference']
        if sha(config_path)!=protocol['configuration_reference_sha256']:raise ValueError('Frozen probe definition changed')
        config=json.loads(config_path.read_text());data=args.stl.read_bytes();count=struct.unpack_from('<I',data,80)[0]
        if len(data)!=84+count*50:raise ValueError('Unexpected binary STL layout')
        raw=np.asarray([list(struct.iter_unpack('<fff',data[84+50*i+12:84+50*i+48])) for i in range(count)])
        if not np.isfinite(raw).all():raise ValueError('Nonfinite original STL')
        vertices,inverse=np.unique(raw.reshape(-1,3),axis=0,return_inverse=True);faces=inverse.reshape(-1,3)
        mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=False,validate=False)
        triangles=vertices[faces];cross=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);lengths=np.linalg.norm(cross,axis=1)
        valid=lengths>protocol['numerical_triangle_cross_norm_mm2'];volume=float(np.sum(triangles[:,0]*np.cross(triangles[:,1],triangles[:,2]))/6)
        normals=np.zeros_like(cross);normals[valid]=cross[valid]/lengths[valid,None]*(1 if volume>=0 else -1)
        offsets=-np.sum(normals*triangles[:,0],axis=1);maxres=np.max(normals@vertices.T+offsets[:,None],axis=1)
        support=valid&(maxres<=protocol['supporting_plane_residual_mm']);clusters=defaultdict(list)
        for i in np.flatnonzero(valid):
            key=tuple(np.rint(normals[i]/protocol['normal_component_quantum']).astype('int64'))+(int(round(offsets[i]/protocol['plane_offset_quantum_mm'])),)
            clusters[key].append(int(i))
        edges=np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]]);counts=Counter(map(tuple,np.sort(edges,axis=1)));oriented=Counter(map(tuple,edges))
        hull=ConvexHull(vertices);levels={}
        for axis,name in enumerate('XYZ'):
            exact,n=np.unique(vertices[:,axis],return_counts=True);rounded,rn=np.unique(np.rint(vertices[:,axis]/protocol['coordinate_level_quantum_mm']).astype('int64'),return_counts=True)
            levels[name]={'exact_levels_mm':exact.tolist(),'vertex_counts':n.tolist(),'quantized_levels_mm':(rounded*protocol['coordinate_level_quantum_mm']).tolist(),'quantized_vertex_counts':rn.tolist()}
        result.update(status='features_computed',source_stl_sha256=sha(args.stl),coordinate_unit=protocol['coordinate_unit'],
            triangle_count=count,unique_vertices=len(vertices),bounds_mm=[vertices.min(axis=0).tolist(),vertices.max(axis=0).tolist()],coordinate_levels=levels,
            topology={'non_two_incident_edges':sum(c!=2 for c in counts.values()),'oriented_edge_mismatch':sum(abs(c-oriented[(b,a)]) for (a,b),c in oriented.items()),'degenerate_triangles':int(np.count_nonzero(~valid))},
            volume={'signed_STL_mm3':volume,'vertex_hull_mm3':float(hull.volume),'hull_minus_absolute_STL_mm3':float(hull.volume-abs(volume))},
            supporting_face_ids=np.flatnonzero(support).tolist(),non_supporting_face_ids=np.flatnonzero(valid&~support).tolist(),
            plane_clusters=[{'face_ids':ids,'representative_unit_normal':normals[ids[0]].tolist(),'representative_offset_mm':float(offsets[ids[0]]),
                'area_mm2':float(lengths[ids].sum()/2),'supporting_face_count':int(support[ids].sum()),'maximum_other_vertex_plane_residual_mm':float(maxres[ids].max())} for ids in clusters.values()],
            sections=[],versions={'numpy':np.__version__,'scipy':scipy.__version__,'trimesh':trimesh.__version__,'matplotlib':matplotlib.__version__},
            feasibility='UNASSESSED: inspect reported loops/planes/projections before proposing any fixed convex parts.')
        f=config['fidelity'];probes=[]
        for x in f['bore_x_cad_mm']:
            for k in range(f['bore_witnesses_per_x']):
                offset=np.zeros(2) if k==0 else f['bore_witness_radius_mm']*np.array([math.cos((k-1)*math.pi/4),math.sin((k-1)*math.pi/4)])
                probes.append(np.r_[x,np.asarray(f['bore_center_cad_yz_mm'])+offset])
        probes=np.asarray(probes);result['reference_probes_CAD_mm']=probes.tolist()
        sections=protocol['section_x_mm']
        if len(sections)>protocol['maximum_sections']:raise ValueError('Frozen section cap exceeded')
        for x in sections:
            segments,face_ids=trimesh.intersections.mesh_plane(mesh,[1,0,0],[x,0,0],return_faces=True)
            coplanar=int(np.count_nonzero(np.all(abs(triangles[:,:,0]-x)<=protocol['section_coplanar_tolerance_mm'],axis=1)))
            result['sections'].append({'x_mm':x,'raw_segments_xyz_mm':segments.tolist(),'source_face_ids':face_ids.tolist(),
                'fully_coplanar_source_faces':coplanar,'vertices_near_section':int(np.count_nonzero(abs(vertices[:,0]-x)<=protocol['section_coplanar_tolerance_mm'])),
                'graph':segment_graph(segments,protocol['section_endpoint_quantum_mm']),
                'ambiguity':'Coplanar faces omitted by mesh_plane; no missing segment repair or filled polygon inferred.'})
        fig,axes=plt.subplots(1,3,figsize=(13,5))
        for ax,(a,b) in zip(axes,[(0,1),(0,2),(1,2)]):
            colors=np.where(support[:,None],np.array([.45,.65,.8,.25]),np.array([.9,.4,.2,.35]))
            ax.add_collection(PolyCollection(triangles[:,:,[a,b]],facecolors=colors,edgecolors=(.1,.1,.1,.2),linewidths=.2))
            ax.scatter(probes[:,a],probes[:,b],s=10,c='magenta',marker='+');ax.autoscale();ax.set_aspect('equal');ax.set_xlabel('XYZ'[a]+' (nominal mm)');ax.set_ylabel('XYZ'[b]+' (nominal mm)')
        fig.suptitle('All projected STL facets/hidden edges; supporting blue, non-supporting orange; probe projections magenta')
        fig.tight_layout();fig.savefig(args.output/'orthographic.png',dpi=160);plt.close(fig)
        fig,axes=plt.subplots(4,5,figsize=(15,12))
        for ax,section in zip(axes.flat,result['sections']):
            lines=np.asarray(section['raw_segments_xyz_mm'])
            if len(lines):ax.add_collection(LineCollection(lines[:,:,1:],colors='navy',linewidths=.8))
            ax.scatter(probes[:,1],probes[:,2],s=6,c='magenta',marker='+');ax.autoscale();ax.set_aspect('equal');ax.set_title(f"X={section['x_mm']:g} mm");ax.set_xlabel('Y mm');ax.set_ylabel('Z mm')
        fig.suptitle('Fixed original-STL sections; raw segments only, no caps or inferred solids')
        fig.tight_layout();fig.savefig(args.output/'sections.png',dpi=140);plt.close(fig)
        result['status']='inspection_complete'
    except Exception as error:result.update(status='STOP',error=repr(error))
    finally:
        signal.setitimer(signal.ITIMER_REAL,0);result['wall_seconds']=time.monotonic()-started
        (args.output/'features.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if result['status']!='inspection_complete':raise SystemExit(1)


if __name__=='__main__':main()

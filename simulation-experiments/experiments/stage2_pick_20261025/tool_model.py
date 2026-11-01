"""Reuse the accepted exposed body/head authoring, preservation and cook identity."""
from pathlib import Path
import hashlib,json
import numpy as np
from experiments.stage2_exposed_tip_20261025.model import Adapter,save

class Tool(Adapter):
    def __init__(self,output):
        super().__init__('G');self.phase='component_reuse';self.output=output  # Constructor/author only; never old initial/G/query path.
    def validate(self,context):
        from pxr import UsdGeom
        from isaaclab.sim import get_current_stage
        from omni.physx import get_physx_cooking_interface
        from omni.physx.bindings._physx import PhysxCollisionRepresentationResult
        from pxr import UsdUtils,PhysicsSchemaTools
        stage=get_current_stage();robot=context['robot'];view=robot.root_physx_view
        props={k:getattr(view,m)().cpu().numpy().tolist() for k,m in [('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms'),('stiffnesses','get_dof_stiffnesses'),('dampings','get_dof_dampings'),('effort_limits','get_dof_max_forces')]}
        if props!=self.reference['robot_properties']:raise RuntimeError('Strict frozen robot properties differ')
        result={'tips':{},'canonical_sha256':{}}
        # Exact accepted cook/identity loop, without old global300 query fixture.
        for label,tip in self.records.items():
            result['tips'][label]={};canonical={}
            for kind,part in tip['parts'].items():
                answer={}
                def ready(code,hulls):
                    answer.update(path=part['path'],result=str(code),result_valid=code==PhysxCollisionRepresentationResult.RESULT_VALID,hull_count=len(hulls or []),hulls=[])
                    for h in hulls or []:answer['hulls'].append({'vertices_m':[[float(v.x),float(v.y),float(v.z)] for v in h.vertices],'polygons':[{'plane':list(p.plane),'indices':list(h.indices[p.index_base:p.index_base+p.num_vertices])} for p in h.polygons],'vertex_count':len(h.vertices),'polygon_count':len(h.polygons)})
                get_physx_cooking_interface().request_convex_collision_representation(stage_id=UsdUtils.StageCache.Get().GetId(stage).ToLongInt(),collision_prim_id=PhysicsSchemaTools.sdfPathToInt(part['path']),run_asynchronously=False,on_result=ready)
                result['tips'][label][kind]=answer;save(self.output/'cook_results.json',result)
                if not answer.get('result_valid') or answer['hull_count']!=1:raise RuntimeError('One valid convex hull per body/head required')
                h=answer['hulls'][0];v=np.asarray(h['vertices_m'])
                if not np.isfinite(v).all() or not 4<=h['vertex_count']<=255 or not 4<=h['polygon_count']<=255:raise RuntimeError('Actual CPU hull/count failure')
                planes=np.asarray([p['plane'] for p in h['polygons']],float);length=np.linalg.norm(planes[:,:3],axis=1)
                if not np.isfinite(planes).all() or np.any(length==0):raise RuntimeError('Invalid cooked identity planes')
                planes=planes/length[:,None];q=self.cfg['canonical_hash_quantization'];rows=np.c_[np.rint(planes[:,:3]/q['unit_normal']),np.rint(planes[:,3]/q['plane_offset_m'])].astype(np.int64)
                canonical[kind]={'vertices':sorted(map(tuple,np.rint(v/q['vertex_m']).astype(np.int64).tolist())),'normalized_planes':sorted(map(tuple,rows.tolist()))}
            result['canonical_sha256'][label]=hashlib.sha256(json.dumps(canonical,sort_keys=True).encode()).hexdigest()
        authorization=json.loads((Path(__file__).parent/'inputs/side_authorization.json').read_text())
        if result['canonical_sha256']!=authorization['cooked_hashes']:raise RuntimeError('Tool cook changed from accepted lateral representation')
        self.cooked=result;save(self.output/'cook_results.json',result)
        self.geometry=self.audit(stage,self.output/'tool_geometry.json')
        return props

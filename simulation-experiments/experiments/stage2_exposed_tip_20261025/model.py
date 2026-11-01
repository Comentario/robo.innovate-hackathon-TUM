"""One user-authorized exposed-body hull and 32-sided outside-head envelope."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import numpy as np
from scipy.spatial import ConvexHull
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'experiments/stage2_contact_20261025')]
from experiments.stage2_contact_20261025 import geometry as stock
from experiments.final_workcell_20261024.end_effector.fingertips import nominal_mount_parameters
from experiments.stage2_exposed_tip_20261025.preserve_properties import install

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):Path(p).write_text(json.dumps(v,indent=2,allow_nan=False)+'\n')

def load_body(cfg):
    data=(ROOT/cfg['stl']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=cfg['stl_sha256']:raise RuntimeError('Original STL changed')
    count=struct.unpack_from('<I',data,80)[0]
    if len(data)!=84+50*count:raise RuntimeError('Unexpected STL encoding')
    faces=np.asarray([list(struct.iter_unpack('<fff',data[84+50*i+12:84+50*i+48])) for i in range(count)])
    selected=faces[np.all(faces[:,:,0]>=cfg['body_min_cad_x_mm']-cfg['source_cut_epsilon_mm'],axis=1)]
    vertices=np.unique(faces.reshape(-1,3),axis=0)
    vertices=vertices[vertices[:,0]>=cfg['body_min_cad_x_mm']-cfg['source_cut_epsilon_mm']]
    hull=ConvexHull(vertices);vertices=vertices[hull.vertices];hull=ConvexHull(vertices)
    if len(vertices)>cfg['maximum_source_unique_body_points']:raise RuntimeError('Unexpected source body size; no input simplification')
    triangles=hull.simplices.copy()
    for i,face in enumerate(triangles):
        if np.dot(np.cross(vertices[face[1]]-vertices[face[0]],vertices[face[2]]-vertices[face[0]]),hull.equations[i,:3])<0:triangles[i,[1,2]]=triangles[i,[2,1]]
    return vertices,triangles,selected


def head_mesh(center,radius,height,sides):
    theta=np.arange(sides)*2*np.pi/sides
    ring=np.c_[radius*np.cos(theta),np.zeros(sides),radius*np.sin(theta)]
    points=np.vstack((ring+[0,-height/2,0],ring+[0,height/2,0]))+center
    faces=[]
    for i in range(sides):
        j=(i+1)%sides;faces.extend([[i,j,sides+j],[i,sides+j,sides+i]])
    faces.extend([[0,i+1,i] for i in range(1,sides-1)])
    faces.extend([[sides,sides+i,sides+i+1] for i in range(1,sides-1)])
    return points,np.asarray(faces,int)[:,[0,2,1]]


class Adapter:
    def __init__(self,phase,approved=None,side_authorization=None):
        self.phase=phase;self.approved=approved;self.protocol_path=HERE/'protocol.json'
        self.protocol=json.loads(self.protocol_path.read_text());self.cfg=json.loads((HERE/'model_config.json').read_text())
        if sha(HERE/'model_config.json')!=self.protocol['model_config_sha256']:raise RuntimeError('Frozen model changed')
        self.reference=json.loads((ROOT/'experiments/stage2_contact_20261025/proxy_reference.json').read_text())
        self.side_authorization_path=side_authorization
        if phase!='G':
            if approved is None or side_authorization is None:raise RuntimeError('Contact requires original geometry audit and separate side authorization')
            audit=json.loads(approved.read_text());authorization=json.loads(side_authorization.read_text())
            if sha(approved)!=self.protocol['side_contact']['original_geometry_audit_sha256'] or audit['phase']!='G' or audit['proceed_gate_passed'] is not False:raise RuntimeError('Original failed G artifact must remain unchanged')
            if authorization['schema']!='exposed-tip-lateral-authorization-v1' or authorization['authorization']!='D_then_conditional_R_lateral_only' or authorization['global_G_passed'] is not False or authorization['existing_attempts_only'] is not True:raise RuntimeError('Invalid lateral-only authorization scope')
            if authorization['geometry_audit_sha256']!=sha(approved) or authorization['model_config_sha256']!=sha(HERE/'model_config.json') or authorization['cooked_hashes']!=audit['cooked_hashes']:raise RuntimeError('Side authorization does not bind the exact G/config/cook')
        self.records={};self.fixture={};self.output=None;self.cooked={}
        if sha(HERE/'head_reference.json')!=self.cfg['head_reference_sha256']:raise RuntimeError('Pinned1773 head report changed')
        self.head_reference=json.loads((HERE/'head_reference.json').read_text())

    def configure(self,env):
        before=env.sim.to_dict();env.sim.enable_scene_query_support=True
        self.configuration={'enable_scene_query_support_before':before['enable_scene_query_support'],'enable_scene_query_support_after':True,'only_query_support_change_verified':True}
        if env.sim.to_dict()!={**before,'enable_scene_query_support':True}:raise RuntimeError('Unexpected query-support setting change')

    def author(self,stage,scene,output):
        from pxr import UsdGeom,UsdPhysics,UsdShade,PhysxSchema,Gf
        self.output=output;raw,faces,source=load_body(self.cfg);spec=self.cfg['scene_fingertip_spec']
        self.stock_before=stock.audit(stage,output/'geometry_stock_before.json')
        for label,left in (('left',True),('right',False)):
            parent=stock.BODIES[label];path=parent+'/collisions/mesh_3';prim=stage.GetPrimAtPath(path)
            if prim.GetTypeName()!='Cube' or prim.IsInstanceProxy():raise RuntimeError('Expected stock pad Cube')
            mat,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
            if not mat:raise RuntimeError('Stock pad material missing')
            angle,t=nominal_mount_parameters(spec,left);a=np.deg2rad(angle)
            rotation=np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1.]])@np.diag([-1.,1.,-1.])
            vertices=raw*spec['assumed_stl_unit_m']@rotation.T+t
            ops=UsdGeom.Xformable(prim).GetOrderedXformOps();mesh=UsdGeom.Mesh.Define(stage,path);UsdGeom.Xformable(mesh).ClearXformOpOrder()
            for op in ops:op.GetAttr().Block()
            head=self.head_reference['heads'][parent.rsplit('/',1)[-1]]
            if head['axis']!='Y':raise RuntimeError('Pinned head axis changed')
            center=head['head_center_finger_m'];radius=head['head_radius_m'];height=head['head_height_m']
            hv,hf=head_mesh(center,radius,height,self.cfg['head_sides']);hp=parent+'/UpdatedTipFastenerCollision/Head'
            head_mat,_=UsdShade.MaterialBindingAPI(stage.GetPrimAtPath(parent+'/collisions/mesh_2')).ComputeBoundMaterial('physics')
            parts={}
            for kind,p,v,f,material in (('body',path,vertices,faces,mat),('head',hp,hv,hf,head_mat)):
                m=UsdGeom.Mesh.Define(stage,p);m.CreatePointsAttr(v.tolist());m.CreateFaceVertexCountsAttr([3]*len(f));m.CreateFaceVertexIndicesAttr(np.asarray(f).ravel().tolist());m.CreateSubdivisionSchemeAttr('none');m.CreateExtentAttr([v.min(axis=0).tolist(),v.max(axis=0).tolist()])
                m.CreateVisibilityAttr('invisible')
                UsdPhysics.CollisionAPI.Apply(m.GetPrim()).CreateCollisionEnabledAttr(True);UsdPhysics.MeshCollisionAPI.Apply(m.GetPrim()).CreateApproximationAttr('convexHull')
                api=PhysxSchema.PhysxConvexHullCollisionAPI.Apply(m.GetPrim());api.CreateHullVertexLimitAttr(255);api.CreateMinThicknessAttr(.0001)
                if material:UsdShade.MaterialBindingAPI.Apply(m.GetPrim()).Bind(material,materialPurpose='physics')
                readback={'approximation':UsdPhysics.MeshCollisionAPI(m).GetApproximationAttr().Get(),'hullVertexLimit':api.GetHullVertexLimitAttr().Get(),'minThickness':api.GetMinThicknessAttr().Get()}
                if readback['approximation']!='convexHull' or readback['hullVertexLimit']!=255 or abs(readback['minThickness']-.0001)>self.cfg['schema_float_atol_m']:raise RuntimeError('Explicit cook settings mismatch')
                xf=UsdGeom.Xformable(m).ComputeLocalToWorldTransform(0)*UsdGeom.Xformable(stage.GetPrimAtPath(parent)).ComputeLocalToWorldTransform(0).GetInverse()
                if np.max(abs(np.asarray(list(map(list,xf)))-np.eye(4)))>1e-9:raise RuntimeError('Baked collider transform not identity')
                parts[kind]={'path':p,'vertices_finger_m':v.tolist(),'triangles':np.asarray(f).tolist(),'cook_readback':readback,'transform_finger':list(map(list,xf)),'material_path':str(material.GetPath()) if material else None}
            self.records[label]={'parts':parts,'rotation_CAD_to_finger':rotation.tolist(),'translation_finger_m':t,'body_source_facets_CAD_mm':source.tolist(),'body_vertices_CAD_mm':raw.tolist(),'head':{'center_finger_m':center,'radius_m':radius,'height_m':height,'axis':'Y','sides':32}}
        c=self.protocol['query_control'];cube=UsdGeom.Cube.Define(stage,c['path']);cube.CreateSizeAttr(c['size_m']);cube.AddTranslateOp().Set(Gf.Vec3d(*c['center_world_m']));UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        save(output/'exposed_geometry.json',{'config':self.cfg,'tips':self.records,'scope':'Exposed body only; buried boss omitted/attachment void filled by user authorization'})
        install(scene,self.reference,output,self.protocol)

    def audit(self,stage,output,cooked=None):
        result=stock.audit(stage,output)
        for label,finger in result['fingers'].items():
            for c in finger['colliders']:
                c['is_head']=c['path']==self.records.get(label,{}).get('parts',{}).get('head',{}).get('path')
                c['role']='body' if c['is_pad'] else 'head' if c['is_head'] else 'white'
                if c['role'] in ('body','head'):
                    authored=self.records[label]['parts'][c['role']]
                    points=np.asarray(authored['vertices_finger_m'])
                    expected={'points_finger_m':points,'bounds_finger_m':np.asarray([points.min(axis=0),points.max(axis=0)])}
                    for key,value in expected.items():
                        actual=np.asarray(c[key])
                        if actual.shape!=value.shape or not np.isfinite(actual).all() or np.max(abs(actual-value))>self.cfg['visual_registration_readback_m']:
                            raise RuntimeError('Composed exposed collider differs from authored geometry: '+key)
                    c['triangle_indices']=authored['triangles']
                    c['reference_surface_kind']='fixed_authored_convex_reference'
            original=[c for c in self.stock_before['fingers'][label]['colliders'] if not c['is_pad']]
            current=[c for c in finger['colliders'] if not c['is_pad'] and not c['is_head']]
            if len(current)!=len(original):raise RuntimeError('Stock white inventory changed')
            for actual,old in zip(current,original):
                expected={**old,'is_head':False,'role':'white'}
                if set(actual)!=set(expected):raise RuntimeError('White metadata fields changed')
                for key,value in actual.items():
                    if key in ('points_finger_m','bounds_finger_m'):
                        if np.asarray(value).shape!=np.asarray(expected[key]).shape or np.max(abs(np.asarray(value)-expected[key]))>self.cfg['white_geometry_readback_m']:raise RuntimeError('Stock white geometry changed')
                    elif value!=expected[key]:raise RuntimeError('Stock white metadata/material changed: '+key)
        save(output,result);return result

    def fixture_center(self,relative,old):
        from pxr import Gf
        z=self.cfg['metal_distal_finger_z_m']+self.cfg['coupon_proximal_beyond_metal_m']+.0048
        centers=[relative[k].Transform(Gf.Vec3d(0,0,z))[2] for k in ('left','right')]
        if abs(centers[0]-centers[1])>2e-6:raise RuntimeError('Finger-to-hand fixed Z disagreement')
        center=[self.cfg['reserved_hand_x_offset_m'] if self.phase=='R' else 0.,0.,sum(centers)/2]
        self.fixture={'center_finger_z_m':z,'center_hand_m':center,'finger_to_hand':{k:list(map(list,v)) for k,v in relative.items()},'metal_distal_finger_z_m':self.cfg['metal_distal_finger_z_m']}
        return np.asarray(center)

    def check_fixture(self,low,high,coupon_lo,coupon_hi):
        body_lo=coupon_lo[2];body_hi=body_lo+.0096
        overlap=min(high[2],body_hi)-max(low[2],body_lo)
        self.fixture['body_side_overlap_m']=float(overlap)
        if high[0]<=low[0] or overlap<self.cfg['minimum_body_side_overlap_m']:raise RuntimeError('Declared partial body-side overlap failed')

    def initial(self,context,properties,geometry,center):
        from query_geometry import capture
        from pxr import UsdGeom,Gf
        from isaaclab.sim import get_current_stage
        stage=get_current_stage()
        for label,tip in self.records.items():
            parent=stock.BODIES[label];visual=UsdGeom.Cylinder(stage.GetPrimAtPath(parent+'/UpdatedTipFastenerVisual/Head'))
            xf=visual.ComputeLocalToWorldTransform(0)*UsdGeom.Xformable(stage.GetPrimAtPath(parent)).ComputeLocalToWorldTransform(0).GetInverse()
            body_visual=UsdGeom.Xformable(stage.GetPrimAtPath(parent+'/UpdatedTipSTLVisual/Mesh'))
            body_xf=body_visual.ComputeLocalToWorldTransform(0)*UsdGeom.Xformable(stage.GetPrimAtPath(parent)).ComputeLocalToWorldTransform(0).GetInverse()
            actual=np.asarray([list(body_xf.Transform(Gf.Vec3d(*v))) for v in tip['body_vertices_CAD_mm']])
            if np.max(abs(actual-tip['parts']['body']['vertices_finger_m']))>self.cfg['visual_registration_readback_m']:raise RuntimeError('Body collider differs from corrected visual registration')
            tip['actual_visual_matrix_CAD_mm_to_finger_m']=list(map(list,body_xf))
            if visual.GetAxisAttr().Get()!='Y' or abs(visual.GetRadiusAttr().Get()-tip['head']['radius_m'])>1e-10 or abs(visual.GetHeightAttr().Get()-tip['head']['height_m'])>1e-10 or np.max(abs(np.asarray(xf.ExtractTranslation())-tip['head']['center_finger_m']))>1e-9:raise RuntimeError('Live visual head differs from pinned1773 placement')
        save(self.output/'exposed_geometry.json',{'config':self.cfg,'tips':self.records,'scope':'Exposed body only; buried boss omitted/attachment void filled by user authorization'})
        if properties!=self.reference['robot_properties']:raise RuntimeError('Strict frozen1754 physical properties differ')
        self.cooked=capture(self,context,self.phase=='G')
        if self.phase!='G':
            approved=json.loads(self.approved.read_text())
            expected=approved.get('cooked_hashes')
            if expected!=self.cooked['canonical_sha256']:raise RuntimeError('D/R cook differs from independently approved G')
        else:
            view=context['robot'].root_physx_view
            terminal={key:getattr(view,method)().cpu().numpy().tolist() for key,method in (('masses','get_masses'),('inertias','get_inertias'),('coms','get_coms'),('stiffnesses','get_dof_stiffnesses'),('dampings','get_dof_dampings'),('effort_limits','get_dof_max_forces'))}
            save(self.output/'G_metadata.json',{'initial_robot_properties':properties,'terminal_robot_properties':terminal,'fixture_frames':self.fixture,'cooked_hashes':self.cooked['canonical_sha256'],'model_config_sha256':sha(HERE/'model_config.json')})
            self.audit(stage,self.output/'geometry_terminal.json')
            if terminal!=properties:raise RuntimeError('G property drift')
            save(self.output/'exposed_G_complete.json',{'capture_completed':True,'independent_audit_required':True,'measured_contact_steps':0})

    def metadata(self):
        return {'case':self.phase+'_exposed','stage':self.phase,'model':'one source-body hull plus32-sided outside head','fixture_frames':self.fixture,'exposed_geometry_file':'exposed_geometry.json','cooked_hashes':self.cooked['canonical_sha256'],'stock_collision_unchanged':False,'only_pad_and_head_collision_changed':True,
            'geometry_audit_sha256':sha(self.approved),'side_authorization_sha256':sha(self.side_authorization_path),'global_G_passed':False,'authorized_scope':'Lateral-qualified flat inward-face normal contact only; no global fidelity or grasp claim'}

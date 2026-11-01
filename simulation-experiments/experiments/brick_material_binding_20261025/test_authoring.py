"""Queued pure-USD authoring test; no Kit, simulation or effective-material claim."""
import argparse,hashlib,json,os
from pathlib import Path
if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Run the frozen schema test through default Pueue')
from pxr import Gf,Sdf,Usd,UsdGeom,UsdPhysics,UsdShade
from materials import bind_declared_materials,COEFFICIENTS,DECLARED


def fixture():
    stage=Usd.Stage.CreateInMemory();visual=UsdShade.Material.Define(stage,'/Visual')
    for name in ('Brick','Other'):
        root=UsdGeom.Xform.Define(stage,'/'+name);root.AddTranslateOp().Set(Gf.Vec3d(.1,.2,.3));UsdPhysics.RigidBodyAPI.Apply(root.GetPrim())
        mass=UsdPhysics.MassAPI.Apply(root.GetPrim());mass.CreateMassAttr(.00216);mass.CreateDiagonalInertiaAttr(Gf.Vec3f(1e-7,2e-7,3e-7));mass.CreateCenterOfMassAttr(Gf.Vec3f(0,0,.0048))
        for collider,values in DECLARED.items():
            cube=UsdGeom.Cube.Define(stage,'/'+name+'/'+collider);cube.CreateSizeAttr(1.)
            cube.AddScaleOp().Set(Gf.Vec3f(.032,.016,.0096 if collider=='BodyCollider' else .0017));cube.AddTranslateOp().Set(Gf.Vec3d(0,0,.0048 if collider=='BodyCollider' else .01045))
            UsdPhysics.CollisionAPI.Apply(cube.GetPrim()).CreateCollisionEnabledAttr(True);UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(visual)
            for attr,value in zip(COEFFICIENTS,values):cube.GetPrim().CreateAttribute(attr,Sdf.ValueTypeNames.Float).Set(value)
    return stage


def preserved(stage):
    return {str(p.GetPath()):{'type':p.GetTypeName(),'apis':list(p.GetAppliedSchemas()),
        'attrs':{a.GetName():str(a.Get()) for a in p.GetAttributes() if a.HasAuthoredValueOpinion()},
        'rels':{r.GetName():list(map(str,r.GetTargets())) for r in p.GetRelationships() if r.GetName()!='material:binding:physics'}} for p in stage.Traverse()}


def physics_values(stage):
    for name in DECLARED:
        collider=stage.GetPrimAtPath('/Brick/'+name);material,_=UsdShade.MaterialBindingAPI(collider).ComputeBoundMaterial('physics')
        assert material and material.GetPrim().HasAPI(UsdPhysics.MaterialAPI)
        assert str(material.GetPath())=='/Brick/DeclaredContactMaterials/'+('Body' if name=='BodyCollider' else 'Top')
        for key in COEFFICIENTS:assert material.GetPrim().GetAttribute(key).Get()==collider.GetAttribute(key).Get()
        preview,_=UsdShade.MaterialBindingAPI(collider).ComputeBoundMaterial();assert str(preview.GetPath())=='/Visual'


def conflict(stage,inherited):
    material=UsdShade.Material.Define(stage,'/Existing');UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    prim=stage.GetPrimAtPath('/Brick' if inherited else '/Brick/BodyCollider')
    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material,UsdShade.Tokens.strongerThanDescendants,'physics')


def main():
    parser=argparse.ArgumentParser(allow_abbrev=False);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    protocol=json.loads(Path(__file__).with_name('protocol.json').read_text());assert protocol['execution_authorized'] is True
    assert DECLARED=={name:tuple(values[key] for key in ('static_friction','dynamic_friction','restitution')) for name,values in protocol['existing_declared_coefficients'].items()}
    assert COEFFICIENTS==('physics:staticFriction','physics:dynamicFriction','physics:restitution')
    for path,digest in protocol['source_pins'].items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
    stage=fixture();before=preserved(stage);report=bind_declared_materials(stage,'/Brick',pre_initialization=True);after=preserved(stage)
    assert all(after[path]==values for path,values in before.items());assert set(after)-set(before)=={'/Brick/DeclaredContactMaterials','/Brick/DeclaredContactMaterials/Body','/Brick/DeclaredContactMaterials/Top'}
    physics_values(stage);assert stage.GetRootLayer().Export(str(args.output/'corrected.usda'));physics_values(Usd.Stage.Open(str(args.output/'corrected.usda')))
    cases=[('missing initialization flag',lambda s:None,False),('missing collider',lambda s:s.RemovePrim('/Brick/TopCollider'),True),
        ('disabled collider',lambda s:UsdPhysics.CollisionAPI(s.GetPrimAtPath('/Brick/BodyCollider')).GetCollisionEnabledAttr().Set(False),True),
        ('missing declared attribute',lambda s:s.GetPrimAtPath('/Brick/TopCollider').RemoveProperty(COEFFICIENTS[1]),True),
        ('unexpected coefficient',lambda s:s.GetPrimAtPath('/Brick/BodyCollider').GetAttribute(COEFFICIENTS[1]).Set(.6),True),
        ('conflicting direct physics binding',lambda s:conflict(s,False),True),('conflicting inherited physics binding',lambda s:conflict(s,True),True),
        ('conflicting reserved material path',lambda s:UsdGeom.Scope.Define(s,'/Brick/DeclaredContactMaterials'),True)]
    results={}
    for name,alter,flag in cases:
        bad=fixture();alter(bad);unchanged=bad.GetRootLayer().ExportToString()
        try:bind_declared_materials(bad,'/Brick',pre_initialization=flag)
        except ValueError:pass
        else:raise AssertionError('Unexpected acceptance: '+name)
        assert bad.GetRootLayer().ExportToString()==unchanged;results[name]=True
    assert list(results)==protocol['negative_cases']
    payload={'schema_authoring_passed':True,'runtime_coefficients_verified':False,'retention_claim':False,'positive_preservation':True,'reload_resolution':True,'negative_cases':results,'authoring':report}
    (args.output/'report.json').write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n');print(json.dumps(payload))


if __name__=='__main__':main()

"""Opt-in pre-init USD binding of the brick's existing declared coefficients."""
import math
import struct
from pxr import Sdf,UsdGeom,UsdPhysics,UsdShade

COEFFICIENTS=('physics:staticFriction','physics:dynamicFriction','physics:restitution')
DECLARED={'BodyCollider':(.5,.4,.1),'TopCollider':(1.,.8,.2)}


def _float32(value):return struct.unpack('f',struct.pack('f',value))[0]


def bind_declared_materials(stage,brick_root_path,*,pre_initialization=False):
    """Author only two physics-purpose bindings, never runtime/contact changes.

    The caller must explicitly assert pre-initialization. USD alone cannot
    establish whether a separate physics engine has initialized this stage.
    """
    if pre_initialization is not True:raise ValueError('Explicit pre-initialization assertion required')
    path=Sdf.Path(brick_root_path)
    if not path.IsAbsolutePath() or not path.IsPrimPath() or str(path)=='/' or str(path)!=brick_root_path:raise ValueError('One exact absolute brick prim path required')
    root=stage.GetPrimAtPath(path)
    if not root or root.IsInstanceProxy() or not root.HasAPI(UsdPhysics.RigidBodyAPI):raise ValueError('Missing or uneditable rigid brick root')
    namespace=path.AppendChild('DeclaredContactMaterials')
    if stage.GetPrimAtPath(namespace):raise ValueError('Reserved material namespace is occupied')
    targets={}
    for name,expected in DECLARED.items():
        prim=stage.GetPrimAtPath(path.AppendChild(name));collision=UsdPhysics.CollisionAPI(prim)
        if not prim or prim.IsInstanceProxy() or not prim.IsA(UsdGeom.Cube) or not prim.HasAPI(UsdPhysics.CollisionAPI) or collision.GetCollisionEnabledAttr().Get() is not True:raise ValueError('Expected enabled editable Cube: '+name)
        values=[]
        for attr_name,value in zip(COEFFICIENTS,expected):
            attr=prim.GetAttribute(attr_name)
            if not attr or attr.GetTypeName()!=Sdf.ValueTypeNames.Float or not attr.HasAuthoredValueOpinion() or attr.GetTimeSamples():raise ValueError('Missing/static-float declaration required: '+attr_name)
            actual=attr.Get()
            if not isinstance(actual,(int,float)) or not math.isfinite(actual) or actual!=_float32(value):raise ValueError('Unexpected declared coefficient: '+attr_name)
            values.append(actual)
        material,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
        if material and material.GetPrim().HasAPI(UsdPhysics.MaterialAPI):raise ValueError('Existing effective physics material')
        ancestor=prim
        while ancestor and not ancestor.IsPseudoRoot():
            for rel in ancestor.GetRelationships():
                name_tokens=rel.GetName().split(':')
                if name_tokens[:2]!=['material','binding']:continue
                if 'physics' in name_tokens[2:]:raise ValueError('Existing direct/inherited physics binding')
                if ancestor!=prim and UsdShade.MaterialBindingAPI.GetMaterialBindingStrength(rel)==UsdShade.Tokens.strongerThanDescendants:raise ValueError('Stronger ancestor material binding')
            ancestor=ancestor.GetParent()
        targets[name]=(prim,values)
    layer=stage.GetEditTarget().GetLayer();backup=layer.ExportToString();records={}
    try:
        UsdGeom.Scope.Define(stage,namespace)
        for name,(prim,values) in targets.items():
            material=UsdShade.Material.Define(stage,namespace.AppendChild('Body' if name=='BodyCollider' else 'Top'))
            api=UsdPhysics.MaterialAPI.Apply(material.GetPrim())
            for method,value in zip(('CreateStaticFrictionAttr','CreateDynamicFrictionAttr','CreateRestitutionAttr'),values):getattr(api,method)(value)
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material,materialPurpose='physics')
            resolved,_=UsdShade.MaterialBindingAPI(prim).ComputeBoundMaterial('physics')
            if not resolved or resolved.GetPath()!=material.GetPath() or not resolved.GetPrim().HasAPI(UsdPhysics.MaterialAPI):raise ValueError('Physics-purpose binding did not resolve to the new material')
            records[name]={'collider_path':str(prim.GetPath()),'material_path':str(material.GetPath()),'declared_coefficients':values}
    except Exception:
        layer.ImportFromString(backup)
        raise
    return {'scope':'USD_SCHEMA_AUTHORING_ONLY','brick_root':brick_root_path,'pre_initialization_asserted':True,
        'targets':records,'runtime_coefficients_verified':False,'retention_claim':False}

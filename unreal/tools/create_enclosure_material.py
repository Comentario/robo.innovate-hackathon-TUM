"""Editor-only smooth service-cover transparency; no production simulation here."""
import unreal
edit=unreal.MaterialEditingLibrary
path='/Game/Materials/M_FactoryEnclosureFade'
material=unreal.load_asset(path)
if material is None:
    material=unreal.AssetToolsHelpers.get_asset_tools().create_asset('M_FactoryEnclosureFade','/Game/Materials',unreal.Material,unreal.MaterialFactoryNew())
assert material
edit.delete_all_material_expressions(material)
base=edit.create_material_expression(material,unreal.MaterialExpressionVectorParameter,-650,0)
base.set_editor_property('parameter_name','BaseColor');base.set_editor_property('default_value',unreal.LinearColor(.5,.5,.5,1))
texture=edit.create_material_expression(material,unreal.MaterialExpressionTextureSampleParameter2D,-650,180)
texture.set_editor_property('parameter_name','BaseTexture');texture.set_editor_property('texture',unreal.load_asset('/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture'))
multiply=edit.create_material_expression(material,unreal.MaterialExpressionMultiply,-320,0)
edit.connect_material_expressions(base,'',multiply,'A');edit.connect_material_expressions(texture,'RGB',multiply,'B');edit.connect_material_property(multiply,'',unreal.MaterialProperty.MP_BASE_COLOR)
for name,value,prop,y in [('Roughness',.48,unreal.MaterialProperty.MP_ROUGHNESS,400),('Metallic',0.,unreal.MaterialProperty.MP_METALLIC,550),('Coverage',1.,unreal.MaterialProperty.MP_OPACITY,700)]:
    node=edit.create_material_expression(material,unreal.MaterialExpressionScalarParameter,-320,y)
    node.set_editor_property('parameter_name',name);node.set_editor_property('default_value',value);edit.connect_material_property(node,'',prop)
material.set_editor_property('blend_mode',unreal.BlendMode.BLEND_TRANSLUCENT)
material.set_editor_property('translucency_lighting_mode',unreal.TranslucencyLightingMode.TLM_SURFACE)
material.set_editor_property('two_sided',True);material.set_editor_property('used_with_instanced_static_meshes',True)
fill=edit.create_material_expression(material,unreal.MaterialExpressionScalarParameter,-650,850)
fill.set_editor_property('parameter_name','EnclosureFill');fill.set_editor_property('default_value',.6)
light=edit.create_material_expression(material,unreal.MaterialExpressionMultiply,-320,850)
edit.connect_material_expressions(multiply,'',light,'A');edit.connect_material_expressions(fill,'',light,'B');edit.connect_material_property(light,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
edit.recompile_material(material);assert unreal.EditorAssetLibrary.save_loaded_asset(material)
unreal.log('Source enclosure material ready: smooth opacity, Coverage=1 closed; Coverage=.28 focused cutaway.')

"""Editor-only asset authoring; no production simulation runs in Python."""
import unreal

path='/Game/Materials'
unreal.EditorAssetLibrary.make_directory(path)
asset_path=path+'/M_FactorySurface'
material=unreal.load_asset(asset_path)
if material is None:
    material=unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        'M_FactorySurface',path,unreal.Material,unreal.MaterialFactoryNew())
    edit=unreal.MaterialEditingLibrary
    base=edit.create_material_expression(material,unreal.MaterialExpressionVectorParameter,-650,0)
    base.set_editor_property('parameter_name','BaseColor')
    base.set_editor_property('default_value',unreal.LinearColor(.5,.5,.5,1))
    texture=edit.create_material_expression(material,unreal.MaterialExpressionTextureSampleParameter2D,-650,180)
    texture.set_editor_property('parameter_name','BaseTexture')
    texture.set_editor_property('texture',unreal.load_asset('/Engine/EngineResources/WhiteSquareTexture.WhiteSquareTexture'))
    multiply=edit.create_material_expression(material,unreal.MaterialExpressionMultiply,-320,0)
    edit.connect_material_expressions(base,'',multiply,'A')
    edit.connect_material_expressions(texture,'RGB',multiply,'B')
    edit.connect_material_property(multiply,'',unreal.MaterialProperty.MP_BASE_COLOR)
    for name,value,prop,y in [('Roughness',.48,unreal.MaterialProperty.MP_ROUGHNESS,400),
                              ('Metallic',0.,unreal.MaterialProperty.MP_METALLIC,550)]:
        node=edit.create_material_expression(material,unreal.MaterialExpressionScalarParameter,-320,y)
        node.set_editor_property('parameter_name',name);node.set_editor_property('default_value',value)
        edit.connect_material_property(node,'',prop)
material.set_editor_property('used_with_instanced_static_meshes',True)
unreal.MaterialEditingLibrary.recompile_material(material)
unreal.EditorAssetLibrary.save_loaded_asset(material)
unreal.log('Brickflow native surface material ready. Runtime instances use C++ parameters.')

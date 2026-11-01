"""Unreal Editor Python bootstrap. Set BRICKFLOW_USD to an exported USD path.

Requires Epic's installed Linux editor and USDImporter. Not executed until that
editor is installed; the USD itself is independently verified in Blender.
"""
import os
from pathlib import Path

import unreal

source = Path(os.environ['BRICKFLOW_USD']).resolve()
if not source.is_file():
    raise FileNotFoundError(source)
world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
stage = actors.spawn_actor_from_class(unreal.UsdStageActor, unreal.Vector(0, 0, 0))
stage.set_actor_label('Brickflow · recorded factory state')
stage.set_root_layer(str(source))
if not unreal.EditorLoadingAndSavingUtils.save_map(world, '/Game/Brickflow'):
    raise RuntimeError('Unable to save Brickflow level')
unreal.EditorLoadingAndSavingUtils.save_dirty_packages(True, True)
unreal.log('Brickflow USD stage opened. Verify units, material fidelity and camera before Movie Render Queue.')

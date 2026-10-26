"""Run inside Blender with a prepared .blend to export a portable Unreal USD stage."""
import argparse
import json
import sys
from pathlib import Path

import bpy

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
args.output.parent.mkdir(parents=True, exist_ok=True)
bpy.context.scene.unit_settings.system = 'METRIC'
bpy.context.scene.unit_settings.scale_length = 1
result = bpy.ops.wm.usd_export(
    filepath=str(args.output.resolve()), check_existing=False,
    export_materials=True, export_textures=True, relative_paths=True,
    use_instancing=True, export_animation=False, generate_preview_surface=True,
)
if 'FINISHED' not in result:
    raise RuntimeError('USD export did not complete')
args.output.with_suffix('.evidence.json').write_text(json.dumps({
    'source_evidence': json.loads(bpy.context.scene.get('evidence', '{}')),
    'source_blend': Path(bpy.data.filepath).name,
    'objects': len(bpy.context.scene.objects),
    'type': 'Frozen replay state with studio lighting',
    'limitations': 'USD preview materials approximate Blender shaders. Procedural brick bump requires recreation in Unreal. Unreal import has not yet been verified.',
}, indent=2))
print('Unreal USD stage exported:', args.output)

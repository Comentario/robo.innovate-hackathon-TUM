"""Blender 4.5+ snapshot renderer. Run with blender -b --python ... -- --help."""
import argparse
import base64
import gzip
import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def matrix(values):
    # Three.js serializes matrices by column; Blender accepts rows.
    return Matrix([values[i::4] for i in range(4)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--samples', type=int, default=128)
    parser.add_argument('--cpu', action='store_true', help='Explicit local smoke test only')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else [])
    started = time.monotonic()
    data = json.loads(gzip.decompress(args.scene.read_bytes()))
    if data['schema'] != 'brickflow.render-snapshot.v1':
        raise ValueError('Unsupported render snapshot')
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    devices = []
    if not args.cpu:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        prefs.compute_device_type = 'OPTIX'
        prefs.get_devices()
        for device in prefs.devices:
            device.use = device.type == 'OPTIX'
            if device.use:
                devices.append(device.name)
        if not devices:
            raise RuntimeError('No OptiX GPU detected; refusing an accidental CPU render')
        scene.cycles.device = 'GPU'
    # Rigid coordinate conversion preserves the complete model at metre scale.
    basis = Matrix.Rotation(math.pi / 2, 4, 'X')
    material_cache = {}

    def material(key, tint):
        cache_key = (key, tuple(tint))
        if cache_key in material_cache:
            return material_cache[cache_key]
        source = data['materials'][key]
        mat = bpy.data.materials.new('Factory material')
        mat.use_nodes = True
        shader = mat.node_tree.nodes.get('Principled BSDF')
        shader.inputs['Base Color'].default_value = (*[a*b for a, b in zip(source['color'], tint)], 1)
        shader.inputs['Roughness'].default_value = source['roughness']
        shader.inputs['Metallic'].default_value = source['metalness']
        shader.inputs['Alpha'].default_value = source['opacity']
        if source.get('texture'):
            raw = base64.b64decode(source['texture'].split(',', 1)[1])
            # Packed image: no external texture dependency in the resulting blend.
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.png') as temp:
                temp.write(raw); temp.flush()
                image = bpy.data.images.load(temp.name)
                image.pack()
            texture = mat.node_tree.nodes.new('ShaderNodeTexImage')
            texture.image = image
            multiply = mat.node_tree.nodes.new('ShaderNodeMixRGB')
            multiply.blend_type = 'MULTIPLY'
            multiply.inputs[0].default_value = 1
            multiply.inputs[2].default_value = shader.inputs['Base Color'].default_value
            mat.node_tree.links.new(texture.outputs['Color'], multiply.inputs[1])
            mat.node_tree.links.new(multiply.outputs[0], shader.inputs['Base Color'])
        material_cache[cache_key] = mat
        return mat

    meshes = {}
    for number, item in enumerate(data['objects']):
        tint = item.get('color', [1, 1, 1])
        key = (item['geometry'], tuple(item['materials']), tuple(tint))
        if key not in meshes:
            g = data['geometries'][item['geometry']]
            vertices = list(zip(*[iter(g['positions'])]*3))
            indices = g['indices'] if g['indices'] is not None else list(range(len(vertices)))
            if len(indices) % 3:
                raise ValueError('Only triangle meshes are supported')
            mesh = bpy.data.meshes.new('Factory geometry')
            mesh.from_pydata(vertices, [], list(zip(*[iter(indices)]*3)))
            for mat_id in item['materials']:
                mesh.materials.append(material(mat_id, tint))
            for group in g['groups']:
                for face in range(group['start']//3, (group['start']+group['count'])//3):
                    mesh.polygons[face].material_index = (
                        group['materialIndex'] if len(item['materials']) > 1 else 0)
            if g['uv']:
                uv = mesh.uv_layers.new()
                for loop in mesh.loops:
                    i = loop.vertex_index*2
                    uv.data[loop.index].uv = g['uv'][i:i+2]
            mesh.update()
            if g.get('normals'):
                for polygon in mesh.polygons:
                    polygon.use_smooth = True
                mesh.normals_split_custom_set_from_vertices(list(zip(*[iter(g['normals'])]*3)))
            meshes[key] = mesh
        obj = bpy.data.objects.new(f'Factory {number}', meshes[key])
        scene.collection.objects.link(obj)
        obj.matrix_world = basis @ matrix(item['matrix'])

    camera_data = bpy.data.cameras.new('Replay camera')
    camera = bpy.data.objects.new('Replay camera', camera_data)
    scene.collection.objects.link(camera)
    camera.matrix_world = basis @ matrix(data['camera']['matrix'])
    # Three's fov is vertical; Blender's horizontal sensor fit needs conversion.
    aspect = 16/9
    camera_data.angle = 2*math.atan(math.tan(math.radians(data['camera']['fov'])/2)*aspect)
    scene.camera = camera
    scene.world = bpy.data.worlds.new('Studio world')
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get('Background')
    background.inputs['Color'].default_value = (.12, .16, .21, 1)
    background.inputs['Strength'].default_value = .35
    for name, position, power, size in [
        ('Key softbox', (15, -15, 38), 140000, 35),
        ('Fill softbox', (30, 25, 24), 90000, 28),
        ('Rim softbox', (-15, 10, 25), 100000, 20),
    ]:
        light = bpy.data.lights.new(name, 'AREA')
        light.energy = power; light.shape = 'DISK'; light.size = size
        obj = bpy.data.objects.new(name, light); scene.collection.objects.link(obj)
        obj.location = position
        obj.rotation_euler = (Vector((20, 0, 0))-obj.location).to_track_quat('-Z', 'Y').to_euler()
    scene.view_settings.view_transform = 'AgX'
    scene.render.resolution_x = args.width
    scene.render.resolution_y = round(args.width/aspect)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.output.resolve())
    scene['evidence'] = json.dumps(data['evidence'])
    bpy.ops.wm.save_as_mainfile(filepath=str(args.output.with_suffix('.blend').resolve()))
    bpy.ops.render.render(write_still=True)
    args.output.with_suffix('.receipt.json').write_text(json.dumps({
        'evidence': data['evidence'], 'gpu': devices, 'cpu_smoke_test': args.cpu,
        'seconds': time.monotonic()-started, 'samples': args.samples,
        'width': args.width, 'objects': len(data['objects']),
        'limitations': 'Frozen production state; studio lighting; not physical validation.',
    }, indent=2))


if __name__ == '__main__':
    main()

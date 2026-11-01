"""Validate a rendered .blend against sampled replay matrices. Run inside Blender."""
import argparse
import gzip
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--scene', type=Path, required=True)
parser.add_argument('--motion', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args(sys.argv[sys.argv.index('--')+1:])
snapshot = json.loads(gzip.decompress(args.scene.read_bytes()))
motion = json.loads(gzip.decompress(args.motion.read_bytes()))
expected = {i:item for i,item in enumerate(snapshot['objects'])}
affected = sorted({c['index'] for f in motion['frames'] for c in f['changes']})
basis = Matrix.Rotation(math.pi/2,4,'X')
checked = 0
max_error = 0
for frame in [{'frame':1,'changes':[]}, *motion['frames']]:
    expected.update({c['index']:c for c in frame['changes']})
    bpy.context.scene.frame_set(frame['frame'])
    # Check every changed object and a stable spread of held transforms.
    indices = set(c['index'] for c in frame['changes']) | set(affected[::max(1,len(affected)//50)])
    for i in indices:
        item = expected[i]
        matrix = basis @ Matrix([item['matrix'][j::4] for j in range(4)])
        obj = bpy.context.scene.objects[f'Factory {i}']
        error = max(abs(obj.matrix_world[r][c]-matrix[r][c]) for r in range(4) for c in range(4))
        max_error = max(max_error,error)
        if error > .0001 or obj.hide_render != item.get('hidden',False):
            raise AssertionError(f'Motion mismatch frame={frame["frame"]} object={i} error={error}')
        checked += 1
args.output.write_text(json.dumps({'verified':True,'checks':checked,
    'max_matrix_error':max_error,'frames':len(motion['frames'])+1,
    'affected_objects':len(affected),'fps':motion['fps'],'rate':motion['rate'],
    'evidence':'Numerical agreement with synthetic replay samples; not independent physical validation.'},indent=2))
print('Replay motion verified:', checked, 'checks; max matrix error', max_error)

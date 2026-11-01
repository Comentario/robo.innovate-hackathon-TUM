"""Bounded queued mount-side verification and matched-view panels."""
import argparse
import copy
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def read(path):
    return json.loads(path.read_text())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('before', 'after', 'output'):
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    assert os.environ.get('ROBO_PUEUE_JOB') == '1'
    a.output.mkdir(parents=True, exist_ok=True)
    old, new = [read(d/'manifest.json') for d in (a.before, a.after)]
    layouts = [copy.deepcopy(m['final_layout']['layout_estimates']) for m in (old, new)]
    layouts[1]['wrist_camera'].pop('mount_side_correction')
    checks = {'layout_except_mount_unchanged': layouts[0] == layouts[1]}
    for key in ('geometry', 'applied_lighting_attributes', 'resolved_render_settings',
                'brick_count', 'native_connections', 'native_connected_parts', 'post_connection_physics_steps'):
        checks[key+'_unchanged'] = old[key] == new[key]
    checks['full_native_stack'] = (new['brick_count'], new['native_connections'], new['native_connected_parts']) == (300, 930, 301)
    checks['static_capture'] = new['all_capture_states_exactly_equal'] and new['post_connection_physics_steps'] == 0
    for key in ('requested_joint_positions_native_units', 'actual_joint_positions_native_units', 'hand_usd_pose_wxyz'):
        checks[key+'_unchanged'] = bool(np.allclose(old['robot_initialization'][key], new['robot_initialization'][key], atol=1e-6, rtol=0))
    for name in ('active_bricks.json',):
        checks[name+'_unchanged'] = read(a.before/'evaluation_truth'/name) == read(a.after/'evaluation_truth'/name)
    checks['source_states_unchanged'] = bool(np.array_equal(np.load(a.before/'evaluation_truth/active_root_states.npy'), np.load(a.after/'evaluation_truth/active_root_states.npy')))
    cams = [{c['id']: c for c in read(d/'evaluation_truth/cameras.json')} for d in (a.before, a.after)]
    for view in ('diagnostic_table_top', 'diagnostic_oblique'):
        for key in ('actual_eye_world_m', 'actual_quaternion_wxyz_opengl', 'intrinsics'):
            checks[view+'_'+key+'_unchanged'] = cams[0][view][key] == cams[1][view][key]
        ims = [Image.open(d/'images'/f'{view}.png').convert('RGB') for d in (a.before, a.after)]
        panel = Image.new('RGB', (ims[0].width*2, ims[0].height+32), 'white')
        draw = ImageDraw.Draw(panel)
        for i, (im, title) in enumerate(zip(ims, ('Before: inherited mount side', 'After: opposite hand flank'))):
            panel.paste(im, (im.width*i, 32))
            draw.text((im.width*i+12, 10), title, fill='black')
        panel.save(a.output/f'{view}_before_after.png')
    mount = read(a.after/'wrist_mount_side.json')
    checks['mount_transform_verified'] = all(c['position_error_m'] < 1e-4 and c['orientation_error_rad'] < 1e-3 for c in mount['components'])
    report = {'checks': checks, 'all_passed': all(checks.values()), 'mount': mount, 'before': str(a.before), 'after': str(a.after), 'scope': 'Visual mount-side correction only; no measured optical transform'}
    (a.output/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)
    assert report['all_passed']


if __name__ == '__main__':
    main()

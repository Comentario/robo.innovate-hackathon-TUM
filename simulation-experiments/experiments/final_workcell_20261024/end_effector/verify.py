"""Queued reference-corrected C920 and supplied fingertip visual checks."""
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
    added = layouts[1].pop('additional_wrist_camera')
    layouts[0].pop('additional_wrist_camera')
    layouts[1].pop('fingertip_visual')
    checks = {'layout_except_visual_c920_and_tips_unchanged': layouts[0] == layouts[1]}
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
        for i, (im, title) in enumerate(zip(ims, ('Before: inherited mount side', 'After: reference C920 and supplied fingertips'))):
            panel.paste(im, (im.width*i, 32))
            draw.text((im.width*i+12, 10), title, fill='black')
        panel.save(a.output/f'{view}_before_after.png')
    mount = read(a.after/'wrist_mount_side.json')
    checks['d435_mount_unchanged'] = read(a.before/'wrist_mount_side.json') == mount
    c920 = new['final_layout']['additional_wrist_visual']
    checks['c920_visual_only'] = c920['visual_only_audit_passed'] and not c920['optical_camera_activated']
    checks['two_wrist_housings'] = new['final_layout']['wrist_camera_config_count'] == 2
    checks['c920_centered_opposite'] = added['stand_center_hand_x_m'] < 0 and added['hinge_position_hand_m'][1] == 0
    checks['noncoplanar_body'] = 0 < c920['body_stand_angle_deg'] < 90
    checks['fascia_tilt_toward_grasp'] = c920['decorative_fascia_normal_hand'][0] > 0 and c920['decorative_fascia_normal_hand'][2] > 0
    tips = read(a.after/'updated_fingertips.json')
    checks['two_STL_instances'] = len(tips['instances']) == 2
    checks['only_old_pad_faces_removed'] = all(t['removed_stock_pad_faces'] == 262 and t['retained_white_finger_faces'] == 362 for t in tips['instances'])
    checks['tips_centered_and_distal_aligned'] = all(abs(t['bounds_finger_m'][0][0]+t['bounds_finger_m'][1][0]) < 1e-6 and abs(t['bounds_finger_m'][1][2]-.05389988) < 1e-6 for t in tips['instances'])
    checks['mount_transform_verified'] = all(c['position_error_m'] < 1e-4 and c['orientation_error_rad'] < 1e-3 for c in mount['components'])
    report = {'checks': checks, 'all_passed': all(checks.values()), 'mount': mount, 'before': str(a.before), 'after': str(a.after), 'scope': 'Reference-based C920 and fingertip visuals only; optical and new pad contact geometry uncalibrated'}
    (a.output/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)
    assert report['all_passed']


if __name__ == '__main__':
    main()

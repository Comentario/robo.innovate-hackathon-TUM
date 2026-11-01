#!/usr/bin/python3
"""Move to a saved upper pose on a smooth continuous arc, or perform an explicit small relative Z jog."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

HERE=Path(__file__).resolve().parent


def resolve_pose(catalog,identifier):
    text=str(identifier)
    if text.isdecimal():
        number=int(text)
        key=f'point_{number:02d}'
        if key not in catalog['points']:raise ValueError('Unknown numbered pose: '+text)
        return number,catalog['points'][key],False
    if text not in catalog.get('input_bricks',{}):
        raise ValueError('Unknown pose; use a numbered point or a_n_m_k (n=0..5, m=0..4, k=0..9)')
    from generate_stack import source_signature
    model=catalog['input_stack']
    if source_signature(catalog,model['config'])!=model['report']['source_signature']:
        raise ValueError('Input-stack anchors/configuration changed; regenerate the brick dictionary before using it')
    return text,catalog['input_bricks'][text],True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('point',help='Numbered pose 1..15, or a_n_m_k input-brick ID')
    parser.add_argument('--lift-mm',type=float,default=10,help='Legacy segmented-path lift; normal arc moves use motion_config.json')
    parser.add_argument('--clearance-z-mm',type=float,help='Explicit existing clearance height for a reviewed continuation')
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--grasp',action='store_true',help='Set the configured approach opening, move to the upper pose, then descend; leaves the hand open')
    parser.add_argument('--restore-orientation',action='store_true',help='Restore the taught orientation during high-clearance XY transfer')
    parser.add_argument('--vertical-tool',action='store_true',help='Temporarily remove target tilt while preserving saved tool-X heading')
    parser.add_argument('--z-offset-mm',type=float,default=0,help='Temporary base-Z offset; never writes the taught catalog')
    parser.add_argument('--relative-z-mm',type=float,help='Direct small Z jog from current pose, bounded to +/-2 mm')
    parser.add_argument('--route',help='Retired legacy option; rejected')
    parser.add_argument('--segmented',action='store_true',help='Retired legacy option; rejected')
    parser.add_argument('--time-scale',type=float,default=1,help='Slow a normal arc by this factor (1 to 4) for a constrained route')
    parser.add_argument('--input-layers-removed',type=int,default=0,help='Operator-declared count of completely removed upper layers, for generated input targets')
    args=parser.parse_args()
    if args.grasp and (args.relative_z_mm is not None or args.z_offset_mm!=0 or args.vertical_tool):
        parser.error('--grasp uses the saved reference and cannot be combined with temporary pose overrides')
    if not math.isfinite(args.time_scale) or not 1<=args.time_scale<=4:
        parser.error('--time-scale must be between 1 and 4')
    if not math.isfinite(args.z_offset_mm) or abs(args.z_offset_mm)>20:
        parser.error('--z-offset-mm must be finite and within +/-20 mm')
    if args.relative_z_mm is not None and (not math.isfinite(args.relative_z_mm) or abs(args.relative_z_mm)>2 or args.z_offset_mm!=0):
        parser.error('--relative-z-mm must be within +/-2 mm and cannot be combined with --z-offset-mm')
    catalog_bytes=(HERE/'positions.json').read_bytes()
    catalog=json.loads(catalog_bytes)
    motion_policy=json.loads((HERE/'motion_config.json').read_text())
    if args.route or args.clearance_z_mm is not None:
        parser.error('Legacy named/segmented routes are retired; clearance comes from motion_config.json')
    if args.segmented:
        parser.error('The legacy segmented controller has been retired; use the checked continuous path')
    if args.execute and not motion_policy.get('verified_joint_plans_enabled'):
        parser.error('Singularity-checked execution is disabled in motion_config.json; no command sent')
    try:
        args.point,point,is_input=resolve_pose(catalog,args.point)
    except ValueError as exc:parser.error(str(exc))
    if is_input and args.execute and args.input_layers_removed!=point['layer_from_top']-1:
        parser.error('Generated input target is not the declared exposed layer; verify removed upper layers before motion')
    result=subprocess.run([str(HERE/'read_pose')],capture_output=True,text=True,timeout=10)
    if result.returncode:
        print('STOP: read-only preflight failed: '+(result.stderr.strip() or result.stdout.strip()),file=sys.stderr)
        return result.returncode
    capture=json.loads(result.stdout)
    state=capture['state']
    if args.grasp:
        from arc_motion import run_arc
        from audit_kinematics import yaw_variant
        reference=point.get('grasp_reference',{}).get('O_T_EE')
        if reference is None:parser.error('This pose has no saved grasp reference')
        upper=point['O_T_EE']
        offset=[reference[12+i]-upper[12+i] for i in range(3)]
        if abs(offset[0])>1e-9 or abs(offset[1])>1e-9 or not -.020<=offset[2]<0:
            parser.error('Grasp reference must be a saved vertical descent of at most 20 mm')
        from gripper_width import command_width
        opening=command_width('approach',args.execute)
        if opening:return opening
        if args.execute:
            reread=subprocess.run([str(HERE/'read_pose')],capture_output=True,text=True,timeout=10)
            if reread.returncode:
                print('STOP after gripper opening: '+reread.stderr.strip(),file=sys.stderr);return reread.returncode
            capture=json.loads(reread.stdout)
        code=run_arc(args.point,upper,capture,catalog_bytes,point,args.execute,
                     dict(stage='grasp_upper_approach',time_scale=args.time_scale))
        if code:return code
        if not args.execute:
            print('Grasp reference XYZ m:',reference[12:15],'; descent is checked after reaching the upper pose')
            return 0
        fresh=subprocess.run([str(HERE/'read_pose')],capture_output=True,text=True,timeout=10)
        if fresh.returncode:
            print('STOP before grasp descent: '+fresh.stderr.strip(),file=sys.stderr);return fresh.returncode
        capture=json.loads(fresh.stdout);actual=capture['state']['O_T_EE']
        def rotation_error(pose):
            trace=sum(actual[c*4+r]*pose[c*4+r] for c in range(3) for r in range(3))
            return math.acos(max(-1,min(1,(trace-1)/2)))
        variants=[reference.copy()]
        if motion_policy['singularity_avoidance']['allow_yaw180_for_bricks'] and str(args.point)!='1':
            variants.append(yaw_variant(reference,180))
        target=min(variants,key=rotation_error)
        if math.dist(actual[12:15],upper[12:15])>.001 or rotation_error(target)>math.pi/180:
            print('STOP: upper grasp approach is outside the verified pose tolerance',file=sys.stderr);return 1
        print(f'Grasp descent: {-offset[2]*1000:.1f} mm to saved reference; configured approach opening verified',flush=True)
        return run_arc(args.point,target,capture,catalog_bytes,point,True,
                       dict(stage='grasp_descent',target_kind='grasp_reference',direct_saved_grasp=True,
                            saved_grasp_offset_base_m=offset,time_scale=args.time_scale))
    target=(state['O_T_EE'] if args.relative_z_mm is not None else point['O_T_EE']).copy()
    target[14]+=(args.relative_z_mm if args.relative_z_mm is not None else args.z_offset_mm)/1000
    if args.vertical_tool:
        if math.hypot(target[0],target[1])<.1:
            parser.error('Tool-X heading is undefined near vertical')
        yaw=math.atan2(target[1],target[0])
        c,s=math.cos(yaw),math.sin(yaw)
        # Right-handed frame: tool Z points down, tool X retains its XY heading.
        target[:12]=[c,s,0,0,s,-c,0,0,0,0,-1,0]
    if args.relative_z_mm is not None:
        trace=sum(state['O_T_EE'][c*4+r]*target[c*4+r] for c in range(3) for r in range(3))
        if math.acos(max(-1,min(1,(trace-1)/2)))>math.radians(2):
            parser.error('Direct jog reorientation is limited to 2 degrees; use a normal pose move')
    from arc_motion import run_arc
    return run_arc(args.point,target,capture,catalog_bytes,point,args.execute,
                   dict(z_offset_mm=args.z_offset_mm,relative_z_mm=args.relative_z_mm,vertical_tool=args.vertical_tool,time_scale=args.time_scale))


if __name__=='__main__':
    sys.exit(main())

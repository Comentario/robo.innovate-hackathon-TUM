#!/usr/bin/python3
"""Generate the deterministic 300-brick input grid. Never connects to the robot."""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

HERE=Path(__file__).resolve().parent
CATALOG=HERE/'positions.json'


def source_signature(catalog,config):
    anchors={name:{key:catalog['points'][name][key] for key in ('xyz_m','O_T_EE','tool_frames')}
             for name in config['anchor_indices']}
    value=dict(config=config,anchors=anchors)
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def local_xy(config,layer,ridge,brick):
    # Indices are one-based from the top. Ridge numbering follows the image.
    length=config['brick_center_pitch_m'];width=config['ridge_center_pitch_m']
    b=brick-1-(config['bricks_per_ridge']-1)/2
    r=ridge-1-(config['ridges_per_layer']-1)/2
    center=[(config['bricks_per_ridge']-1)*length/2,
            (config['ridges_per_layer']-1)*width/2]
    if (layer-1)%2==0:
        return [center[0]+b*length,center[1]+r*width]
    # A 90-degree layer rotation, with ridge numbering reversed so ridge 1
    # remains at the edge shown by #7/#6. The physical set rotates about center.
    return [center[0]+r*width,center[1]+b*length]


def pose(xyz,yaw):
    c,s=math.cos(yaw),math.sin(yaw)
    # Proper tool frame: tool Z down, no tilt, saved reference heading retained.
    return [c,s,0,0,s,-c,0,0,0,0,-1,0,*xyz,1]


def generate(catalog,config):
    if not config.get('operator_confirmed'):
        raise ValueError('Stack layout has not been confirmed by the operator')
    if (config['layers'],config['ridges_per_layer'],config['bricks_per_ridge'])!=(10,6,5):
        raise ValueError('This workcell model requires 10 layers, 6 ridges, 5 bricks')
    for key in ('brick_center_pitch_m','ridge_center_pitch_m','layer_height_m','grasp_offset_m'):
        if not math.isfinite(config[key]) or config[key]<=0:
            raise ValueError('Invalid positive dimension: '+key)
    points=catalog['points'];origin=points[config['origin_anchor']]['xyz_m']
    reference=points[config['orientation_anchor']]
    # Rigid planar yaw fit with #3 translation fixed exactly. No scale/shear fit.
    dot=cross=0.0
    for name,index in config['anchor_indices'].items():
        x,y=local_xy(config,**index);measured=points[name]['xyz_m']
        wx,wy=measured[0]-origin[0],measured[1]-origin[1]
        dot+=x*wx+y*wy;cross+=x*wy-y*wx
    if math.hypot(dot,cross)<1e-12:
        raise ValueError('Anchor layout cannot determine grid direction')
    angle=math.atan2(cross,dot);c,s=math.cos(angle),math.sin(angle)
    def world(xy):
        x,y=xy
        return [origin[0]+c*x-s*y,origin[1]+s*x+c*y]
    center=world([(config['bricks_per_ridge']-1)*config['brick_center_pitch_m']/2,
                  (config['ridges_per_layer']-1)*config['ridge_center_pitch_m']/2])
    top_z=points[config['height_anchor']]['xyz_m'][2]
    base_yaw=math.atan2(reference['O_T_EE'][1],reference['O_T_EE'][0])
    signature=source_signature(catalog,config);bricks={};layer_info=[];residuals={}
    for name,index in config['anchor_indices'].items():
        xy=world(local_xy(config,**index));z=top_z-(index['layer']-1)*config['layer_height_m']
        actual=points[name]['xyz_m']
        residuals[name]=dict(indices=index,predicted_xyz_m=xy+[z],taught_xyz_m=actual.copy(),
                             xy_residual_mm=math.dist(xy,actual[:2])*1000,
                             taught_minus_grid_z_mm=(actual[2]-z)*1000)
    for layer in range(1,config['layers']+1):
        relative_yaw=((layer-1)%2)*math.pi/2
        z=top_z-(layer-1)*config['layer_height_m']
        length_axis=[math.cos(angle+relative_yaw),math.sin(angle+relative_yaw),0]
        width_axis=[-length_axis[1],length_axis[0],0]
        members=[]
        for ridge in range(1,config['ridges_per_layer']+1):
            for brick in range(1,config['bricks_per_ridge']+1):
                n,m,k=ridge-1,brick-1,config['layers']-layer
                name=f'a_{n}_{m}_{k}'
                xyz=world(local_xy(config,layer,ridge,brick))+[z]
                upper=pose(xyz,base_yaw+relative_yaw)
                grasp_xyz=xyz.copy();grasp_xyz[2]-=config['grasp_offset_m']
                grasp=pose(grasp_xyz,base_yaw+relative_yaw)
                bricks[name]=dict(n=n,m=m,k=k,layer_index_from_bottom=k,
                    layer_from_top=layer,layer_from_bottom=config['layers']-layer+1,
                    ridge=ridge,brick_in_ridge=brick,layer_rotation_deg=relative_yaw*180/math.pi,
                    xyz_m=xyz,O_T_EE=upper,
                    grasp_reference=dict(xyz_m=grasp_xyz,O_T_EE=grasp,
                        offset_from_recorded_pose_base_m=[0,0,-config['grasp_offset_m']],motion_validated=False),
                    brick_axes_world=dict(length=length_axis.copy(),width=width_axis.copy(),up=[0,0,1]),
                    tool_frames=copy.deepcopy(reference['tool_frames']),
                    pose_source='deterministic_input_stack_model',
                    motion_to_pose_validated=False,grasp_physically_validated=False,
                    joint_configuration=None,
                    access_precondition=f'Layers 1 through {layer-1} must be removed' if layer>1 else 'Top layer',
                    note='Calculated configured-EE upper/grasp targets; joint angles, color and pick outcomes are not inferred.')
                members.append(name)
        centroid=[sum(bricks[name]['xyz_m'][i] for name in members)/len(members) for i in (0,1)]
        if math.dist(centroid,center)>1e-10:
            raise ValueError('Layer centers do not coincide')
        layer_info.append(dict(layer_from_top=layer,rotation_deg=relative_yaw*180/math.pi,
                               count=len(members),center_xy_m=centroid,upper_z_m=z,
                               grasp_z_m=z-config['grasp_offset_m']))
    if len(bricks)!=300 or len({tuple(p['xyz_m']) for p in bricks.values()})!=300:
        raise ValueError('Input grid does not contain 300 unique positions')
    if any(layer['count']!=30 for layer in layer_info):
        raise ValueError('Every layer must have 30 bricks')
    if bricks['a_0_0_9']['xyz_m']!=origin:
        raise ValueError('Top origin must exactly reproduce point #3 XYZ')
    dims=config['brick_dimensions_m']
    if config['brick_center_pitch_m']<dims['length']-1e-10 or config['ridge_center_pitch_m']<dims['width']-1e-10:
        raise ValueError('Bricks overlap within a layer')
    for upper,lower in zip(layer_info,layer_info[1:]):
        if abs(upper['upper_z_m']-lower['upper_z_m']-config['layer_height_m'])>1e-12:
            raise ValueError('Layer heights are inconsistent')
    for b in bricks.values():
        for matrix in (b['O_T_EE'],b['grasp_reference']['O_T_EE']):
            if any(not math.isfinite(v) for v in matrix):raise ValueError('Non-finite pose')
            if matrix[10]!=-1 or any(matrix[i]!=0 for i in (2,6,8,9)):
                raise ValueError('Generated tool must be vertical')
    report=dict(generator='teaching/generate_stack.py',source_signature=signature,
        brick_id_format='a_n_m_k; n=0..5, m=0..4, k=0..9 from bottom',
        source_anchor_brick_ids={name:f'a_{v["ridge"]-1}_{v["brick"]-1}_{config["layers"]-v["layer"]}'
                                 for name,v in config['anchor_indices'].items()},
        enumeration_order='Descending k (top down), ascending n, ascending m',
        generated_count=len(bricks),numbered_poses_retained=len(points),
        center_xy_m=center,length_axis_heading_deg=math.degrees(angle),
        length_axis_world=[c,s,0],ridge_axis_world=[-s,c,0],
        measured_anchor_residuals=residuals,layers=layer_info,
        max_xy_anchor_residual_mm=max(p['xy_residual_mm'] for p in residuals.values()),
        max_abs_z_anchor_residual_mm=max(abs(p['taught_minus_grid_z_mm']) for p in residuals.values()),
        short_edge_gap_m=config['brick_center_pitch_m']-dims['length'],
        gap_between_ridges_m=config['ridge_center_pitch_m']-dims['width'],
        layer_footprint_m=dict(length=5*dims['length'],width=5*config['ridge_center_pitch_m']+dims['width']),
        upper_xyz_bounds_m=dict(min=[min(p['xyz_m'][i] for p in bricks.values()) for i in range(3)],
                                max=[max(p['xyz_m'][i] for p in bricks.values()) for i in range(3)]),
        physical_validation='Not performed. Generated geometry is not proof of collision-free motion, grasping or separation.')
    return bricks,report


def render(catalog,config,bricks,report,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Polygon
    fig,axes=plt.subplots(1,2,figsize=(12,6),constrained_layout=True)
    dims=config['brick_dimensions_m']
    for layer,ax in zip((1,2),axes):
        for name,b in bricks.items():
            if b['layer_from_top']!=layer:continue
            x,y=[v*1000 for v in b['xyz_m'][:2]]
            u=b['brick_axes_world']['length'];v=b['brick_axes_world']['width']
            corners=[(x+sx*dims['length']*500*u[0]+sy*dims['width']*500*v[0],
                      y+sx*dims['length']*500*u[1]+sy*dims['width']*500*v[1])
                     for sx,sy in ((-1,-1),(1,-1),(1,1),(-1,1))]
            ax.add_patch(Polygon(corners,facecolor='#e0ecff' if layer==1 else '#ffe7cd',edgecolor='#52616f',linewidth=.8))
            ax.text(x,y,name,ha='center',va='center',fontsize=6,
                    rotation=(report['length_axis_heading_deg']+((layer-1)%2)*90)%180)
        for anchor,index in config['anchor_indices'].items():
            if index['layer']!=layer:continue
            p=catalog['points'][anchor]['xyz_m'];ax.plot(p[0]*1000,p[1]*1000,'rx')
            ax.annotate('#'+str(int(anchor[-2:])),(p[0]*1000,p[1]*1000),xytext=(4,6),textcoords='offset points',color='#b01722')
        ax.plot(report['center_xy_m'][0]*1000,report['center_xy_m'][1]*1000,'k+',markersize=12)
        ax.autoscale_view();ax.set_aspect('equal');ax.grid(alpha=.2)
        ax.set_xlabel('Robot-base X (mm)');ax.set_ylabel('Robot-base Y (mm)')
        ax.set_title(f'Layer k={config["layers"]-layer} from bottom / matching parity\nUpper Z {report["layers"][layer-1]["upper_z_m"]*1000:.3f} mm')
    fig.suptitle('Calculated input grid — red crosses: original taught anchors; black +: shared center')
    fig.savefig(path,dpi=170);plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true',help='Back up and extend positions.json')
    parser.add_argument('--plot',action='store_true')
    args=parser.parse_args()
    original=CATALOG.read_text();catalog=json.loads(original)
    config=catalog['input_stack']['config']
    bricks,report=generate(catalog,config)
    if args.write:
        now=datetime.now(timezone.utc);stamp=now.strftime('%Y%m%dT%H%M%S.%fZ')
        with (HERE/'history'/f'positions_before_stack_{stamp}.json').open('x') as backup:backup.write(original)
        old_points=copy.deepcopy(catalog['points'])
        catalog['input_stack'].update(generated_utc=now.isoformat(),report=report)
        catalog['input_bricks']=bricks
        if catalog['points']!=old_points:raise ValueError('Original numbered poses changed')
        temporary=CATALOG.with_name('.positions.json.tmp')
        temporary.write_text(json.dumps(catalog,indent=2,allow_nan=False)+'\n');temporary.replace(CATALOG)
    (HERE/'input_stack_report.json').write_text(json.dumps(report,indent=2)+'\n')
    if args.plot:render(catalog,config,bricks,report,HERE/'input_stack_layout.png')
    print(f'Generated {len(bricks)} brick poses: 10 layers x 6 ridges x 5 bricks')
    print('Upper Z range mm:',report['layers'][0]['upper_z_m']*1000,'to',report['layers'][-1]['upper_z_m']*1000)
    print('Max measured-anchor residual XY mm:',report['max_xy_anchor_residual_mm'])
    print('Max measured-anchor residual Z mm:',report['max_abs_z_anchor_residual_mm'])
    print('Catalog written:',args.write)


if __name__=='__main__':main()

"""Unverified grip-plane screen; not BODY ownership or a robot control policy."""
import numpy as np
from experiments.stage2_contact_20261025.geometry import distance_to_triangles

SURFACE_SLACK_M=50e-6
FORBIDDEN_EXTRA_M=100e-6
MINIMUM_NORMAL_DOT=.9


def screen_contact(point_world_m,separation_m,outward_normal_world,finger_pose_world_wxyz,
                   cad,rendered_association=None):
    """Screen one signed-convention-corrected outward normal and contact point.

    World/finger frames use meters and WXYZ poses. ``cad`` contains only the
    inner-plane Y, expected grip normal, and numeric WHITE/HEAD triangle surfaces.
    ``rendered_association`` is the unchanged rendered-candidate spatial test's
    boolean result. Missing association or forbidden geometry yields UNKNOWN.
    No finite BODY surface is supplied or tested. A compatible result remains
    UNVERIFIED and never establishes shape identity, safety or pick permission.
    Inputs are never modified; thresholds are frozen, not configurable.
    """
    result={'decision':'UNKNOWN','compatible':False,'reasons':[],'evidence':{},
            'body_ownership_established':False,'pick_permission':False}
    expected={'inner_plane_y_m','expected_grip_normal_finger','white_surfaces','head_surfaces'}
    if not isinstance(cad,dict) or set(cad)!=expected:
        result['reasons']=['invalid_numeric_CAD_schema'];return result
    try:
        point=np.asarray(point_world_m,dtype=np.float64);normal=np.asarray(outward_normal_world,dtype=np.float64)
        pose=np.asarray(finger_pose_world_wxyz,dtype=np.float64);grip=np.asarray(cad['expected_grip_normal_finger'],dtype=np.float64)
        separation=float(separation_m);plane=float(cad['inner_plane_y_m'])
    except (TypeError,ValueError):
        result['reasons']=['invalid_numeric_input'];return result
    if (point.shape!=(3,) or normal.shape!=(3,) or pose.shape!=(7,) or grip.shape!=(3,) or
            not np.isfinite(np.r_[point,normal,pose,grip,separation,plane]).all()):
        result['reasons']=['nonfinite_or_wrong_shape'];return result
    qnorm=np.linalg.norm(pose[3:]);nnorm=np.linalg.norm(normal);gnorm=np.linalg.norm(grip)
    if min(qnorm,nnorm,gnorm)<=1e-12:
        result['reasons']=['undefined_pose_or_normal'];return result
    w,x,y,z=pose[3:]/qnorm
    rotation=np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
        [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
        [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])
    local=(point-pose[:3])@rotation;outward=(normal/nnorm)@rotation
    # Expected grip normal is a known unit axis, never fitted to a contact.
    if abs(gnorm-1.)>1e-12:
        result['reasons']=['expected_grip_normal_not_unit'];return result
    tolerance=abs(separation)+SURFACE_SLACK_M
    distances={}
    for category in ('white','head'):
        surfaces=cad[category+'_surfaces']
        if not isinstance(surfaces,list) or not surfaces:
            result['reasons']=['missing_'+category+'_surfaces'];return result
        values=[]
        for surface in surfaces:
            if not isinstance(surface,dict) or set(surface)!={'vertices_finger_m','triangle_indices'}:
                result['reasons']=['invalid_numeric_surface_schema'];return result
            try:
                vertices=np.asarray(surface['vertices_finger_m'],dtype=np.float64);indices=np.asarray(surface['triangle_indices'])
            except (TypeError,ValueError):
                result['reasons']=['invalid_surface_input'];return result
            if (vertices.ndim!=2 or vertices.shape[1:]!=(3,) or not len(vertices) or
                    indices.ndim!=2 or indices.shape[1:]!=(3,) or not len(indices) or indices.dtype.kind not in 'iu' or
                    not np.isfinite(vertices).all() or indices.min()<0 or indices.max()>=len(vertices)):
                result['reasons']=['invalid_surface_arrays'];return result
            values.append(distance_to_triangles(local,vertices,indices))
        distances[category]=min(values)
    flat=float(abs(local[1]-plane));dot=float(outward@grip)
    result['evidence']={'point_finger_m':local.tolist(),'flat_plane_distance_m':flat,'tolerance_m':float(tolerance),
        'outward_dot_grip_normal':dot,'white_distance_m':float(distances['white']),'head_distance_m':float(distances['head']),
        'rendered_association':None}
    if not isinstance(rendered_association,(bool,np.bool_)):
        result['reasons']=['rendered_association_missing_or_ambiguous'];return result
    result['evidence']['rendered_association']=bool(rendered_association)
    if flat>tolerance:result['reasons'].append('outside_grip_plane_tolerance')
    if dot<MINIMUM_NORMAL_DOT:result['reasons'].append('normal_not_lateral_qualified')
    for category in ('white','head'):
        if distances[category]<=tolerance+FORBIDDEN_EXTRA_M:result['reasons'].append(category+'_not_excluded')
    if not rendered_association:result['reasons'].append('rendered_candidate_not_associated')
    result['compatible']=not result['reasons']
    result['decision']='UNVERIFIED_GRIP_PLANE_COMPATIBLE' if result['compatible'] else 'INCOMPATIBLE'
    return result

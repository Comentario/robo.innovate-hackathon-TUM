"""Canonical perception boundary; no detector, neural network or ROS dependency."""
from copy import deepcopy
import math
from planning.faces import face_candidates
from planning import blend_planner


def normalize_snapshot(value):
    if not isinstance(value,dict) or value.get('schema_version')!='inventory-snapshot-0.1':
        raise ValueError('expected inventory-snapshot-0.1 envelope; convert the producer format explicitly')
    for key in ('snapshot_id','source'):
        if not isinstance(value.get(key),str) or not value[key].strip():
            raise ValueError(f'{key} must be a nonempty string')
    if value['source'] not in ('synthetic','perception') or type(value.get('face_aware')) is not bool:
        raise ValueError('source must be synthetic/perception and face_aware must be boolean')
    items=value.get('items')
    if not isinstance(items,list) or not items:
        raise ValueError('snapshot requires a nonempty items list')
    if value['face_aware']:
        face_candidates(items)
    else:
        blend_planner(items,1)
    for item in items:
        score=item.get('score')
        if score is not None and (type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=1):
            raise ValueError('optional score must be finite and in [0,1]')
    result=deepcopy(value)
    poses=result.get('source_poses')
    if poses is not None:
        if not isinstance(poses,dict) or set(poses)!={b['id'] for b in items}:
            raise ValueError('source_poses must map every inventory ID exactly once')
        if result.get('units')!='m' or not isinstance(result.get('frame'),str) or not result['frame'].strip():
            raise ValueError('source poses require units m and an explicit frame')
    return result


def execution_source_poses(snapshot,cell):
    if snapshot.get('source_poses') is None:
        if snapshot['source']!='synthetic':
            raise ValueError('perception execution requires measured source_poses; plan-only remains available')
        return None
    if snapshot['frame']!=cell['frame']:
        raise ValueError('perception poses must be transformed to the cell frame explicitly')
    return deepcopy(snapshot['source_poses'])

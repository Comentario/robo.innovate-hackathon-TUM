"""Final-selected source color evidence; never held identity or motion permission."""
import copy
import hashlib
import inspect
import json
import math
from pathlib import Path
import numpy as np
from experiments.stage1_color_20261025.color import classify


def json_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def array_digest(value):
    array=np.ascontiguousarray(value)
    header=json.dumps({'shape':list(array.shape),'dtype':str(array.dtype)},sort_keys=True,separators=(',',':')).encode()
    return hashlib.sha256(header+b'\0'+array.tobytes()).hexdigest()


def _calibration(calibration):
    arrays={k:np.asarray(calibration[k],float) for k in ('K','R','t')}
    expected={'K':(3,3),'R':(3,3),'t':(3,)}
    if any(arrays[k].shape!=shape for k,shape in expected.items()) or not all(np.isfinite(a).all() for a in arrays.values()):raise ValueError('Invalid retained optical calibration')
    return {k:a.tolist() for k,a in arrays.items()}


def _time(value):
    if value is None:return None
    result=float(value)
    if not math.isfinite(result):raise ValueError('Nonfinite measurement time')
    return result


def make_observation(frame,rgb_bgr,depth,calibration):
    """Call on the retained capture, before final selection is handed off."""
    return {'frame_id':frame['frame_id'],'measurement_time_s':_time(frame.get('measurement_time_s')),
        'rgb_array_sha256':array_digest(rgb_bgr),'depth_array_sha256':array_digest(depth),
        'calibration_sha256':json_digest(_calibration(calibration)),
        'rgb_file_sha256':frame.get('rgb_sha256'),'depth_file_sha256':frame.get('depth_sha256')}


def invalidate(transaction,reason,time_s):
    """Invalidate the current attempt, retaining its immutable source observation."""
    if not isinstance(reason,str) or not reason:raise ValueError('An invalidation reason is required')
    result=copy.deepcopy(transaction);result.update(status='INVALIDATED',invalidated=True,
        invalidated_at_time_s=_time(time_s),held_identity='UNKNOWN',held_color=None,transfer_authorized=False,freshness_verified=False)
    if reason not in result['invalidation_reasons']:result['invalidation_reasons'].append(reason)
    return result


def classify_selection(selection,rgb_bgr,depth,calibration,prototypes,settings,*,observation,
                       reference_hashes,current_time_s,case_id):
    """Classify ONLY selection['candidate']; BGR pixels and axial depth are unmodified.

    Untimed saved observations may be replayed with current_time_s=None. They
    receive no freshness claim. Live use requires exact simulation timestamps.
    Reference file hashes are provenance supplied by the caller's pinned loader;
    content digests below bind the actual dictionaries passed to the classifier.
    """
    candidate=selection.get('candidate');candidate_id=candidate.get('candidate_id') if isinstance(candidate,dict) else None
    cal=_calibration(calibration);measured=_time(observation.get('measurement_time_s'));now=_time(current_time_s)
    actual=make_observation({'frame_id':observation['frame_id'],'measurement_time_s':measured},rgb_bgr,depth,cal)
    classifier_hash=hashlib.sha256(Path(inspect.getfile(classify)).read_bytes()).hexdigest()
    refs={k:reference_hashes[k] for k in ('classifier_sha256','settings_sha256','prototypes_sha256')}
    if refs['classifier_sha256']!=classifier_hash:raise ValueError('Frozen classifier source changed')
    content={'settings_content_sha256':json_digest(settings),'prototypes_content_sha256':json_digest(prototypes)}
    for key,value in content.items():
        if key in reference_hashes and reference_hashes[key]!=value:raise ValueError('Pinned reference contents changed: '+key)
    binding={**copy.deepcopy(observation),**refs,**content,'candidate_id':candidate_id,
        'candidate_sha256':json_digest(candidate),'expected_candidate_sha256':observation.get('candidate_sha256'),
        'input_digests':{k:actual[k] for k in ('rgb_array_sha256','depth_array_sha256','calibration_sha256')},'calibration':cal}
    result={'case_id':case_id,'frame_id':selection.get('frame_id'),'candidate_id':candidate_id,
        'source_color':None,'observation_binding':binding,'held_identity':'UNKNOWN','held_color':None,
        'transfer_authorized':False,'status':'SOURCE_ONLY','invalidated':False,'invalidation_reasons':[],
        'invalidated_at_time_s':None,'freshness_verified':bool(now is not None and measured is not None and now==measured),
        'classified_at_time_s':now,
        'scope':'Observed source color only; no grasp, held-object identity, quality, routing or physical-camera claim.'}
    reasons=[]
    if selection.get('frame_id')!=observation['frame_id']:reasons.append('frame_mismatch')
    if _time(selection.get('measurement_time_s'))!=measured:reasons.append('selection_measurement_time_mismatch')
    for key in ('rgb_array_sha256','depth_array_sha256','calibration_sha256'):
        if observation.get(key)!=actual[key]:reasons.append(key+'_mismatch')
    if 'candidate_sha256' in observation and observation['candidate_sha256']!=binding['candidate_sha256']:reasons.append('candidate_geometry_mismatch')
    if not isinstance(candidate,dict):reasons.append('no_final_candidate')
    if not reasons:
        result['source_color']=classify(rgb_bgr,depth,cal,candidate,observation['frame_id'],prototypes,settings)
    if now is not None and measured is None:reasons.append('measurement_time_unavailable')
    elif now is not None and now!=measured:reasons.append('stale_frame')
    for reason in reasons:result=invalidate(result,reason,now)
    return result

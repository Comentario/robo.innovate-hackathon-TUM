"""Tiny frame/final-selection/lifecycle tests; no saved images or simulator."""
import copy
import hashlib
import inspect
import json
from pathlib import Path
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[1]))
from adapter import classify_selection,make_observation,invalidate,json_digest
from experiments.stage1_color_20261025.color import build_prototypes,classify


def main():
    settings=json.loads((HERE.parent/'stage1_color_20261025/settings.json').read_text())
    rgb=np.empty((32,64,3),np.uint8);rgb[:,:32]=[20,30,210];rgb[:,32:]=[30,160,190]
    depth=np.full((32,64),.1,np.float32);cal={'K':np.array([[100.,0,32.],[0,100.,16.],[0,0,1.]]),'R':np.eye(3),'t':np.zeros(3)}
    prototypes=build_prototypes(rgb,[{'label':'red','pixel_xyxy':[5,5,15,15]},{'label':'ochre','pixel_xyxy':[40,5,50,15]}],settings)
    first={'candidate_id':'first','decision':'present','image_polygon':[[2,2],[29,2],[29,29],[2,29]],'estimated_body_top_from_selected_band_m':.1}
    final={**first,'candidate_id':'FINAL','image_polygon':[[34,2],[61,2],[61,29],[34,29]]}
    selection={'frame_id':'frame_0000','measurement_time_s':1.,'candidate':final}
    observation=make_observation(selection,rgb,depth,cal);observation['candidate_sha256']=json_digest(final)
    refs={'classifier_sha256':hashlib.sha256(Path(inspect.getfile(classify)).read_bytes()).hexdigest(),
        'settings_sha256':'0'*64,'prototypes_sha256':'1'*64,'settings_content_sha256':json_digest(settings),'prototypes_content_sha256':json_digest(prototypes)}
    immutable=json.dumps([selection,observation,prototypes,settings,refs],sort_keys=True);rgb_copy=rgb.copy();depth_copy=depth.copy();cal_copy=copy.deepcopy(cal)
    def call(sel=selection,image=rgb,dep=depth,camera=cal,obs=observation,now=1.):
        return classify_selection(sel,image,dep,camera,prototypes,settings,observation=obs,reference_hashes=refs,current_time_s=now,case_id='synthetic')
    packet=call();expected=classify(rgb,depth,cal,final,'frame_0000',prototypes,settings)
    assert packet['source_color']==expected and packet['source_color']['label']=='ochre'
    assert packet['candidate_id']=='FINAL' and packet['status']=='SOURCE_ONLY' and packet['freshness_verified']
    assert classify(rgb,depth,cal,first,'frame_0000',prototypes,settings)['label']=='red','Control must distinguish first from final'
    for reason in ('abort','slip'):
        invalid=invalidate(packet,reason,2.)
        assert invalid['source_color']==packet['source_color'] and invalid['observation_binding']==packet['observation_binding']
        assert invalid['invalidated'] and invalid['status']=='INVALIDATED' and not invalid['freshness_verified']
        assert packet['invalidated'] is False
    stale=call(now=1.001);assert stale['invalidated'] and 'stale_frame' in stale['invalidation_reasons'] and stale['source_color']==expected
    badframe={**selection,'frame_id':'other'};assert call(sel=badframe)['source_color'] is None
    swapped=rgb.copy();swapped[0,0]=[0,0,0]
    assert 'rgb_array_sha256_mismatch' in call(image=swapped)['invalidation_reasons']
    altered=depth.copy();altered[0,0]=.11
    assert 'depth_array_sha256_mismatch' in call(dep=altered)['invalidation_reasons']
    changed_cal=copy.deepcopy(cal);changed_cal['K'][0,0]+=1
    assert 'calibration_sha256_mismatch' in call(camera=changed_cal)['invalidation_reasons']
    changed=copy.deepcopy(selection);changed['candidate']['image_polygon'][0][0]+=1
    assert 'candidate_geometry_mismatch' in call(sel=changed)['invalidation_reasons']
    uncertain={**selection,'candidate':{**final,'decision':'uncertain'}}
    uncertain_obs={**observation,'candidate_sha256':json_digest(uncertain['candidate'])}
    assert call(sel=uncertain,obs=uncertain_obs)['source_color']['decision']=='unknown'
    nan_depth=np.full_like(depth,np.nan);nan_obs=make_observation(selection,rgb,nan_depth,cal)
    assert call(dep=nan_depth,obs=nan_obs)['source_color']['decision']=='unknown'
    offline={**selection,'measurement_time_s':None};offline_obs=make_observation(offline,rgb,depth,cal)
    assert not call(sel=offline,obs=offline_obs,now=None)['freshness_verified']
    for transaction in (packet,stale,invalidate(packet,'abort',2.)):
        assert transaction['held_identity']=='UNKNOWN' and transaction['held_color'] is None and not transaction['transfer_authorized']
        json.dumps(transaction,allow_nan=False)
    assert immutable==json.dumps([selection,observation,prototypes,settings,refs],sort_keys=True)
    np.testing.assert_array_equal(rgb,rgb_copy);np.testing.assert_array_equal(depth,depth_copy)
    for key in cal:np.testing.assert_array_equal(cal[key],cal_copy[key])
    print('PASS: final selection/direct classifier equality, swapped/stale bindings, abort/slip retention, UNKNOWN and immutable inputs')


if __name__=='__main__':main()

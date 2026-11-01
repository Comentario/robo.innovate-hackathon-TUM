"""Tiny deterministic API checks only; no real images or benchmark processing."""
import copy
import json
from pathlib import Path
import numpy as np
from color import build_prototypes,classify


def main():
    settings=json.loads(Path(__file__).with_name('settings.json').read_text())
    reference=np.zeros((24,48,3),np.uint8)
    reference[:,:24]=[25,30,170]
    reference[:,24:]=[160,80,25]
    patches=[{'label':'A','pixel_xyxy':[0,0,24,24]},
             {'label':'B','pixel_xyxy':[24,0,48,24]}]
    image=np.full((24,24,3),[25,30,170],np.uint8)
    depth=np.ones((24,24),np.float32)
    candidate={'candidate_id':'c0','decision':'present',
        'image_polygon':[[1,1],[22,1],[22,22],[1,22]],
        'estimated_body_top_from_selected_band_m':0.}
    cal={'K':np.array([[100.,0,12],[0,100.,12],[0,0,1.]]),
         'R':np.eye(3),'t':np.array([0.,0.,1.])}
    arrays={key:value.copy() for key,value in {'reference':reference,'image':image,'depth':depth,**cal}.items()}
    settings_before=copy.deepcopy(settings);candidate_before=copy.deepcopy(candidate);patches_before=copy.deepcopy(patches)
    prototypes=build_prototypes(reference,patches,settings)
    assert prototypes['ready'] and all(row['valid_pixels']>=64 for row in prototypes['labels'].values())
    prototypes_before=copy.deepcopy(prototypes)
    known=classify(image,depth,cal,candidate,'f0',prototypes,settings)
    assert known['decision']=='known' and known['label']=='A'
    assert (known['frame_id'],known['candidate_id'],known['source_decision'])==('f0','c0','present')
    mixed=image.copy();mixed[:,12:]=[160,80,25];mixed_before=mixed.copy()
    unknown=classify(mixed,depth,cal,candidate,'fmix',prototypes,settings)
    assert unknown['decision']=='unknown' and unknown['label'] is None and unknown['source_decision']=='present'
    assert 'mixed_or_inconsistent_pixels' in unknown['reasons']
    invalid_depth=np.full_like(depth,np.nan)
    invalid=classify(image,invalid_depth,cal,candidate,'fnan',prototypes,settings)
    assert invalid['decision']=='unknown' and invalid['evidence']['valid_pixels']==0
    nonpresent=classify(image,depth,cal,{**candidate,'decision':'uncertain'},'fu',prototypes,settings)
    assert nonpresent['decision']=='unknown' and nonpresent['reasons']==['candidate_not_present']
    glare=classify(np.full_like(image,255),depth,cal,candidate,'fglare',prototypes,settings)
    dark=classify(np.zeros_like(image),depth,cal,candidate,'fdark',prototypes,settings)
    assert glare['decision']==dark['decision']=='unknown'
    assert glare['evidence']['valid_pixels']==dark['evidence']['valid_pixels']==0
    for key,value in {'reference':reference,'image':image,'depth':depth,**cal}.items():
        assert np.array_equal(value,arrays[key]),'Mutated raw input: '+key
    assert np.array_equal(mixed,mixed_before) and np.isnan(invalid_depth).all()
    assert candidate==candidate_before and settings==settings_before and patches==patches_before and prototypes==prototypes_before
    json.dumps({'prototypes':prototypes,'known':known,'mixed':unknown,'invalid':invalid,
                'nonpresent':nonpresent,'glare':glare,'dark':dark},allow_nan=False)
    print('PASS: known, mixed-PRESENT abstention, NaN depth, non-PRESENT, glare/dark, exact association, strict JSON and input immutability.')


if __name__=='__main__':main()

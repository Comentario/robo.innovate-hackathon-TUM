"""Tiny direct Sensors handoff test without initializing Isaac or reading photos."""
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
from experiments.stage2_pick_20261025.sensors import Sensors
from experiments.stage1_handoff_20261025.adapter import make_observation
from experiments.stage1_color_20261025.color import classify


def main():
    sensor=Sensors.__new__(Sensors)
    sensor.source_color_reference=None
    assert sensor.color_handoff({},'synthetic') is None
    image=np.full((32,32,3),[20,30,210],np.uint8)
    depth=np.full((32,32),.1,np.float32)
    cal={'K':np.array([[100.,0.,16.],[0.,100.,16.],[0.,0.,1.]]),'R':np.eye(3),'t':np.zeros(3)}
    selected={'frame_id':'unit_frame','measurement_time_s':1.,'candidate':{
        'candidate_id':'FINAL','decision':'present','image_polygon':[[2,2],[29,2],[29,29],[2,29]],
        'estimated_body_top_from_selected_band_m':.1}}
    reference=json.loads((HERE/'references.json').read_text())
    settings=json.loads((ROOT/reference['settings']['path']).read_text())
    prototypes=json.loads((ROOT/reference['prototypes']['path']).read_text())
    with TemporaryDirectory(prefix='robo26-color-hook-') as temporary:
        sensor.output=Path(temporary);(sensor.output/'online').mkdir()
        sensor.source_color_reference=HERE/'references.json'
        sensor.color_rgb_bgr=image;sensor.color_depth=depth;sensor.cal=cal
        sensor.color_observation=make_observation(selected,image,depth,cal)
        sensor.sim=SimpleNamespace(current_time=1.)
        result=sensor.color_handoff(selected,'synthetic')
        assert result['source_color']==classify(image,depth,cal,selected['candidate'],'unit_frame',prototypes,settings)
        assert result['candidate_id']=='FINAL' and result['freshness_verified']
        assert result['held_identity']=='UNKNOWN' and not result['transfer_authorized']
        assert result['reference_bundle_sha256']==hashlib.sha256((HERE/'references.json').read_bytes()).hexdigest()
        assert json.loads((sensor.output/'online/source_color_handoff.json').read_text())==result
        sensor.sim.current_time=2.
        assert sensor.color_handoff(selected,'synthetic')['status']=='INVALIDATED'
    print('PASS: actual Sensors.color_handoff default no-op, pinned references, final selection, stale input and source-only artifact')


if __name__=='__main__':main()

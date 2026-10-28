"""Verify continuous clocks, pre-populated start and real-feed edit windows."""
import importlib.util,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('planner',root/'unreal/tools/plan_night_tours.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
facts=json.loads(Path(sys.argv[1]).read_text())
for i in range(1,11):
    t=m.make(facts,i);previous=None
    for segment in t['clock']:
        if previous:
            assert abs(segment['videoStart']-previous['videoStart']-previous['duration'])<1e-8
            assert abs(segment['nativeStart']-m.Clock.state(previous,previous['videoStart']+previous['duration']))<1e-7
            assert segment['rateStart']==previous['rateEnd']
        previous=segment
    assert t['cart']==1 and t['stockPalletsAtStart']>0
    assert t['outroAdditionalInspected']>=1000
    assert t['frames']==__import__('math').ceil(t['seconds']*30)
    for overlay in t['overlays'].values():
        assert 0<=overlay['start']<=overlay['fadeIn']<overlay['fadeOut']<overlay['end']<t['seconds']
        assert overlay['start']+overlay['clipSeconds']<=overlay['end']
    d=t['overlays']['detection']
    for s in t['clock']:
        if s['videoStart']<d['end'] and s['videoStart']+s['duration']>d['start']:
            assert s['rateStart']==s['rateEnd']==1,'Inspection simulation freezes or speeds up during real detection overlay'
print('Ten plans verified: continuous time/speed, second-cart start, populated inventory, two complete real-feed edits, uninterrupted inspection.')

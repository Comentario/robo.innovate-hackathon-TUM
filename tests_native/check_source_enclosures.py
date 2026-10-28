"""Verify actual C++ enclosure traces against the unchanged source-camera trace."""
import argparse,csv,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--before',type=Path,required=True);p.add_argument('--after',type=Path,required=True);p.add_argument('--output',type=Path);a=p.parse_args()
old=list(csv.DictReader(a.before.open()));new=list(csv.DictReader(a.after.open()));assert len(old)==len(new)>0
maximum=0
for before,after in zip(old,new):
    for key in before:
        if key in ['subject','view']:assert before[key]==after[key]
        else:maximum=max(maximum,abs(float(before[key])-float(after[key])))
assert maximum==0,'The enclosure revision must preserve the exact source and camera trajectory'
result=dict(frames=len(new),maximumCameraOrSourceDifference=maximum,coverage={})
for key in ['inspectionCoverage','routingCoverage']:
    values=[float(row[key]) for row in new];step=max(abs(b-a) for a,b in zip(values,values[1:]));assert all(.2<=v<=1 for v in values)
    assert min(values)<.4,'The focused enclosure never reveals the interior'
    assert values[0]==values[-1]==1,'Establishing and final views must recover closed covers'
    assert step<.05,'An enclosure changes abruptly between adjacent video frames'
    result['coverage'][key]=dict(minimum=min(values),maximum=max(values),maximumFrameStep=step,final=values[-1])
result['limits']='Native geometry/clock regression evidence; independent visual source/native comparison is still required.'
if a.output:a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))

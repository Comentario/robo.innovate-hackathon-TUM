"""Verify evidence produced by the actual Unreal native application."""
import argparse
import gzip
import json
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('evidence',type=Path)
parser.add_argument('--reference',type=Path,default=Path('artifacts/greenfield_30'))
parser.add_argument('--output',type=Path)
args=parser.parse_args()
actual=json.loads(args.evidence.read_text(encoding='utf-8-sig'))
assert actual['simulationBackend']=='native-cpp20'
assert actual['referenceSha256']=='7573180b519dfa27f1b97b6cd682659b5235f129f1ad7d4f9b73f25db808805b'
mode=actual['initialMode'];assert mode in ('mixed','single')
expected=json.loads(gzip.decompress((args.reference/f'{mode}-572c87cac2f8addb.json.gz').read_bytes()))
for key in ('inspected','rejected','formed','delivered'):
    assert actual[key]==expected[key],(key,actual[key],expected[key])
for a,b in [('batchSeconds','total'),('bricksPerHour','bph'),('palletsPerHour','pph')]:
    assert abs(actual[a]-expected[b])<1e-7,(a,actual[a],expected[b])
assert len(actual['pallets'])==len(expected['pallets'])
identities=[];max_error=0
for a,b in zip(actual['pallets'],expected['pallets']):
    assert a['ids']==[str(i)for i in b['ids']], 'Unreal pallet identity or order mismatch'
    for key in ('lane','cart','slot'):assert a[key]==b[key],key
    assert a['shade']==(-1 if b['shade']is None else b['shade'])
    error=abs(a['t']-b['t']);max_error=max(max_error,error);assert error<1e-7
    identities.extend(a['ids'])
assert len(identities)==len(set(identities))
report={'verified':True,'backend':'Unreal native C++20','mode':mode,'pallets':len(actual['pallets']),
        'shippedIdentities':len(identities),'maximumDispatchTimeErrorSeconds':max_error,
        'evidence':'Numerical agreement with synthetic reference; not physical validation.'}
if args.output:args.output.write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))

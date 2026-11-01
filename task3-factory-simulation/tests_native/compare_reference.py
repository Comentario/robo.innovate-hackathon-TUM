"""Compare native C++ output against the immutable greenfield_30 replay caches.

This is an offline verification utility, never a runtime simulation dependency.
"""
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--native-dir', type=Path, default=Path('artifacts/cinematic/reference_30'))
parser.add_argument('--reference-dir', type=Path, default=Path('artifacts/greenfield_30'))
parser.add_argument('--output', type=Path, default=Path('artifacts/cinematic/reference_30/comparison.json'))
args = parser.parse_args()
report = {'referenceSha256': hashlib.sha256((args.reference_dir/'index.html').read_bytes()).hexdigest(),
          'verified': True, 'modes': {}}
for mode in ('mixed', 'single'):
    native = json.loads((args.native_dir/f'native-{mode}.json').read_text())
    reference = json.loads(gzip.decompress((args.reference_dir/f'{mode}-572c87cac2f8addb.json.gz').read_bytes()))
    for key in ('inspected','rejected','formed','delivered','completeInput'):
        assert native[key] == reference[key], (mode, key, native[key], reference[key])
    for key in ('total','bph','pph'):
        assert math.isclose(native[key], reference[key], rel_tol=0, abs_tol=1e-7), (mode,key)
    assert len(native['pallets']) == len(reference['pallets'])
    max_time_error = 0
    all_ids = []
    for actual, expected in zip(native['pallets'],reference['pallets']):
        assert actual['ids'] == expected['ids'], f'{mode}: pallet identity/order mismatch'
        assert len(actual['ids']) == 560
        for key in ('lane','cart','slot'):
            assert actual[key] == expected[key], (mode,key)
        assert actual['shade'] == (-1 if expected['shade'] is None else expected['shade'])
        error = abs(actual['t']-expected['t']); max_time_error = max(max_time_error,error)
        assert error < 1e-7, f'{mode}: dispatch time mismatch'
        all_ids.extend(actual['ids'])
    assert len(all_ids) == len(set(all_ids)), f'{mode}: duplicated output material'
    report['modes'][mode] = {'verified':True,'pallets':len(native['pallets']),
        'shippedIdentities':len(all_ids),'maxDispatchTimeErrorSeconds':max_time_error,
        'batchTimeErrorSeconds':abs(native['total']-reference['total']),
        'bricksPerHour':native['bph'],'palletsPerHour':native['pph']}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))

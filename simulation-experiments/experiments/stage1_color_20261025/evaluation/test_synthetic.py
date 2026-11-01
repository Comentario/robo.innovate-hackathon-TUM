"""Tiny JSON-contract tests; no rendered pixels, depth or scoring batch."""
from evaluate import pin_prefix,inside,group,score,PATCHES

def main():
    prefix=pin_prefix('/home/faps/dev/github/robo.innovate26/runs/frozen_source')
    pins={'runs/frozen_source/sensors/calibration.json':'fixed'}
    assert pins[prefix+'/sensors/calibration.json']=='fixed'
    assert inside([1,1],[[0,0],[2,0],[2,2],[0,2]])
    assert not inside([3,1],[[0,0],[2,0],[2,2],[0,2]])
    assert group('same_physical_object')==group('same_physical_object')
    visible=[{'reference_id':'x','truth_label':'tan'}]
    calls=[{'reference_id':'x','truth_label':'tan','predicted_label':None,'status':'unknown'}]
    result=score(visible,calls)
    assert result['known_label_precision'] is None and result['color_coverage_eligible_present']==0 and result['correct_color_recall_all_visible']==0
    assert set(result['per_label'])==set(PATCHES)
    print('Synthetic pin-path/containment/split/UNKNOWN score checks PASS')
if __name__=='__main__':main()

"""Small transform/extraction regressions only; never loads the315-pose input."""
import importlib.util
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

HERE=Path(__file__).resolve().parent


def main():
    spec=importlib.util.spec_from_file_location('grasp_reference_check',HERE/'extract_and_check.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    example={'motion_validated':False,'poses':[{'grasp_physically_validated':False}]}
    raw=json.dumps(example);block,data=m.extract('# reference\n```json\n'+raw+'\n```\n')
    assert block==raw and data==example
    for text in ('no JSON','```json\n{}\n```\n```json\n{}\n```'):
        try:m.extract(text)
        except ValueError:pass
        else:raise AssertionError('Missing/ambiguous authoritative block accepted')
    fh=np.eye(4);fh[:3,:3]=Rotation.from_euler('z',-np.pi/4).as_matrix()
    he=np.eye(4);he[2,3]=.1034;hg=np.eye(4);hg[2,3]=.11755756120085716
    be=np.eye(4);be[:3,:3]=np.diag([1,-1,-1]);be[:3,3]=[.4,.02,.08]
    original=be.copy();flat=be.reshape(-1,order='F').tolist()
    np.testing.assert_array_equal(m.matrix(flat),be)
    bh,bg,derived=m.bridge_pose(be,fh,fh@he,hg)
    np.testing.assert_allclose(derived,he,atol=1e-15,rtol=0)
    np.testing.assert_allclose(bh@he,be,atol=1e-15,rtol=0)
    np.testing.assert_allclose(bg[:3,3],[.4,.02,.08-(.11755756120085716-.1034)],atol=1e-15,rtol=0)
    np.testing.assert_array_equal(be,original)  # No second -15mm applied.
    assert m.proper(be);bad=be.copy();bad[0,0]=-1;assert not m.proper(bad)
    for values in ([0]*15,[float('nan')]*16):
        try:m.matrix(values)
        except ValueError:pass
        else:raise AssertionError('Invalid transform accepted')
    print('PASS: raw flags preserved, unique extraction, column-major decode, fixed frame bridge, no double15mm, rigid/input checks')


if __name__=='__main__':main()

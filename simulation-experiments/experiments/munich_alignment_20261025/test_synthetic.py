"""Small synthetic JSON/XML/frame checks; never reads calibration observations."""
import json
import os
from pathlib import Path
import tempfile
import numpy as np
from scipy.spatial.transform import Rotation
from check_bridge import fk,residual,rigid,run,urdf_chain


def main():
    xml='''<robot name="synthetic"><joint name="j1" type="revolute">
      <parent link="fr3_link0"/><child link="fr3_hand"/>
      <origin xyz="0.1 0.2 0.3" rpy="0.2 0.1 -0.4"/><axis xyz="0 0 1"/>
      </joint><joint name="tcp" type="fixed"><parent link="fr3_hand"/>
      <child link="fr3_hand_tcp"/><origin xyz="0 0 0.1" rpy="0 0 0"/></joint></robot>'''
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'synthetic.urdf';path.write_text(xml)
        frames=fk(urdf_chain(path),{'j1':.3})
    hand=frames['fr3_hand'];tcp=frames['fr3_hand_tcp']
    expected=Rotation.from_euler('xyz',[.2,.1,-.4]).as_matrix()@Rotation.from_rotvec([0,0,.3]).as_matrix()
    np.testing.assert_allclose(hand[:3,:3],expected,atol=1e-14)
    np.testing.assert_allclose(tcp[:3,3],hand[:3,3]+expected@[0,0,.1],atol=1e-14)
    decoded=np.asarray(tcp.flatten(order='F')).reshape(4,4,order='F')
    np.testing.assert_array_equal(decoded,tcp)
    assert residual(hand,hand)['translation_m']==0
    assert residual(hand,hand)['rotation_rad']<1e-14
    np.testing.assert_allclose(np.linalg.inv(hand)@tcp,np.diag([1.,1.,1.,1.])+np.array([[0,0,0,0],[0,0,0,0],[0,0,0,.1],[0,0,0,0]]),atol=1e-14)
    json.dumps({'pose':tcp.tolist(),'error':residual(hand,hand)},allow_nan=False)
    try:rigid(np.full((4,4),np.nan))
    except ValueError:pass
    else:raise AssertionError('Nonfinite input accepted')
    before=os.environ.pop('ROBO_PUEUE_JOB',None)
    try:
        try:run('/input-not-read','/output-not-created')
        except RuntimeError as error:assert 'Pueue' in str(error)
        else:raise AssertionError('Missing pre-input scheduler guard')
    finally:
        if before is not None:os.environ['ROBO_PUEUE_JOB']=before
    print('PASS: synthetic URDF/FK/fixed-tool bridge, column-major decode, strict JSON/finite/scheduler guards')


if __name__=='__main__':main()

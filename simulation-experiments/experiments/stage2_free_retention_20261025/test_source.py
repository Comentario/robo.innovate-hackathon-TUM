"""Tiny source/fixture math checks; no Isaac import or saved numerical data."""
import ast
import math
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent


def tree(path):return ast.parse(path.read_text())
def function(t,name):return next(n for n in t.body if isinstance(n,ast.FunctionDef) and n.name==name)
def dump(n):return ast.dump(n,include_attributes=False)
def assignment(t,name):
    return next(n for n in ast.walk(t) if isinstance(n,ast.Assign) and any(isinstance(a,ast.Name) and a.id==name for a in n.targets))


def main():
    current=tree(HERE/'run_fixture.py');parent=tree(HERE.parent/'stage2_position_candidate_20261025/run_pick.py')
    for name in ('contacts','qangle','interpolate'):assert dump(function(current,name))==dump(function(parent,name)),name
    for name in ('position_sample','actual_joint_gap','commanded_joint_gap','finger_errors'):
        assert dump(assignment(current,name))==dump(assignment(parent,name)),name
    def closing(t):
        return next(n for n in ast.walk(t) if isinstance(n,ast.If) and ast.unparse(n.test)=="phase == 'close'" and n.body and isinstance(n.body[0],ast.Assign) and any(isinstance(a,ast.Name) and a.id=='positive' for a in n.body[0].targets))
    assert dump(closing(current))==dump(closing(parent)),'closure/admission/lift commands changed'
    calls=[ast.unparse(n.func) for n in ast.walk(current) if isinstance(n,ast.Call)]
    assert not any('write_root' in n or 'write_joint_state' in n or 'set_transforms' in n for n in calls)
    source=(HERE/'run_fixture.py').read_text()
    assert "recorder.stationary=True" in source and "else 'close'" in source
    scope={'np':np,'math':math}
    small=ast.Module(body=[function(current,'fixture_design'),function(current,'qangle')],type_ignores=[])
    exec(compile(ast.fix_missing_locations(small),'synthetic_fixture','exec'),scope)
    q=[0.,math.sqrt(.5),math.sqrt(.5),0.]
    reference={'tcp_pose_world_wxyz':[.14,-.12,.20,*q],
        'finger_poses_world_wxyz':{'left':[.14909331,-.12,.2591575612,*q],'right':[.13090669,-.12,.2591575612,*q]}}
    cfg={'scene_fingertip_spec':{'stock_pad_backplane_abs_finger_y_m':.01090669,'body_mount_cad_x_mm':-9.5,'distal_tip_finger_z_m':.06164037066757202}}
    plan={'nominal_body_side_overlap_m':.003082809466714867,'body_size_m':[.032,.016,.0096],
        'post_size_xy_m':[.008,.008],'table_z_m':0.,'fixture_reference_metadata':{'sha256':'synthetic'}}
    before=repr(reference);design=scope['fixture_design'](reference,cfg,plan)
    np.testing.assert_allclose(design['body_top'],.2006,atol=1e-12)
    np.testing.assert_allclose(design['coupon_pose'][:3],[.14,-.12,.191],atol=1e-12)
    from scipy.spatial.transform import Rotation
    orientation=np.asarray(design['coupon_pose'][3:])
    np.testing.assert_allclose(Rotation.from_quat(orientation[[1,2,3,0]]).apply([0,0,1]),[0,0,1],atol=1e-15)
    assert design['post_size'][2]>0 and repr(reference)==before
    assert scope['qangle'](np.array(q,dtype=np.float32).astype(float),q)<1e-7
    print('PASS: unchanged contact/closure guards, no measured pose writes, upright body-base support and input immutability')


if __name__=='__main__':main()

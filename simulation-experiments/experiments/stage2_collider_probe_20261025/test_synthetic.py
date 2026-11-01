"""Tiny event-sign/redaction/empty-LOST/source checks; no Kit imports."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from native_observer import NativeObserver,role_packet


def main():
    roles={'/robot/pad':{'side':'left','role':'body'}};actors={'/robot/finger':'left'}
    point={'position':[0.,0.,0.],'normal':[0.,1.,0.],'impulse':[.00001,.0002,0.],'separation':0.}
    header={'actor0':'/robot/finger','actor1':'/private/object','collider0':'/robot/pad','collider1':'/private/shape',
            'proto_index0':0xffffffff,'proto_index1':0xffffffff,'points':[point]}
    packet=role_packet([{'headers':[header]}],roles,actors,.01)
    assert packet['robot_contacts'][0]['normal_force_on_robot_world_N']==[0.,.02,0.]
    assert '/private' not in json.dumps(packet,allow_nan=False)
    reverse={**header,'actor0':header['actor1'],'actor1':header['actor0'],'collider0':header['collider1'],'collider1':header['collider0'],
             'points':[{**point,'normal':[0.,-1.,0.],'impulse':[-.00001,-.0002,0.]}]}
    assert packet==role_packet([{'headers':[reverse]}],roles,actors,.01)
    for bad in ({**header,'proto_index0':0},{**header,'collider0':'/unknown'},
                {**header,'points':[{**point,'normal':[0.,0.,0.]}]}):
        assert role_packet([{'headers':[bad]}],roles,actors,.01)['unknown_robot_shapes']==1
    empty={**header,'collider0':'/unknown','proto_index0':0,'points':[]}
    assert role_packet([{'headers':[empty]}],roles,actors,.01)=={'robot_contacts':[],'unknown_robot_shapes':0}
    # An empty LOST header's original offset is unspecified: never dereference it.
    observer=NativeObserver.__new__(NativeObserver);observer.active=True;observer.callbacks=[];observer.errors=[]
    observer.sim=SimpleNamespace(current_time=.01);observer.decode=str;observer.stage_id=7
    lost=SimpleNamespace(actor0=1,actor1=2,collider0=3,collider1=4,stage_id=7,type='LOST',
                         proto_index0=0xffffffff,proto_index1=0xffffffff,contact_data_offset=-123,num_contact_data=0)
    observer._callback([lost],[])
    assert not observer.errors and observer.callbacks[0]['headers'][0]['points']==[]
    assert observer.callbacks[0]['headers'][0]['raw_collider0']==3
    bad=SimpleNamespace(**{**lost.__dict__,'num_contact_data':1})
    observer._callback([bad],[]);assert observer.errors
    source=ast.parse((Path(__file__).parent/'run_probe.py').read_text())
    tick=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='tick')
    calls=[n.func.attr for n in ast.walk(tick) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
    assert 'set_kinematic_targets' in calls and 'write_root_pose_to_sim' not in calls
    # Fixed1812 literals: no real files/arrays are loaded by this regression.
    actual=np.array([-1.7136335372924805e-7,.9238798022270203,.38268306851387024,-2.4214389782173384e-7],dtype=np.float32)
    command=np.array([-1.7136334627960553e-7,.9238797024587486,.3826830220752498,-2.4214385887335565e-7],dtype=np.float64)
    old=float(2*np.arccos(np.clip(abs(actual@command)/(np.linalg.norm(actual)*np.linalg.norm(command)),0,1)))
    # Execute the actual repaired producer's three angle expressions.
    statements=tick.body
    angle_statements=[n for n in statements if isinstance(n,ast.Assign) and any(
        isinstance(t,ast.Name) and t.id in ('qa','qb','angle_error') for t in n.targets)]
    # The subsequent TCP guard also has qa/qb assignments; restrict to the first angle output.
    angle_statements=angle_statements[:next(i for i,n in enumerate(angle_statements) if any(isinstance(t,ast.Name) and t.id=='angle_error' for t in n.targets))+1]
    namespace={'np':np,'actual':np.r_[np.zeros(3,dtype=np.float32),actual],'cube_pose':np.r_[np.zeros(3),command]}
    exec(compile(ast.fix_missing_locations(ast.Module(body=angle_statements,type_ignores=[])),'<actual-angle-producer>','exec'),namespace)
    assert old>1e-4 and namespace['angle_error']<1e-4
    for theta in (5e-5,2e-4):
        namespace['actual']=np.r_[np.zeros(3),[np.cos(theta/2),np.sin(theta/2),0.,0.]]
        namespace['cube_pose']=np.array([0.,0.,0.,1.,0.,0.,0.])
        exec(compile(ast.fix_missing_locations(ast.Module(body=angle_statements,type_ignores=[])),'<actual-angle-producer>','exec'),namespace)
        assert (namespace['angle_error']<=1e-4)==(theta<=1e-4)
    print('PASS: event contracts, target-only motion, saved1812 float64 angle regression and unchanged1e-4 gate')


if __name__=='__main__':main()

"""Small source and endpoint/state-machine checks; no simulator or saved arrays."""
import ast
import hashlib
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from bridge import model_gap


def main():
    here=Path(__file__).resolve().parent;root=here.parents[1]
    parent=(root/'experiments/stage2_exploratory_20261025/run_pick.py').read_bytes()
    assert hashlib.sha256(parent).hexdigest()=='a8db27f3e6ab599472d1ba6be65eda449a867bb66ec35bf55c88d45d8e843bb7'
    source=(here/'run_pick.py').read_text()
    functions=lambda tree:{n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    old,new=functions(ast.parse(parent)),functions(ast.parse(source))
    for name in ('admission','qangle','interpolate','construct','factory','loader'):
        assert ast.dump(old[name])==ast.dump(new[name]),name
    selection=lambda n:next(x for x in n.body if isinstance(x,ast.If) and ast.unparse(x.test)=="args.mode == 'pick'")
    assert ast.dump(selection(old['run']))==ast.dump(selection(new['run']))
    associated=lambda n:next(x for x in ast.walk(n) if isinstance(x,ast.If) and ast.unparse(x.test)=='selected is not None')
    assert ast.dump(associated(old['contacts']))==ast.dump(associated(new['contacts']))
    loop=next(x for x in ast.walk(new['run']) if isinstance(x,ast.While))
    native_names={'native','native_path','_discarded_packet','native_index','role_paths'}
    for node in ast.walk(loop):
        if isinstance(node,ast.If):assert not any(isinstance(x,ast.Name) and x.id in native_names for x in ast.walk(node.test))
    inner={'left':.00140669,'right':-.00140669};q=.00909331
    state={'tcp_pose_world_wxyz':[0,0,0,1,0,0,0],
           'finger_poses_world_wxyz':{'left':[0,q,.0584,1,0,0,0],'right':[0,-q,.0584,1,0,0,0]}}
    gap=model_gap(state,inner);intercept=gap-2*q;endpoint=(.014-intercept)/2
    assert abs(gap-.021)<1e-14 and abs(endpoint-.00559331)<1e-14
    assert abs(float(np.float32(endpoint))-endpoint)<=1e-9
    rotation=Rotation.from_euler('xyz',[.2,.4,-.8]);quat=rotation.as_quat()[[3,0,1,2]].tolist()
    shifted={'tcp_pose_world_wxyz':[.1,.2,.3,*quat],'finger_poses_world_wxyz':{}}
    for side,pose in state['finger_poses_world_wxyz'].items():
        shifted['finger_poses_world_wxyz'][side]=[*(rotation.apply(pose[:3])+[.1,.2,.3]),*quat]
    assert abs(model_gap(shifted,inner)-gap)<1e-14
    # Execute the actual clamp branch and completed-command counter.
    branch=next(n for n in loop.body if isinstance(n,ast.If) and ast.unparse(n.test)=="phase == 'close'")
    ns={'phase':'close','finger_command':endpoint+1e-6,'endpoint_q':endpoint,'dt':1/120,'plan':{'endpoint_command_tolerance_m':1e-9}}
    exec(compile(ast.Module(body=[branch],type_ignores=[]),'<clamp>','exec'),ns)
    assert ns['finger_command']==endpoint and ns['closing_state']=='endpoint_settle'
    counter=next(n for n in loop.body if isinstance(n,ast.If) and 'endpoint_settle' in ast.unparse(n.test))
    ns['endpoint_commands']=0;exec(compile(ast.Module(body=[counter],type_ignores=[]),'<completed-counter>','exec'),ns)
    assert ns['endpoint_commands']==1
    # The third loaded sample freezes commanded float32 q, not measured q.
    transition=next(n for n in ast.walk(loop) if isinstance(n,ast.If) and ast.unparse(n.test)=="phase == 'close'" and any(isinstance(x,ast.Name) and x.id=='positive' for x in ast.walk(n)))
    command=float(np.float32(.006));ns={'np':np,'phase':'close','positive':2,'forces':{'left':1.5,'right':1.5},'step':3,
        'plan':{'grasp_confirmation_N':1.5,'grasp_confirmation_consecutive_steps':3,'commanded_lift_m':.005,'endpoint_settle_steps':30},
        'commanded':{'joint_commands':[0.]*7+[command,command]},'finger_ids':[7,8],'finger_command':.0060000001,
        'closing_state':'ramp','post':np.array([0.,0.,.1,1,0,0,0]),'endpoint_commands':0,'stop':[]}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[transition],type_ignores=[])),'<confirmation>','exec'),ns)
    assert ns['phase']=='lift' and ns['finger_command']==command and ns['confirmation']['command_q_m']==command
    ns.update(phase='close',positive=0,forces={'left':.1,'right':.1},endpoint_commands=30,stop=[],status='running')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[transition],type_ignores=[])),'<endpoint-no-force>','exec'),ns)
    assert ns['status']=='endpoint_without_load_confirmation' and ns['phase']=='close'
    compile(source,'run_pick.py','exec')
    print('PASS: frozen initialization/perception/association, no native policy branch, model gap, float32 endpoint, completed settle and last-command freeze')


if __name__=='__main__':main()

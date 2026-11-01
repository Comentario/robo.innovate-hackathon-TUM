"""Source-inactive control proof and tiny timing-only admission regression."""
import ast
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent


def dump(node):return ast.dump(node,include_attributes=False)
def named(tree,name):return next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
def closing(tree):
    return next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="phase == 'close'" and n.body and isinstance(n.body[0],ast.Assign) and any(isinstance(t,ast.Name) and t.id=='positive' for t in n.body[0].targets))
def control_prefix(tree):
    loop=next(n for n in ast.walk(tree) if isinstance(n,ast.While))
    for i,node in enumerate(loop.body):
        if isinstance(node,ast.If) and ast.unparse(node.test)=="args.mode == 'control'" and len(node.body)==1 and isinstance(node.body[0],ast.Continue):return loop.body[:i+1]
    raise AssertionError('Missing unconditional control continuation')


def main():
    path=HERE/'run_fixture.py';parent=HERE.parent/'stage2_free_retention_20261025/run_fixture.py'
    current,old=ast.parse(path.read_text()),ast.parse(parent.read_text())
    for name in ('fixture_design','coupon_properties','fixture_initial','sample','contacts','qangle','interpolate','loader','construct','factory'):
        assert dump(named(current,name))==dump(named(old,name)),name
    assert [dump(n) for n in control_prefix(current)]==[dump(n) for n in control_prefix(old)],'Measured control path changed'
    for tree in (current,old):
        assert not any(isinstance(n,ast.Call) and any(s in ast.unparse(n.func) for s in ('write_root','write_joint_state','set_transforms')) for n in ast.walk(tree))
    for name in ('position_sample','actual_joint_gap','commanded_joint_gap','finger_errors'):
        def assignment(t):return next(n for n in ast.walk(t) if isinstance(n,ast.Assign) and any(isinstance(a,ast.Name) and a.id==name for a in n.targets))
        assert dump(assignment(current))==dump(assignment(old)),name
    assert 'original_control_protocol' in ast.unparse(named(current,'verify_fresh_control'))
    block=compile(ast.fix_missing_locations(ast.Module(body=[closing(current)],type_ignores=[])),'synthetic_admission','exec')
    plan={'grasp_confirmation_N':1.5,'grasp_confirmation_consecutive_steps':3,'endpoint_settle_steps':30,'candidate_consecutive_steps':3,'commanded_lift_m':.005}
    command=float(np.float32(.005593305353995928));env={'plan':plan,'np':np,'phase':'close','positive':0,'forces':{'left':1.6,'right':1.6},
        'force_reference':None,'confirmation':None,'position_candidate':None,'lift_admission':None,'closing_state':'endpoint_settle',
        'finger_command':command,'commanded':{'joint_commands':[command,command]},'finger_ids':[0,1],
        'commanded_finger_q':np.array([command,command]),'post':np.array([.14,-.12,.2,0.,1.,0.,0.]),'stop':[],'status':'running'}
    for count in range(1,31):
        env.update(step=count,endpoint_commands=count,position_count=count,position_window=[{'step':s} for s in range(max(1,count-2),count+1)])
        exec(block,env)
        if count<30:assert env['phase']=='close' and env['lift_admission'] is None and env['finger_command']==command
    assert env['force_reference']['step']==3 and env['confirmation'] is None
    assert env['phase']=='lift' and env['lift_admission']=={'kind':'position_candidate','step':30,'command_q_m':command}
    assert env['position_candidate']['endpoint_settle_completed_commands']==30
    assert env['finger_command']==command and env['phase_target'][2]==.20500000000000002
    failed=dict(env,phase='close',endpoint_commands=30,position_count=2,position_candidate=None,lift_admission=None,status='running',stop=[])
    exec(block,failed)
    assert failed['status']=='endpoint_without_position_candidate' and failed['lift_admission'] is None
    assert "metadata['grasp_confirmation']=confirmation" in path.read_text()
    print('PASS: unchanged measured control/contact/physics source, force reference cannot advance, exact30-command position admission and failed-window abstention')


if __name__=='__main__':main()

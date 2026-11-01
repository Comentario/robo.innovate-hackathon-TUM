"""Tiny frozen-source and stop-precedence checks; no Isaac/real-array imports."""
import ast
import hashlib
from pathlib import Path


def main():
    here=Path(__file__).resolve().parent;root=here.parents[1]
    old=(root/'experiments/stage2_exploratory_20261025/run_pick.py').read_bytes()
    assert hashlib.sha256(old).hexdigest()=='a8db27f3e6ab599472d1ba6be65eda449a867bb66ec35bf55c88d45d8e843bb7'
    new=(here/'run_closing.py').read_text();before,after=ast.parse(old),ast.parse(new)
    functions=lambda tree:{n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    a,b=functions(before),functions(after)
    for name in ('contacts','admission','qangle','interpolate','construct','factory','loader'):
        assert ast.dump(a[name])==ast.dump(b[name]),name
    select=lambda function:next(n for n in function.body if isinstance(n,ast.If) and "args.mode == 'pick'"==ast.unparse(n.test))
    assert ast.dump(select(a['run']))==ast.dump(select(b['run'])),'Sensor selection changed'
    loop=lambda function:next(n for n in ast.walk(function) if isinstance(n,ast.While))
    oldloop,newloop=loop(a['run']),loop(b['run'])
    labels={'finger_actual_speed','finger_actual_travel','TCP_actual_speed','TCP_tracking','unexpected_early_contact'}
    guards=lambda node:[ast.dump(n) for n in node.body if isinstance(n,ast.If) and any(isinstance(v,ast.Constant) and isinstance(v.value,str) and v.value in labels for v in ast.walk(n))]
    assert guards(oldloop)==guards(newloop),'Original inline motion/early-contact guards changed'
    row=lambda node:next(n for n in node.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='row' for t in n.targets))
    assert ast.dump(row(oldloop))==ast.dump(row(newloop)),'Online data schema changed'
    # No post-observation native identity can influence command/phase decisions.
    native_names={'native','native_path','_discarded_packet','native_index','role_paths','actor_sides'}
    for n in ast.walk(newloop):
        if isinstance(n,ast.If):assert not any(isinstance(v,ast.Name) and v.id in native_names for v in ast.walk(n.test))
    for n in ast.walk(b['run']):
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='phase' for t in n.targets):
            assert not isinstance(n.value,ast.Constant) or n.value.value not in ('lift','hold')
    first=next(i for i,n in enumerate(newloop.body) if isinstance(n,ast.If) and 'sampled_force_stop_N' in ast.unparse(n.test))
    last=next(i for i,n in enumerate(newloop.body) if isinstance(n,ast.If) and ast.unparse(n.test)=='diagnostic_stop')
    block=ast.fix_missing_locations(ast.Module(body=[ast.While(test=ast.Constant(True),body=newloop.body[first:last+1]+[ast.Break()],orelse=[])],type_ignores=[]))
    for reasons,force,close,step,expected in [(['unqualified_contact_right'],.1,400,1800,'old_guard_abort'),
            ([],.1,1,1,'diagnostic_force_cap'),([],.01,400,1,'diagnostic_close_step_cap'),([],.01,1,1800,'diagnostic_total_step_cap')]:
        ns={'forces':{'left':force,'right':0.},'diagnostic':{'sampled_force_stop_N':.1,'maximum_close_steps':400,'maximum_physics_steps':1800},
            'closing_steps':close,'step':step,'diagnostic_stop':[],'reasons':reasons,'stop':[],'status':'running','termination':None}
        exec(compile(block,'<actual-stop-producer>','exec'),ns)
        assert ns['termination']==expected
        if reasons:assert len(ns['diagnostic_stop'])==3 and ns['stop']==reasons
    compile(new,'run_closing.py','exec')
    print('PASS: immutable1809 contact/control/selection/guard/row AST, no native-control branch, no lift, actual stop precedence')


if __name__=='__main__':main()

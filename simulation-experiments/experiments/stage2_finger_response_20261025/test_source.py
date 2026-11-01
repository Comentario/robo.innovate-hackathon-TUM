"""Full-source guard-only equivalence and tiny phase/frozen-target regressions."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent


def dump(node):return ast.dump(node,include_attributes=False)
def named(tree,kind,name):return next(n for n in ast.walk(tree) if isinstance(n,kind) and n.name==name)
def speed_if(tree):
    return next(n for n in ast.walk(tree) if isinstance(n,ast.If) and len(n.body)==1 and isinstance(n.body[0],ast.Expr) and isinstance(n.body[0].value,ast.Call) and any(isinstance(a,ast.Constant) and a.value=='finger_actual_speed' for a in n.body[0].value.args))


def main():
    plan=json.loads((HERE/'protocol.json').read_text());base=Path(plan['original_trial_source']['path']);margin=Path(plan['original_margin_wrapper']['path'])
    assert hashlib.sha256(base.read_bytes()).hexdigest()==plan['original_trial_source']['sha256']=='e5e8323cb111f216527c9e37dd3582fb3be4a66690953160e6656e3e2eac81a5'
    assert hashlib.sha256(margin.read_bytes()).hexdigest()==plan['original_margin_wrapper']['sha256']
    old=ast.parse(base.read_text());new=ast.parse((HERE/'newtrial.py').read_text())
    old_guard=speed_if(old);new_guard=speed_if(new)
    assert dump(ast.Module(body=new_guard.body,type_ignores=[]))==dump(ast.Module(body=old_guard.body,type_ignores=[]))
    assert 'finger_response_limit' in ast.unparse(new_guard.test)
    normalized=copy.deepcopy(new);normalized.body=[n for n in normalized.body if not isinstance(n,ast.FunctionDef) or n.name!='response_limits']
    run=named(normalized,ast.FunctionDef,'run')
    start=next(i for i,n in enumerate(run.body) if isinstance(n,ast.Import) and any(a.name=='inspect' for a in n.names))
    end=next(i for i,n in enumerate(run.body) if i>=start and isinstance(n,ast.Expr) and any(isinstance(a,ast.Constant) and a.value=='finger_response_initial.json' for a in ast.walk(n)))
    readonly=run.body[start:end+1]
    calls=[ast.unparse(n.func) for node in readonly for n in ast.walk(node) if isinstance(n,ast.Call)]
    assert any(n.endswith('.get_dof_max_velocities') for n in calls) and any(n.endswith('.get_dof_types') for n in calls)
    assert not any('.set_' in n or '.write_' in n or n.endswith('.step') for n in calls)
    run.body[start:end+1]=[]
    class RemoveEvidence(ast.NodeTransformer):
        def visit_Assign(self,node):
            if any(isinstance(t,ast.Name) and t.id=='finger_response_limit' for t in node.targets):return None
            if any(isinstance(t,ast.Subscript) and isinstance(t.value,ast.Name) and t.value.id=='metadata' and isinstance(t.slice,ast.Constant) and t.slice.value in ('finger_response','finger_response_file') for t in node.targets):return None
            return self.generic_visit(node)
        def visit_If(self,node):
            if dump(node.test)==dump(new_guard.test):return copy.deepcopy(old_guard)
            return self.generic_visit(node)
        def visit_Dict(self,node):
            keep=[i for i,k in enumerate(node.keys) if not isinstance(k,ast.Constant) or k.value not in ('finger_response_limit_m_s','old_2mm_speed_crossing')]
            node.keys=[node.keys[i] for i in keep];node.values=[node.values[i] for i in keep]
            return self.generic_visit(node)
    normalized=RemoveEvidence().visit(normalized)
    assert dump(normalized)==dump(old),'A trial/factory/controller/contact change exists outside the declared guard/readback/logging delta'
    wrapper=ast.parse((HERE/'run_fixture.py').read_text());previous=ast.parse(margin.read_text())
    assert dump(named(wrapper,ast.ClassDef,'MarginTool'))==dump(named(previous,ast.ClassDef,'MarginTool')),'BODY authoring/readbacks changed'
    scope={'np':np};fn=named(new,ast.FunctionDef,'response_limits');exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'synthetic_guard','exec'),scope)
    limits=scope['response_limits'];command=np.float32(.005593305453658104);commands=np.array([command,command]);before=commands.copy();admission={'command_q_m':float(command)}
    for phase in ('control','close'):np.testing.assert_array_equal(limits(phase,[.2,.01],commands,None),[.002,.002])
    for phase in ('lift','hold'):np.testing.assert_array_equal(limits(phase,[.2,.01],commands,admission),[.02,.01])
    for phase,target,record in [('approach',commands,admission),('lift',commands,None),('hold',np.array([np.nextafter(command,np.float32(np.inf)),command]),admission)]:
        try:limits(phase,[.2,.2],target,record)
        except RuntimeError:pass
        else:raise AssertionError('Unknown phase/missing admission/changed command accepted')
    np.testing.assert_array_equal(commands,before)
    print('PASS: full1822 AST differs only declared guard/readbacks/logs; identical margin model; phase/asset caps and exact frozen targets')


if __name__=='__main__':main()

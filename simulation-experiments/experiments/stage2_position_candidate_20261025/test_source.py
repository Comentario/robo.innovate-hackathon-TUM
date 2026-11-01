"""Small source/state-machine regression; no simulator or saved sensor arrays."""
import ast
import copy
import hashlib
from pathlib import Path
import numpy as np


def main():
    here=Path(__file__).resolve().parent;root=here.parents[1]
    parent=(root/'experiments/stage2_plane_pick_20261025/run_pick.py').read_bytes()
    assert hashlib.sha256(parent).hexdigest()=='934bd1b818c1a060d30f4ad3d80d6c62d6cacff5e8afed27f21abf4936e945d3'
    source=(here/'run_pick.py').read_text()
    functions=lambda tree:{n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    old,new=functions(ast.parse(parent)),functions(ast.parse(source))
    for name in ('contacts','admission','qangle','interpolate','construct','factory','loader'):
        assert ast.dump(old[name])==ast.dump(new[name]),name
    selection=lambda f:next(n for n in f.body if isinstance(n,ast.If) and ast.unparse(n.test)=="args.mode == 'pick'")
    assert ast.dump(selection(old['run']))==ast.dump(selection(new['run']))
    loop=lambda f:next(n for n in ast.walk(f) if isinstance(n,ast.While))
    a,b=loop(old['run']),loop(new['run'])
    labels={'finger_actual_speed','finger_actual_travel','TCP_actual_speed','TCP_tracking','unexpected_early_contact'}
    guards=lambda node:[ast.dump(n) for n in node.body if isinstance(n,ast.If) and any(isinstance(v,ast.Constant) and isinstance(v.value,str) and v.value in labels for v in ast.walk(n))]
    assert guards(a)==guards(b)
    early=lambda node:next(n for n in ast.walk(node) if isinstance(n,ast.If) and ast.unparse(n.test)=="positive >= plan['grasp_confirmation_consecutive_steps']")
    before,after=early(a),copy.deepcopy(early(b))
    after.body=[n for n in after.body if not (isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='lift_admission' for t in n.targets))]
    assert ast.dump(before.test)==ast.dump(after.test)
    assert [ast.dump(n) for n in before.body]==[ast.dump(n) for n in after.body]
    for n in ast.walk(b):
        if isinstance(n,ast.If):assert not any(isinstance(v,ast.Name) and v.id in {'native','native_path','_discarded_packet','native_index','role_paths'} for v in ast.walk(n.test))
    targets=lambda n:{t.id for t in n.targets if isinstance(t,ast.Name)} if isinstance(n,ast.Assign) else set()
    start=next(i for i,n in enumerate(b.body) if 'actual_finger_q' in targets(n))
    end=next(i for i,n in enumerate(b.body) if 'old_finite_reasons' in targets(n))
    sample=compile(ast.fix_missing_locations(ast.Module(body=b.body[start:end],type_ignores=[])),'<actual-sample>','exec')
    transition=next(n for n in ast.walk(b) if isinstance(n,ast.If) and ast.unparse(n.test)=="phase == 'close'" and any(isinstance(v,ast.Name) and v.id=='positive' for v in ast.walk(n)))
    decide=compile(ast.fix_missing_locations(ast.Module(body=[transition],type_ignores=[])),'<actual-transition>','exec')
    q=float(np.float32(.00559331))
    def case():
        return {'np':np,'phase':'close','closing_state':'endpoint_settle','reasons':[],
            'state':{'q':[0.]*7+[q+10e-6,q+10e-6]},'commanded':{'joint_commands':[0.]*7+[q,q]},'finger_ids':[7,8],
            'derived':{'gap_intercept_m':.00281338,'fingers':{'left':{'opening_axis_hand':[0,1,0]},'right':{'opening_axis_hand':[0,-1,0]}}},
            'plan':{'position_contact_floor_N':1e-6,'blocked_finger_allowance_m':2e-6,'blocked_gap_allowance_m':4e-6,'candidate_consecutive_steps':3,
                'endpoint_settle_steps':30,'grasp_confirmation_N':1.5,'grasp_confirmation_consecutive_steps':3,'commanded_lift_m':.005},
            'forces':{'left':.1,'right':.1},'position_count':0,'position_window':[],'position_candidate':None,'lift_admission':None,
            'confirmation':None,'positive':0,'endpoint_commands':0,'finger_command':q,'post':np.array([0,0,.1,1,0,0,0.]),'status':'running','stop':[]}
    ns=case()
    for step in (28,29,30):
        ns.update(step=step,endpoint_commands=step);exec(sample,ns)
        if step==29:
            exec(decide,ns);assert ns['phase']=='close'  # No early position transition.
    exec(decide,ns)
    assert ns['phase']=='lift' and ns['confirmation'] is None
    assert ns['position_candidate']['status']=='GRASP_CANDIDATE' and ns['lift_admission']['kind']=='position_candidate'
    assert ns['finger_command']==q and [r['step'] for r in ns['position_candidate']['window']]==[28,29,30]
    for defect in ('one_finger','one_force','not_endpoint','old_guard'):
        bad=case();bad.update(step=30,endpoint_commands=30)
        if defect=='one_finger':bad['state']['q'][7]=q+1e-6
        elif defect=='one_force':bad['forces']['right']=0.
        elif defect=='not_endpoint':bad['closing_state']='ramp'
        else:bad['reasons']=['unqualified_contact_left']
        exec(sample,bad);assert not bad['position_sample'] and bad['position_count']==0
    ns=case()
    for step in (28,29,30):
        ns.update(step=step,endpoint_commands=step)
        ns['forces']['right']=0. if step==29 else .1
        exec(sample,ns)
    exec(decide,ns)
    assert ns['status']=='endpoint_without_position_candidate' and ns['phase']=='close'
    assert ns['position_count']==1  # Failed middle sample must reset, not be omitted.
    ns=case();ns.update(step=1,endpoint_commands=0,closing_state='ramp',positive=2,forces={'left':1.5,'right':1.5})
    exec(decide,ns)
    assert ns['phase']=='lift' and ns['confirmation'] is not None and ns['position_candidate'] is None
    assert ns['lift_admission']['kind']=='force_confirmation'
    compile(source,'run_pick.py','exec')
    print('PASS: frozen contacts/control/early-force branch; three fresh bilateral endpoint samples; last-command freeze; no extra wait/native oracle')


if __name__=='__main__':main()

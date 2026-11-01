"""Tiny unordered-runtime-contract tests; no Isaac or saved-data imports."""
import ast
import copy
from pathlib import Path
import numpy as np
from run_fixture import multiset_checks,canonical_views,SCHEMA_NAMES


def views():
    result={}
    for side in ('left','right','coupon'):
        n=2 if side=='coupon' else 5
        arrays={'material_properties':np.array([[[.5,.5,0.]]*n],np.float32),
            'contact_offsets':np.full((1,n),.0013625002466142178,np.float32),'rest_offsets':np.zeros((1,n),np.float32)}
        result[side]={'prim_paths':['/'+side],'count':1,'max_shapes':n,'getters':{key:{'status':'AVAILABLE','values':a.tolist(),'shape':list(a.shape),'dtype':str(a.dtype)} for key,a in arrays.items()}}
    return result


def main():
    baseline=views();current=copy.deepcopy(baseline)
    for side in ('left','right'):current[side]['getters']['contact_offsets']['values'][0][-1]=float(np.float32(.0001))
    assert all(multiset_checks(current,baseline,.0001,1e-8).values())
    shuffled=copy.deepcopy(current)
    for side in ('left','right'):
        for value in shuffled[side]['getters'].values():value['values'][0].reverse()
    assert all(multiset_checks(shuffled,baseline,.0001,1e-8).values())
    assert canonical_views(current)==canonical_views(shuffled),'Row ordering must stay unassigned'
    for side,kind,newvalue in [('left','contact_offsets',.0001),('coupon','contact_offsets',.0001),('right','rest_offsets',.0001),('left','material_properties',[.9,.5,0.])]:
        bad=copy.deepcopy(current);bad[side]['getters'][kind]['values'][0][0]=newvalue
        assert not all(multiset_checks(bad,baseline,.0001,1e-8).values()),(side,kind)
    bad=copy.deepcopy(current);bad['left']['getters']['contact_offsets']['status']='UNAVAILABLE'
    assert not all(multiset_checks(bad,baseline,.0001,1e-8).values())
    source=ast.parse((Path(__file__).parent/'run_fixture.py').read_text())
    assert not any(isinstance(n,ast.While) for n in ast.walk(source)),'The measured trial must not be copied'
    calls=[ast.unparse(n.func) for n in ast.walk(source) if isinstance(n,ast.Call)]
    assert 'parent.main' in calls and 'super().author' in calls
    assert calls.count('api.CreateContactOffsetAttr')==1
    assert not any('set_material' in name or 'set_rest' in name or 'set_contact' in name or 'write_root' in name or 'write_joint' in name or name.endswith('.step') for name in calls)
    assert SCHEMA_NAMES=={'physxCollision:contactOffset','physxCollision:restOffset','physxCollision:torsionalPatchRadius','physxCollision:minTorsionalPatchRadius'}
    print('PASS: one-slot offset delta, unordered rows, forbidden deltas/getter failure rejection and imported trial source')


if __name__=='__main__':main()

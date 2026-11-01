"""Small fake-view and hook tests; never imports Isaac or saved experiment data."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from readback import capture_view,getter_record,replace_hook


class View:
    prim_paths=['/known/body'];count=1;max_shapes=2
    def get_material_properties(self):return np.array([[[.5,.4,0.],[2.5,2.,0.]]],dtype=np.float32)
    def get_contact_offsets(self):raise RuntimeError('Synthetic getter unavailable')
    def get_rest_offsets(self):return np.array([[0.,.001]],dtype=np.float32)


def main():
    view=View();sim=SimpleNamespace(physics_sim_view=SimpleNamespace(create_rigid_body_view=lambda path:view))
    result=capture_view(sim,'/known/body')
    assert result['count']==1 and result['max_shapes']==2 and result['row_to_collider_mapping']=='UNKNOWN'
    assert result['getters']['material_properties']['shape']==[1,2,3]
    assert result['getters']['material_properties']['dtype']=='float32'
    assert result['getters']['contact_offsets']['status']=='UNAVAILABLE'
    assert result['getters']['rest_offsets']['status']=='AVAILABLE'
    nonfinite=getter_record(SimpleNamespace(get_bad=lambda:np.array([np.nan])),'get_bad')
    assert nonfinite['status']=='UNAVAILABLE' and nonfinite['values'] is None and 'Nonfinite' in nonfinite['error']
    json.dumps({'view':result,'nonfinite':nonfinite},allow_nan=False)
    seen=[]
    def trial(**context):raise AssertionError('Original measured trial must never execute')
    def original(*args,postassembly_hook=None,**kwargs):
        seen.append((args,kwargs));return postassembly_hook(robot='synthetic',sim='unadvanced')
    def read_hook(original_trial,context):
        assert original_trial is trial and context=={'robot':'synthetic','sim':'unadvanced'};return 'readback-only'
    assert replace_hook(original,read_hook)('unchanged',postassembly_hook=trial,case_adapter=None)=='readback-only'
    assert seen==[(('unchanged',),{'case_adapter':None})]
    source=ast.parse((Path(__file__).parent/'readback.py').read_text())
    calls=[ast.unparse(n.func) for n in ast.walk(source) if isinstance(n,ast.Call)]
    assert not any('.set_' in name or name.endswith('.step') or 'write_root' in name or 'write_joint' in name for name in calls)
    print('PASS: independent getter failures/nonfinite handling, strict JSON, unmapped rows, trial-hook replacement and no setters/steps')


if __name__=='__main__':main()

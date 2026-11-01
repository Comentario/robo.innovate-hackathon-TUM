"""Tiny Python method-hook proof; no USD, Kit or saved runtime values."""
import ast
import importlib
from pathlib import Path
import sys
from types import ModuleType
from readback import wrap_author,COUPON


def main():
    events=[]
    class Tool:
        def author(self,stage,scene,output):
            events.append(('original',stage,scene,output));return 'original-return'
    module=ModuleType('_synthetic_material_tool_cache');module.Tool=Tool;sys.modules[module.__name__]=module
    original=Tool.author
    def correction(tool,stage,scene,output):
        assert type(tool) is Tool and events==[('original','stage','scene','output')]
        events.append(('coupon-only',COUPON))
    try:
        Tool.author=wrap_author(original,correction)
        second_import=importlib.import_module(module.__name__)
        assert second_import.Tool is Tool
        assert second_import.Tool().author('stage','scene','output')=='original-return'
        assert events==[('original','stage','scene','output'),('coupon-only','/World/envs/env_0/contact_coupon')]
    finally:
        Tool.author=original;del sys.modules[module.__name__]
    assert Tool.author is original
    source=ast.parse((Path(__file__).parent/'readback.py').read_text())
    calls=[ast.unparse(n.func) for n in ast.walk(source) if isinstance(n,ast.Call)]
    assert calls.count('base.main')==1 and 'parent.main' not in calls
    assert not any('set_material' in name or 'set_contact' in name or 'set_rest' in name or 'write_root' in name or 'write_joint' in name or name.endswith('.step') for name in calls)
    binding=next(n for n in ast.walk(source) if isinstance(n,ast.Call) and ast.unparse(n.func)=='helper.bind_declared_materials')
    assert isinstance(binding.args[1],ast.Name) and binding.args[1].id=='COUPON'
    assert any(k.arg=='pre_initialization' and isinstance(k.value,ast.Constant) and k.value.value is True for k in binding.keywords)
    assert not any(isinstance(n,ast.FunctionDef) and n.name in ('read_hook','capture_view','usd_inventory') for n in ast.walk(source))
    print('PASS: original author once before coupon-only correction; cached class identity/restoration; immutable readback reused; no trial or physics setters/steps')


if __name__=='__main__':main()

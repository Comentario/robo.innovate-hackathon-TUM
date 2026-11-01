"""Tiny hook/lifecycle checks; no USD, physics, or experiment data reads."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent


def main():
    spec=importlib.util.spec_from_file_location('declared_material_capture',HERE/'run_fixture.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    calls=[]
    class Tool:
        def author(self,*args):calls.append(('original',args));return 'original_return'
    original_author=Tool.author
    def bridge(*args):calls.append(('new_bridge',args))
    def old_bridge(*args):raise AssertionError('Historical control bridge invoked')
    def save(*args):calls.append(('save',args))
    def original_main():
        assert parent.verify_fresh_control is bridge
        assert parent.Tool().author('stage','scene','output')=='original_return'
        parent.save('packet','value');parent.verify_fresh_control('current_control')
        raise RuntimeError('synthetic capture failure')
    parent=SimpleNamespace(Tool=Tool,HERE='old_here',main=original_main,save=save,verify_fresh_control=old_bridge)
    def correction(*args):calls.append(('correction',args[1:]))
    def new_save(*args):calls.append(('new_save',args))
    restore,author=module.install(parent,correction,bridge,new_save)
    class UnchangedMarginTool(Tool):pass
    parent.Tool=UnchangedMarginTool;parent.HERE='new_here'
    parent.verify_fresh_control=old_bridge  # unchanged wrapper's historical assignment
    try:parent.main()
    except RuntimeError as error:assert str(error)=='synthetic capture failure'
    else:raise AssertionError('Synthetic exception lost')
    finally:restore()
    assert [row[0] for row in calls]==['original','correction','new_save','new_bridge']
    assert parent.Tool is Tool and Tool.author is original_author is author
    assert parent.HERE=='old_here' and parent.main is original_main and parent.save is save and parent.verify_fresh_control is old_bridge
    tree=ast.parse((HERE/'run_fixture.py').read_text())
    functions=[n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)]
    assert not any(n.name in ('run','response_limits','fixture_design','contacts') for n in functions)
    calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
    assert not any('set_joint' in call or 'write_' in call or call.endswith('.step') for call in calls)
    assert not any(isinstance(n,ast.ClassDef) for n in ast.walk(tree))
    assert {'helper.bind_declared_materials','base.main','base.canonical_views','snapshotter.snapshot'}<=calls
    source=(HERE/'run_fixture.py').read_text()
    for evidence in ('capture_metadata_sha256','same_current_protocol','binding_schema_unchanged','same_declared_authoring','ROBO_PUEUE_JOB'):
        assert evidence in source
    print('PASS: original author once, correction once, current control bridge; all hooks restored on failure; no trial/controller/physics copy')


if __name__=='__main__':main()

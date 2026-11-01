"""One declared-material regression; immutable1825 trial and margin wrapper."""
import argparse
import inspect
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
COUPON='/World/envs/env_0/contact_coupon'


def install(parent,correction,bridge,save):
    """Return an exact restoration callback for the three local hooks."""
    tool=parent.Tool;author=tool.author;main=parent.main;old_save=parent.save
    old_bridge=parent.verify_fresh_control;old_here=parent.HERE
    def wrapped_author(self,stage,scene,output):
        result=author(self,stage,scene,output)
        correction(self,stage,scene,output)
        return result
    def wrapped_main():
        # The unchanged margin wrapper installs its historical bridge first.
        parent.verify_fresh_control=bridge
        return main()
    tool.author=wrapped_author;parent.main=wrapped_main;parent.save=save
    def restore():
        tool.author=author;parent.Tool=tool;parent.HERE=old_here;parent.main=main;parent.save=old_save
        parent.verify_fresh_control=old_bridge
    return restore,author


def main():
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    parser.add_argument('--protocol',type=Path,default=HERE/'protocol.json')
    args,remaining=parser.parse_known_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    if args.protocol.resolve()!=(HERE/'protocol.json').resolve():raise RuntimeError('Frozen local protocol required')
    plan=json.loads(args.protocol.read_text())
    if plan['execution_authorized'] is not True:raise RuntimeError('Material baseline is not authorized')
    import hashlib,importlib.util
    def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    def load(record,name):
        path=Path(record['path'])
        if sha(path)!=record['sha256']:raise RuntimeError('Changed pinned source: '+name)
        spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module
    def pin(path):return {'path':str(Path(path).resolve()),'sha256':sha(path)}
    base=load(plan['immutable_margin_wrapper'],'declared1825_margin')
    parent=load(plan['parent_runner'],'declared1825_trial')
    snapshotter=load(plan['binding_snapshot_helper'],'declared1828_snapshot')
    original_load=base.load;original_here=base.HERE;original_argv=sys.argv
    original_save=parent.save;stage_context={}
    paths=[COUPON+'/'+name for name in ('BodyCollider','TopCollider','DeclaredContactMaterials',
                                      'DeclaredContactMaterials/Body','DeclaredContactMaterials/Top')]
    def schema(stage):
        inventory=snapshotter.snapshot(stage)
        return {path:inventory[path] for path in paths}
    def save(path,packet):
        name=Path(path).name
        if name=='capture_metadata.json':
            packet={**packet,'binding_authoring_file':plan['binding_authoring_file'],
                    'binding_helper_sha256':plan['binding_helper']['sha256'],
                    'material_protocol_sha256':sha(args.protocol)}
        if name in ('margin_readback_initial.json','margin_readback_terminal.json'):
            actual=schema(stage_context['stage']);expected=stage_context['expected_schema']
            if actual!=expected:raise RuntimeError('Coupon material schema changed after authoring')
            packet={**packet,'binding_schema':actual,'binding_schema_unchanged':True,
                    'material_settings_changed_reference':'corrected1828_baseline',
                    'material_model_changed_from_1825':True}
        return original_save(path,packet)
    def correction(tool,stage,scene,output):
        from pxr import UsdPhysics
        helper_path=HERE/'materials.py'
        helper=load({'path':str(helper_path),'sha256':plan['binding_helper']['sha256']},'declared1827_binding')
        before=snapshotter.snapshot(stage)
        report=helper.bind_declared_materials(stage,COUPON,pre_initialization=True)
        after=snapshotter.snapshot(stage);density={}
        for target in report['targets'].values():
            attr=UsdPhysics.MaterialAPI(stage.GetPrimAtPath(target['material_path'])).GetDensityAttr()
            density[target['material_path']]={'value':attr.Get(),'has_authored_value':bool(attr.HasAuthoredValueOpinion())}
        payload={'timing':'pre_initialization','helper_pin':plan['binding_helper'],'actual_helper_copy':pin(helper_path),
            'hook':{'kind':'process_local_inherited_Tool.author_wrapper','class_module':parent.Tool.__module__,
                'class_name':parent.Tool.__name__,'runtime_class_name':type(tool).__name__,
                'class_identity_unchanged':isinstance(tool,parent.Tool),'original_method_source':pin(inspect.getfile(original_author)),
                'wrapper_source':pin(__file__)},'report':report,'before':before,'after':after,'density_defaults':density}
        original_save(Path(output)/plan['binding_authoring_file'],payload)
        stage_context.update(stage=stage,expected_schema={path:after[path] for path in paths})
    def fresh_control(audit_path,capture,current,initial,observer,fixture,new_plan,output):
        audit=json.loads(audit_path.read_text());meta=json.loads((capture/'capture_metadata.json').read_text())
        margin=json.loads((capture/'margin_readback_initial.json').read_text());live=json.loads((output/'margin_readback_initial.json').read_text())
        old_binding=json.loads((capture/plan['binding_authoring_file']).read_text());new_binding=json.loads((output/plan['binding_authoring_file']).read_text())
        digest=sha(args.protocol)
        checks={'passed_fresh_control':audit.get('proceed_gate_passed') is True and meta['mode']=='control' and meta['steps_executed']==plan['control_steps'],
            'control_capture_binding':Path(audit['capture_directory']).resolve()==capture.resolve() and audit['capture_metadata_sha256']==sha(capture/'capture_metadata.json'),
            'same_current_protocol':meta['contact_policy_protocol_sha256']==meta['margin_protocol_sha256']==meta['material_protocol_sha256']==digest,
            'physical_settings':meta['settings_initial']==current,'initial_q':meta['initial_joint_positions']==initial['q'],
            'fixture':fixture==json.loads((capture/'fixture_initial.json').read_text()),
            'raw_observer':observer==json.loads((capture/'contact_observations/metadata.json').read_text()),
            'combined_runtime_bags':margin['passed'] is True and live['passed'] is True and margin['baseline_readback_sha256']==live['baseline_readback_sha256'] and base.canonical_views(margin['views'])==base.canonical_views(live['views']),
            'binding_schema':margin['binding_schema_unchanged'] is True and live['binding_schema_unchanged'] is True and margin['binding_schema']==live['binding_schema'],
            'same_declared_authoring':old_binding==new_binding and meta['binding_helper_sha256']==plan['binding_helper']['sha256']}
        save(output/'control_bridge.json',{'passed':all(checks.values()),'checks':checks,'control_protocol_sha256':digest,
            'control_audit_sha256':sha(audit_path),'control_capture_metadata_sha256':sha(capture/'capture_metadata.json'),
            'control_capture_directory':str(capture.resolve())})
        if not all(checks.values()):raise RuntimeError('Fresh declared-material control bridge failed')
    restore,original_author=install(parent,correction,fresh_control,save)
    def module_load(record,name):
        if name=='frozen1822_margin_parent':
            if record!=plan['parent_runner']:raise RuntimeError('Unexpected trial source request')
            return parent
        return original_load(record,name)
    base.load=module_load;base.HERE=HERE
    sys.argv=[sys.argv[0],*remaining,'--protocol',str(args.protocol)]
    try:base.main()
    finally:
        restore();base.load=original_load;base.HERE=original_here;sys.argv=original_argv


if __name__=='__main__':main()

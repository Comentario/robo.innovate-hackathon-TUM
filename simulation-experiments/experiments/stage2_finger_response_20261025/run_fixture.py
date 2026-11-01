"""Verified BODY-margin model with a guard-only trial-source fork."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
SCHEMA_NAMES={'physxCollision:contactOffset','physxCollision:restOffset',
              'physxCollision:torsionalPatchRadius','physxCollision:minTorsionalPatchRadius'}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def load(record,name):
    path=Path(record['path']);path=path if path.is_absolute() else ROOT/path
    if sha(path)!=record['sha256']:raise RuntimeError('Changed pinned source: '+name)
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def multiset_checks(views,baseline,target,tolerance):
    checks={}
    for side in ('left','right','coupon'):
        now,old=views[side],baseline[side]
        checks[side+'_binding']=now['prim_paths']==old['prim_paths'] and now['count']==old['count']==1 and now['max_shapes']==old['max_shapes']==(2 if side=='coupon' else 5)
        for kind in ('material_properties','contact_offsets','rest_offsets'):
            a,b=now['getters'][kind],old['getters'][kind]
            valid=a['status']==b['status']=='AVAILABLE' and a['shape']==b['shape'] and a['dtype']==b['dtype']
            if valid:
                actual=np.asarray(a['values'],float);expected=np.asarray(b['values'],float)
                if kind=='material_properties':valid=sorted(map(tuple,actual.reshape(-1,3)))==sorted(map(tuple,expected.reshape(-1,3)))
                else:
                    expected=expected.ravel().copy()
                    if kind=='contact_offsets' and side!='coupon':
                        if not np.all(expected==expected[0]):raise RuntimeError('Baseline finger offset is not uniform')
                        expected[0]=float(np.float32(target))
                    valid=bool(np.allclose(np.sort(actual.ravel()),np.sort(expected),atol=tolerance if kind=='contact_offsets' else 0,rtol=0))
            checks[side+'_'+kind]=bool(valid)
    return checks


def canonical_views(views):
    return {side:{'prim_paths':v['prim_paths'],'count':v['count'],'max_shapes':v['max_shapes'],
        'materials':sorted(map(tuple,np.asarray(v['getters']['material_properties']['values']).reshape(-1,3))),
        'contact_offsets':sorted(np.asarray(v['getters']['contact_offsets']['values']).ravel().tolist()),
        'rest_offsets':sorted(np.asarray(v['getters']['rest_offsets']['values']).ravel().tolist())} for side,v in views.items()}


def attributes(prim,authored_only=False):
    result={}
    for attr in prim.GetAttributes():
        if authored_only and not attr.HasAuthoredValueOpinion():continue
        value=attr.Get()
        if isinstance(value,float) and not math.isfinite(value):value={'nonfinite_scalar':'nan' if math.isnan(value) else 'inf' if value>0 else '-inf'}
        elif value is not None and not isinstance(value,(float,int,bool,str)):value=str(value)
        result[attr.GetName()]={'usd_type':str(attr.GetTypeName()),'sdk_value':value}
    return result


def main():
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False);parser.add_argument('--protocol',type=Path,default=HERE/'protocol.json')
    args,remaining=parser.parse_known_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    if args.protocol.resolve()!=(HERE/'protocol.json').resolve():raise RuntimeError('Use the frozen local protocol')
    plan=json.loads(args.protocol.read_text())
    if plan['execution_authorized'] is not True:raise RuntimeError('Margin sensitivity is not authorized')
    if sha(plan['collision_schema']['path'])!=plan['collision_schema']['sha256']:raise RuntimeError('Changed installed collision schema')
    helper=load(plan['readback_helper'],'frozen1823_margin_readback');parent=load(plan['parent_runner'],'frozen1822_margin_parent')
    if sha(plan['baseline_readback']['path'])!=plan['baseline_readback']['sha256']:raise RuntimeError('Changed baseline readback')
    baseline=json.loads(Path(plan['baseline_readback']['path']).read_text());original_tool=parent.Tool;original_save=parent.save
    def save(path,packet):
        if Path(path).name=='capture_metadata.json':packet={**packet,'margin_authoring_file':'margin_authoring.json',
            'margin_readback_initial_file':'margin_readback_initial.json','margin_readback_terminal_file':'margin_readback_terminal.json','margin_protocol_sha256':sha(args.protocol)}
        return original_save(path,packet)
    class MarginTool(original_tool):
        def author(self,stage,scene,output):
            from pxr import PhysxSchema
            super().author(stage,scene,output);records={}
            names=set(map(str,PhysxSchema.PhysxCollisionAPI.GetSchemaAttributeNames()))
            if names!=SCHEMA_NAMES:raise RuntimeError('Unexpected installed collision schema attributes')
            for side,path in plan['expected_body_paths'].items():
                if path!=self.records[side]['parts']['body']['path']:raise RuntimeError('Exact BODY authoring path differs')
                prim=stage.GetPrimAtPath(path);before=attributes(prim);authored=attributes(prim,True)
                old_value=before.get('physxCollision:contactOffset');schemas=list(prim.GetAppliedSchemas())
                api=PhysxSchema.PhysxCollisionAPI.Apply(prim);api.CreateContactOffsetAttr(plan['body_contact_offset_m'])
                after=attributes(prim);other=attributes(prim,True);authored.pop('physxCollision:contactOffset',None);other.pop('physxCollision:contactOffset',None)
                added=set(prim.GetAppliedSchemas())-set(schemas)
                defaults={name:value for name,value in after.items() if name not in before and name!='physxCollision:contactOffset'}
                if authored!=other or added-{'PhysxCollisionAPI'} or set(schemas)-set(prim.GetAppliedSchemas()) or any(value!=plan['allowed_unauthored_collision_defaults'].get(name) for name,value in defaults.items()) or any(prim.GetAttribute(name).HasAuthoredValueOpinion() for name in defaults):raise RuntimeError('Authoring exceeded the single BODY offset delta')
                records[side]={'path':path,'old_authored_offset':old_value,'new_authored_offset':after['physxCollision:contactOffset'],
                    'applied_schemas_before':schemas,'applied_schemas_after':list(prim.GetAppliedSchemas()),
                    'newly_exposed_unauthored_defaults':defaults,'other_authored_attributes_unchanged':True,
                    'other_authored_before_sha256':hashlib.sha256(json.dumps(authored,sort_keys=True).encode()).hexdigest(),
                    'other_authored_after_sha256':hashlib.sha256(json.dumps(other,sort_keys=True).encode()).hexdigest()}
            save(output/'margin_authoring.json',{'timing':'pre_initialization','target_contact_offset_m':plan['body_contact_offset_m'],
                'paths':plan['expected_body_paths'],'schema_attribute_names':sorted(SCHEMA_NAMES),'collision_schema':plan['collision_schema'],'records':records})
        def read_margin(self,phase):
            context=self.margin_context;sim=context['sim'];robot=context['robot'];clock=float(sim.current_time);q=robot.data.joint_pos.clone()
            views={side:helper.capture_view(sim,path) for side,path in helper.PATHS.items()}
            checks=multiset_checks(views,baseline['views'],plan['body_contact_offset_m'],plan['runtime_property_tolerance_m'])
            checks['no_time_or_q_change']=float(sim.current_time)==clock and bool((robot.data.joint_pos==q).all())
            record={'phase':phase,'views':views,'baseline_readback_sha256':plan['baseline_readback']['sha256'],
                'checks':checks,'passed':all(checks.values()),'mapping':'UNKNOWN','rest_offset_setting_changed':False,'material_settings_changed':False}
            save(self.output/('margin_readback_'+phase+'.json'),record)
            if not record['passed']:raise RuntimeError('Effective contact/material/rest multisets differ from the one-delta contract')
        def validate(self,context):
            self.margin_context=context;result=super().validate(context);self.read_margin('initial');return result
        def audit(self,stage,output,cooked=None):
            result=super().audit(stage,output,cooked)
            if Path(output).name=='geometry_terminal.json':self.read_margin('terminal')
            return result
    def fresh_control(audit_path,capture,current,initial,observer,fixture,new_plan,output):
        audit=json.loads(audit_path.read_text());meta=json.loads((capture/'capture_metadata.json').read_text());old_fixture=json.loads((capture/'fixture_initial.json').read_text());old_observer=json.loads((capture/'contact_observations/metadata.json').read_text())
        margin=json.loads((capture/'margin_readback_initial.json').read_text());live=json.loads((output/'margin_readback_initial.json').read_text())
        old_protocol=json.loads(Path(new_plan['original_control_protocol']['path']).read_text())
        checks={'passed_fresh_control':audit.get('proceed_gate_passed') is True and meta['mode']=='control' and meta['steps_executed']==new_plan['control_steps'],
            'control_capture_binding':Path(audit['capture_directory']).resolve()==capture.resolve() and audit['capture_metadata_sha256']==sha(capture/'capture_metadata.json'),
            'original_control_pins':sha(audit_path)==new_plan['original_control_audit']['sha256'] and sha(capture/'capture_metadata.json')==new_plan['original_control_metadata']['sha256'] and capture.resolve()==Path(new_plan['original_control_capture_directory']).resolve(),
            'same_protocol':meta['contact_policy_protocol_sha256']==new_plan['original_control_protocol']['sha256'] and meta['margin_protocol_sha256']==new_plan['original_control_protocol']['sha256'] and sha(new_plan['original_control_protocol']['path'])==new_plan['original_control_protocol']['sha256'],
            'unchanged_control_science':all(new_plan[key]==old_protocol[key] for key in new_plan['control_physical_equivalence_keys']),
            'physical_settings':meta['settings_initial']==current,'initial_q':meta['initial_joint_positions']==initial['q'],
            'fixture':fixture==old_fixture,'raw_observer':observer==old_observer,
            'margin_readbacks':margin['passed'] is True and live['passed'] is True and margin['baseline_readback_sha256']==live['baseline_readback_sha256'] and canonical_views(margin['views'])==canonical_views(live['views'])}
        save(output/'control_bridge.json',{'passed':all(checks.values()),'checks':checks,'control_audit_sha256':sha(audit_path),'control_capture_metadata_sha256':sha(capture/'capture_metadata.json')})
        if not all(checks.values()):raise RuntimeError('New matched margin-control bridge failed')
    parent.HERE=HERE;parent.Tool=MarginTool;parent.save=save;parent.verify_fresh_control=fresh_control
    sys.argv=[sys.argv[0],*remaining];parent.main()


if __name__=='__main__':main()

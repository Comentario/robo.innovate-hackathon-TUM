"""Coupon-only pre-init binding; all capture logic is immutable1823 readback."""
import argparse
import hashlib
import importlib.util
import inspect
import json
import math
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
COUPON='/World/envs/env_0/contact_coupon'


def pin(path):
    path=Path(path).resolve();return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def load(path,name,expected):
    if pin(path)['sha256']!=expected:raise RuntimeError('Changed frozen module: '+name)
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def snapshot(stage):
    from pxr import Usd
    result={}
    for prim in Usd.PrimRange(stage.GetPrimAtPath(COUPON),Usd.TraverseInstanceProxies()):
        attrs={}
        for attr in prim.GetAttributes():
            authored=attr.HasAuthoredValueOpinion();connected=attr.HasAuthoredConnections()
            if not authored and not connected:continue
            value=attr.Get()
            if isinstance(value,float) and not math.isfinite(value):value={'nonfinite_scalar':'nan' if math.isnan(value) else 'inf' if value>0 else '-inf'}
            elif value is not None and not isinstance(value,(float,int,bool,str)):value=str(value)
            attrs[attr.GetName()]={'usd_type':str(attr.GetTypeName()),'sdk_value':value,'connections':list(map(str,attr.GetConnections())),
                'has_authored_value':bool(authored),'has_authored_connections':bool(connected)}
        result[str(prim.GetPath())]={'type':prim.GetTypeName(),'apis':list(prim.GetAppliedSchemas()),'attributes':attrs,
            'relationships':{r.GetName():list(map(str,r.GetTargets())) for r in prim.GetRelationships()}}
    return result


def wrap_author(original,correction):
    def author(self,stage,scene,output):
        result=original(self,stage,scene,output)
        correction(self,stage,scene,output)
        return result
    return author


def main():
    parser=argparse.ArgumentParser(add_help=False,allow_abbrev=False)
    parser.add_argument('--protocol',type=Path,default=HERE/'protocol.json');parser.add_argument('--output',type=Path,required=True)
    args,remaining=parser.parse_known_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    protocol=json.loads(args.protocol.read_text())
    if protocol['execution_authorized'] is not True:raise RuntimeError('Runtime readback is not authorized')
    parent_record=protocol['parent_runner'];base_record=protocol['immutable_readback'];helper_record=protocol['binding_helper']
    parent=load(parent_record['path'],'binding1822_parent_preload',parent_record['sha256'])
    base=load(base_record['path'],'binding1823_readback',base_record['sha256'])
    tool_class=parent.Tool;original=tool_class.author
    def correction(tool,stage,scene,output):
        from pxr import UsdPhysics
        if type(tool) is not tool_class:raise RuntimeError('Unexpected runtime Tool class')
        helper_path=HERE/'materials.py';helper=load(helper_path,'frozen1827_coupon_binding',helper_record['sha256'])
        before=snapshot(stage);report=helper.bind_declared_materials(stage,COUPON,pre_initialization=True);after=snapshot(stage)
        density={}
        for record in report['targets'].values():
            attr=UsdPhysics.MaterialAPI(stage.GetPrimAtPath(record['material_path'])).GetDensityAttr()
            density[record['material_path']]={'value':attr.Get(),'has_authored_value':bool(attr.HasAuthoredValueOpinion())}
        payload={'timing':'pre_initialization','helper_pin':helper_record,'actual_helper_copy':pin(helper_path),
            'hook':{'kind':'process_local_Tool.author_wrapper','class_module':tool_class.__module__,'class_name':tool_class.__name__,
                'class_identity_unchanged':type(tool) is tool_class,'original_method_source':pin(inspect.getfile(original)),'wrapper_source':pin(__file__)},
            'report':report,'before':before,'after':after,'density_defaults':density}
        (Path(output)/protocol['binding_authoring_file']).write_text(json.dumps(payload,indent=2,allow_nan=False)+'\n')
    tool_class.author=wrap_author(original,correction)
    sys.argv=[sys.argv[0],*remaining,'--protocol',str(args.protocol.resolve()),'--output',str(args.output.resolve())]
    try:base.main()
    finally:tool_class.author=original


if __name__=='__main__':main()

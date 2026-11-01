"""Queued fixed-file OLD/cached contact-summary equivalence; no simulation."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import numpy as np
HERE=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def encode(value):return json.dumps(value,sort_keys=True,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else x.tolist()).encode()
def arrays_sha(data):
    digest=hashlib.sha256()
    for key,value in data.items():
        digest.update(key.encode());digest.update(value.dtype.str.encode());digest.update(str(value.shape).encode());digest.update(value.tobytes())
    return digest.hexdigest()
def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def run(outputdir,deadline):
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    outputdir=Path(outputdir);outputdir.mkdir(parents=True,exist_ok=True);scope=read(HERE/'cache_scope.json')
    result={'schema':scope['schema'],'completed':False,'all_summaries_exact':False,'all_cached_arrays_unchanged':False,'case_gate_reevaluated':False,'fixtures':[],'timing_scope':scope['order'],'scope_sha256':sha(HERE/'cache_scope.json')}
    started=time.monotonic()
    try:
        old_path=Path(scope['old_helper']);new_path=HERE.parent/'evaluation/contact_helpers.py';protocol_path=HERE.parent/'evaluation/contact_protocol.json'
        for path,digest in [(old_path,scope['old_helper_sha256']),(new_path,scope['new_helper_sha256']),(protocol_path,scope['contact_protocol_sha256']),(Path(scope['old_contact_protocol']),scope['old_contact_protocol_sha256'])]:
            if sha(path)!=digest:raise ValueError('Pinned cache input changed: '+str(path))
        protocol=read(protocol_path)
        if protocol!=read(scope['old_contact_protocol']):raise ValueError('Old/new reporting protocols differ')
        old=load_module('fixed_old_contact_cache',old_path);new=load_module('fixed_new_contact_cache',new_path)
        for fixture in scope['fixtures']:
            if time.monotonic()>=deadline:raise TimeoutError('Shared30s diagnostic deadline exhausted')
            path=Path(fixture['data']);metadata=Path(fixture['metadata'])
            if sha(path)!=fixture['data_sha256'] or sha(metadata)!=fixture['metadata_sha256']:raise ValueError('Pinned fixture changed')
            view=read(metadata)['resolved_views'][fixture['sensor']];paths=old.filter_paths(view);values={}
            for label,module in [('OLD',old),('CACHED',new)]:
                if time.monotonic()>=deadline:raise TimeoutError('Shared30s diagnostic deadline exhausted')
                before=time.monotonic()
                with np.load(path,allow_pickle=False) as raw:
                    cache={key:raw[key].copy() for key in raw.files};initial_sha=arrays_sha(cache)
                    summary=module.view_summary(raw if label=='OLD' else cache,paths,protocol,protocol['unchanged']['dt_s'])
                    terminal_sha=arrays_sha(cache)
                values[label]={'summary':summary,'seconds':time.monotonic()-before,'unchanged':initial_sha==terminal_sha,'arrays_sha256':initial_sha}
            a,b=values['OLD'],values['CACHED'];exact=encode(a['summary'])==encode(b['summary'])
            result['fixtures'].append({'fixture':fixture['fixture'],'step':fixture['step'],'sensor':fixture['sensor'],'input_sha256':fixture['data_sha256'],'summary_exact':exact,'same_input_arrays':a['arrays_sha256']==b['arrays_sha256'],'OLD_arrays_unchanged':a['unchanged'],'CACHED_arrays_unchanged':b['unchanged'],'summary_sha256':hashlib.sha256(encode(a['summary'])).hexdigest(),'OLD_seconds':a['seconds'],'CACHED_seconds':b['seconds'],'has_loaded_rows':any(pair['force_carrying_rows'] for pair in a['summary']['pairs'].values())})
        result.update(completed=True,all_summaries_exact=all(x['summary_exact'] and x['same_input_arrays'] for x in result['fixtures']),all_cached_arrays_unchanged=all(x['OLD_arrays_unchanged'] and x['CACHED_arrays_unchanged'] for x in result['fixtures']),fixed_fixture_count=len(result['fixtures']),OLD_total_seconds=sum(x['OLD_seconds'] for x in result['fixtures']),CACHED_total_seconds=sum(x['CACHED_seconds'] for x in result['fixtures']))
        result['zero_fixture_confirmed']=all(not x['has_loaded_rows'] for x in result['fixtures'] if x['fixture']=='zero_I_control')
        result['loaded_fixture_confirmed']=any(x['has_loaded_rows'] for x in result['fixtures'] if x['fixture']=='loaded_D1791')
        result['equivalence_passed']=result['completed'] and len(result['fixtures'])==len(scope['fixtures']) and all(result[k] for k in ['all_summaries_exact','all_cached_arrays_unchanged','zero_fixture_confirmed','loaded_fixture_confirmed'])
    except Exception as error:result.update(error=repr(error),equivalence_passed=False)
    finally:
        result['wall_seconds']=time.monotonic()-started;result['within_shared_deadline']=time.monotonic()<=deadline
        result['equivalence_passed']=result.get('equivalence_passed',False) and result['within_shared_deadline']
        (outputdir/'cache_comparison.json').write_bytes(encode(result)+b'\n')
    return result

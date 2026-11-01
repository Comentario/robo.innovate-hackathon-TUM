"""Separate saved-JSON adjudication; the original failed audit is immutable."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

HERE=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Default Pueue required')
    plan=json.loads((HERE/'adjudication_protocol.json').read_text())
    if not plan['execution_authorized']:raise RuntimeError('Final source review required')
    started=time.monotonic()
    def unchanged():return all(sha(path)==digest for path,digest in plan['pinned_inputs_sha256'].items())
    if not unchanged() or sha(HERE/'evaluate.py')!=plan['auditor_sha256']:raise RuntimeError('Pinned adjudication input/source changed')
    spec=importlib.util.spec_from_file_location('revised_saved_material_auditor',HERE/'evaluate.py')
    auditor=importlib.util.module_from_spec(spec);spec.loader.exec_module(auditor)
    # Reuse the captured protocol/wrapper provenance, not the new audit location.
    auditor.HERE=Path(plan['captured_code_context'])
    result=auditor.evaluate(Path(plan['original_snapshot'])/'output')
    intact=unchanged()
    result['adjudication']={'original_job_id':1828,'original_overall_result':'FAIL_PRESERVED',
        'saved_inputs_unchanged_before_and_after':intact,'captured_code_context':plan['captured_code_context'],
        'new_auditor_source':{'path':str(HERE/'evaluate.py'),'sha256':sha(HERE/'evaluate.py')},
        'adjudication_protocol_sha256':sha(HERE/'adjudication_protocol.json'),
        'allowed_semantic_changes':plan['allowed_semantic_changes'],
        'schema_relation_authorship_limit':plan['schema_relation_authorship_limit'],
        'simulation_started':False,'physics_steps':0,'retention_claim':False,
        'seconds':time.monotonic()-started}
    args.output.mkdir()
    (args.output/'evaluation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    raise SystemExit(0 if intact and result['runtime_materials_verified'] else 1)


if __name__=='__main__':main()

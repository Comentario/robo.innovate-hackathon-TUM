"""Pure stdlib AST/parser regression; never imports Isaac or executes main()."""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
OUTER=ROOT/'experiments/stage2_exposed_tip_20261025/run_contact.py'
BASE=ROOT/'experiments/stage2_contact_20261025/run_contact.py'
CORE=ROOT/'experiments/final_workcell_20261024/render_core.py'

def parser_from(path,old_abbreviation=False):
    tree=ast.parse(path.read_text());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    nodes=[]
    for node in main.body:
        # Stop before argument parsing, file reads, AppLauncher or other work.
        if any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='parse_known_args' for n in ast.walk(node)):break
        if isinstance(node,ast.If) and any(isinstance(n,ast.Constant) and n.value=='--self-test' for n in ast.walk(node.test)):break
        nodes.append(copy.deepcopy(node))
    if old_abbreviation:
        call=next(n for node in nodes for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='ArgumentParser')
        call.keywords=[k for k in call.keywords if k.arg!='allow_abbrev']
    env={'argparse':argparse,'Path':Path,'__doc__':'AST-only parser check','case_adapter':None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(path)+'-parser-only','exec'),env)
    return env['parser']

def route(phase,old_abbreviation=False):
    argv=['--phase',phase,'--output','/tmp/outer-output','--geometry','/tmp/geometry.json',
          '--cameras','/tmp/cameras.json','--appearance','/tmp/appearance.json','--views','all',
          '--headless','--enable_cameras','--device','cpu','--geometry-audit','/tmp/original-G.json',
          '--side-authorization','/tmp/side_authorization.json']
    if phase=='R':argv+=['--predecessor-D','/tmp/passing-D.json']
    outer,remaining=parser_from(OUTER,old_abbreviation).parse_known_args(argv)
    baseline,remaining=parser_from(BASE).parse_known_args(remaining)
    forwarded=[*remaining,'--output',str(baseline.output.resolve())]
    core,launcher=parser_from(CORE).parse_known_args(forwarded)
    assert outer.geometry_audit==Path('/tmp/original-G.json') and outer.side_authorization==Path('/tmp/side_authorization.json')
    assert phase!='R' or outer.predecessor_D==Path('/tmp/passing-D.json')
    assert core.cameras==Path('/tmp/cameras.json') and core.output==Path('/tmp/outer-output')
    assert core.appearance==Path('/tmp/appearance.json') and core.views=='all'
    assert launcher==['--headless','--enable_cameras','--device','cpu']
    return core

if __name__=='__main__':
    before=route('D',old_abbreviation=True)
    assert before.geometry is None  # Reproduces1788's combined required-argument error.
    for phase in ('D','R'):assert route(phase).geometry==Path('/tmp/geometry.json')
    assert not any(name.startswith(('isaaclab','isaacsim','omni.')) for name in sys.modules)
    evidence={'schema':'exposed-tip-argument-passthrough-v1','before_reproduced_missing_geometry':True,
        'after_D_R_all_renderer_and_evidence_arguments_preserved':True,'Isaac_or_Kit_imported':False,
        'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (OUTER,BASE,CORE)}}
    Path(__file__).with_name('argument_passthrough_result.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('PASS: reproduced1788 geometry abbreviation loss; fixed D/R retain geometry/cameras/output/auth and launcher tokens. No Isaac/Kit imported.')

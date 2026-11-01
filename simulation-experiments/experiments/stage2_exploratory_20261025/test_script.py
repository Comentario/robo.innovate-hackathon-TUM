"""Small source/admission regression test; no Isaac imports or real arrays."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    here=Path(__file__).resolve().parent
    parent=here.parent/'stage2_pick_20261025/run_pick.py'
    old=parent.read_text();new=(here/'run_pick.py').read_text()
    assert hashlib.sha256(parent.read_bytes()).hexdigest()=='221d7e3ebc47d9c464172b2ee1de02d48252a237e92f8c09d958e955345f744d'
    functions=lambda tree:{n.name:n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef)}
    before,after=functions(ast.parse(old)),functions(ast.parse(new))
    for name in ('contacts','qangle','interpolate','factory','loader'):
        assert ast.dump(before[name])==ast.dump(after[name]),name
    loop=lambda function:next(n for n in ast.walk(function) if isinstance(n,ast.While))
    assert ast.dump(loop(before['run']))==ast.dump(loop(after['run'])),'Measured loop changed'
    namespace={}
    exec(compile(ast.Module(body=[after['admission']],type_ignores=[]),'<admission>','exec'),namespace)
    for passed in (False,True,np.bool_(False)):
        raw={'passed':passed,'unknown_samples':10};original=copy.deepcopy(raw)
        result=namespace['admission'](raw,'fixed-authorization')
        assert result['policy']=='simulation_only_finger_contact_guarded'
        assert result['visual_clearance_certified'] is False and result['hardware_use'] is False
        assert result['measured_swept_clearance_passed'] is bool(passed)
        assert result['swept_space_status']=='UNCERTIFIED_UNKNOWN' and raw==original
        json.dumps(result,allow_nan=False)
    protocol=json.loads((here/'protocol.json').read_text())
    proof=(here/'pregrasp_authorization.json').read_bytes()
    assert hashlib.sha256(proof).hexdigest()==protocol['pregrasp_init']['authorization_sha256']
    proof=json.loads(proof)
    assert proof['q']==protocol['pregrasp_init']['q']
    assert proof['joint_names']==protocol['pregrasp_init']['joint_names']
    assert proof['pose_integrity_subset_valid'] is True and proof['original_full_diagnostic_passed'] is False
    compile(new,'run_pick.py','exec')
    print('PASS: unchanged physical loop/helpers; admission strict JSON/immutability; failed-diagnostic posture-only provenance')


if __name__=='__main__':main()

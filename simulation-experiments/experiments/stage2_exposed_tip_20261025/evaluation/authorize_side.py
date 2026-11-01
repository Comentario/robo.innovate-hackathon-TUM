"""Administrative scope authorization from immutable, already-scored G evidence."""
import argparse
import hashlib
import json
from pathlib import Path

G_SHA='9e3f623e8f198f730727159009d0238f37207984bebed4f918505f7d2a731c9c'
POINT_CONTRACT={'flat_face_extra_slack_m':5e-5,'minimum_outward_dot_grip_normal':.9,
    'finger_outward':'negative raw signed force coefficient times world normal',
    'coupon_outward':'positive raw signed force coefficient times world normal',
    'all_abs_force_above_N':1e-8,'Z_cutoff':None,'normal_fitting_or_sign_selection':False}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['geometry-audit','geometry-protocol','model-config','output']:parser.add_argument('--'+key,type=Path,required=True)
    a=parser.parse_args();g=json.loads(a.geometry_audit.read_text());p=json.loads(a.geometry_protocol.read_text())
    if sha(a.geometry_audit)!=G_SHA or sha(a.geometry_protocol)!=g['protocol_sha256']:raise ValueError('Original failed geometry evidence changed')
    if g['phase']!='G' or g['proceed_gate_passed'] is not False or not all(g['checks'].values()):raise ValueError('Expected unchanged integrity-valid FAILED G')
    if sha(a.model_config)!=p['model_config_sha256']:raise ValueError('This is not the original unchanged model')
    expected_false={label+'_'+suffix for label in ['left','right'] for suffix in ['design_clear_100um','source_exposed_clear_100um']}
    if {k for k,v in g['quality_checks'].items() if not v}!=expected_false:raise ValueError('Unexpected unqualified geometry failure')
    exceptions={};coverage={}
    for label,rays in g['rays'].items():
        bad=[r for r in rays if r['reference']['hit'] and r['reference'].get('clear') and (r['actual_firsthit_error_m'] is None or abs(r['actual_firsthit_error_m'])>1e-4)]
        if len(rays)!=106 or not all(r['hit_parity'] for r in rays) or len(bad)!=1 or bad[0]['id']!=label+'_bbox_2_-1' or bad[0]['reference']['normal_finger']!=[0,0,1]:raise ValueError('Failed feature is not the known sole distal axial query')
        other_source_bad=[r['id'] for r in rays if r['source_exterior_reference'] and r['source_exterior_reference'].get('exposed_eligible') and r['source_exterior_reference'].get('clear') and (r['source_exterior_error_m'] is None or abs(r['source_exterior_error_m'])>1e-4)]
        if other_source_bad!=[label+'_bbox_2_-1']:raise ValueError('Additional source-exterior failure')
        exceptions[label]={'probe':bad[0]['id'],'axial_query_retreat_m':bad[0]['actual_firsthit_error_m'],'full_G_100um_condition':'FAILED unchanged'}
        coverage[label]={'all106parities':True,'clear_grip_and_outward_taper':g['quality_checks'][label+'_clear_grip_and_outward_taper']}
    result={'schema':'exposed-tip-lateral-authorization-v1','authorization':'D_then_conditional_R_lateral_only',
        'global_G_passed':False,'geometry_audit_sha256':G_SHA,'original_geometry_protocol_sha256':g['protocol_sha256'],
        'model_config_sha256':sha(a.model_config),'cooked_hashes':g['cooked_hashes'],'existing_attempts_only':True,
        'known_exception':exceptions,'retained_coverage':coverage,'point_contract':POINT_CONTRACT,
        'maximum_D_attempts':1,'maximum_reserved_attempts_after_D_pass':1,
        'scope':'Distinct lateral-qualified normal-contact experiment only; not a replacement G/pass. ALL loaded points retain original body/white/head ownership plus flat inward plane and fixed signed-normal qualifier. Endcap-normal or unqualified taper loads stop. Cosine0.9 permits limited off-axis components, not a zero-axial-force claim. No recook, geometry/force tolerance change, Z exclusion, grasp/extraction or new improvement pool.',
        'source_sha256':sha(__file__)}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()

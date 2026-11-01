"""Validated1769 raw targeted-initialization checks, reused without numerical changes."""
import math
import numpy as np

def restoration_checks(record,baseline,protocol):
    expected=baseline['initial_robot_properties'];names=record['body_names'];paths=record['link_paths'];before=record['before'];after=record['after'];n=len(names)
    mapping=n==len(expected['masses'][0]) and n>11 and names[10:12]==['fr3_leftfinger','fr3_rightfinger'] and paths==[['/World/envs/env_0/Robot/'+name for name in names]]
    nonfinger=[i for i in range(n) if i not in (10,11)]
    physical=['masses','coms','inertias'];actuators=['stiffnesses','dampings','effort_limits']
    compatible=set(before)==set(after)==set(expected) and all(np.asarray(before[k]).shape==np.asarray(expected[k]).shape for k in expected)
    unchanged_nonfingers=compatible and all(np.array_equal(np.asarray(before[k])[:,nonfinger],np.asarray(expected[k])[:,nonfinger]) for k in physical)
    unchanged_actuators=compatible and all(before[k]==expected[k] for k in actuators)
    return {'restoration_one_frozen_order':record['count']==1 and record['order']==record['completed_setters']==['set_masses','set_coms','set_inertias'],
        'restoration_reference_pin':record['reference_sha256']==protocol['reference_sha256'],
        'restoration_timing':record['timing']=='after_scene_reset_before_explicit_preassembly_step' and record['sim_reset_internal_initialization_precedes_restore'] is True,
        'restoration_finger_mapping':bool(mapping),'restoration_only_finger_properties_prechanged':bool(unchanged_nonfingers and unchanged_actuators),
        'restoration_exact_all6_B0_readback':after==expected,
        'restoration_no_q_or_qdot_change':record['q_before']==record['q_after'] and record['qdot_before']==record['qdot_after'] and bool(np.isfinite(record['q_after']).all() and np.isfinite(record['qdot_after']).all()),
        'restoration_no_physics_time_change':record['physics_time_before_s']==record['physics_time_after_s'] and math.isfinite(record['physics_time_before_s'])}

def targeted_write_checks(record):
    views=record['target_views'];expected=[];valid=set(views)=={'left','right'}
    for label,index in [('left',10),('right',11)]:
        path='/World/envs/env_0/Robot/fr3_'+label+'finger';v=views[label]
        valid=valid and v['path']==path and v['resolved_paths']==[path] and v['count']==1 and v['articulation_link_index']==index
        for state in ['before','after']:
            valid=valid and set(v[state])=={'masses','coms','inertias'} and all(np.asarray(v[state][k]).shape==shape and np.isfinite(v[state][k]).all() for k,shape in [('masses',(1,1)),('coms',(1,7)),('inertias',(1,9))])
    for setter,shape in [('set_masses',[1,1]),('set_coms',[1,7]),('set_inertias',[1,9])]:
        for label in ['left','right']:
            expected.append({'path':'/World/envs/env_0/Robot/fr3_'+label+'finger','setter':setter,'view_index':0,'shape':shape})
    return {'only_two_exact_finger_views':record['route']=='two_exact_finger_rigid_body_views' and bool(valid),
        'only_six_targeted_property_writes':record['targeted_writes']==expected}

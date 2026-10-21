"""Use Person 1's delivered labels as-is in the synthetic reference workcell."""
from copy import deepcopy
import hashlib
import json
from .person1_intake import convert_inventory
from . import prepare
from .intake import normalize_snapshot
from execution import compile_job


def prepare_person1_simulation(inventory,cell,config=None):
    # No additional score threshold, color measurement or clustering.
    observed,audit=convert_inventory(inventory,min_score=0.)
    estimation=inventory['color_estimation']
    names=['uniform'] if estimation['selected_k']==1 else [f'color_group_{i+1}' for i in range(estimation['selected_k'])]
    if config is None:
        shape=cell['pallet']['capacity']
        config=dict(**shape,target_ratios=dict.fromkeys(names,1),mode='mixed',shortage_policy='reject')
    _,plan,_=prepare(observed,config)
    chosen={p['brick_id'] for p in plan['placements']}
    staged=[deepcopy(b) for b in observed['items'] if b['id'] in chosen]
    # Stage only the selected pieces; the rest remain in the offline input inventory.
    # This is an explicit new synthetic scene, never measured camera coordinates.
    tag=hashlib.sha256(json.dumps(dict(input=observed['snapshot_id'],plan=plan),sort_keys=True).encode()).hexdigest()[:16]
    snapshot=normalize_snapshot(dict(schema_version='inventory-snapshot-0.1',snapshot_id=f'person1-staging:{tag}',source='synthetic',face_aware=False,items=staged,
        producer=dict(input_snapshot_id=observed['snapshot_id'],geometry_source='synthetic_staging_grid',classification_source='person1_export',additional_score_filter=False)))
    job=compile_job(plan,staged,cell)
    handoff=dict(input_snapshot_id=observed['snapshot_id'],image_id=inventory['image_id'],inventory_sha256=observed['producer']['inventory_sha256'],
                 input_count=audit['input_count'],eligible_count=audit['accepted_count'],staged_count=len(staged),unstaged_eligible_ids=[b['id'] for b in observed['items'] if b['id'] not in chosen],
                 excluded=audit['excluded'],additional_score_filter=False,geometry_source='synthetic_staging_grid',classification_source='person1_export',physical_validation=False,
                 group_centers_lab=dict(zip(names,deepcopy(estimation['group_centers_lab']))),recipe=deepcopy(config))
    job['person1_handoff']=handoff
    return dict(observed_snapshot=observed,staged_snapshot=snapshot,plan=plan,job=job,handoff=handoff)

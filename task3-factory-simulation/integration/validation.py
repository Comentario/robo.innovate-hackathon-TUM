"""Compare a complete independent observation against a plan; never invent missing evidence."""
import hashlib
import json


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan,sort_keys=True).encode()).hexdigest()


def validate_final(plan, observations=None, *, run_id=None):
    if observations is None:
        return dict(status='awaiting_observation',independent=False,issues=[],observed_positions=0)
    if not isinstance(observations,dict) or observations.get('schema_version')!='pallet-observation-0.1':
        raise ValueError('expected pallet-observation-0.1 envelope')
    if run_id is not None and observations.get('run_id')!=run_id:
        raise ValueError('observation does not identify this execution run')
    if observations.get('plan_digest')!=plan_digest(plan):
        raise ValueError('observation does not identify this plan')
    if observations.get('source') not in ('synthetic','perception'):
        raise ValueError('observation source must be synthetic/perception')
    if not isinstance(observations.get('observation_id'),str) or not observations['observation_id'].strip():
        raise ValueError('observation_id must be a nonempty string')
    placements=observations.get('placements')
    if not isinstance(placements,list):
        raise ValueError('observation placements must be a list')
    expected={(p['layer'],p['row'],p['column']):p for p in plan['placements']}
    seen,seen_ids,issues=set(),set(),[]
    for item in placements:
        if not isinstance(item,dict) or any(type(item.get(k)) is not int for k in ('layer','row','column')):
            raise ValueError('observed positions require integer coordinates')
        position=tuple(item[k] for k in ('layer','row','column'))
        if position in seen:
            issues.append(dict(kind='duplicate_position',position=list(position)))
        seen.add(position)
        bid=item.get('brick_id')
        if not isinstance(bid,str) or not bid:
            raise ValueError('observed placements require brick_id')
        if bid in seen_ids:
            issues.append(dict(kind='duplicate_brick',brick_id=bid))
        seen_ids.add(bid)
        if position not in expected:
            issues.append(dict(kind='unexpected_position',position=list(position)))
            continue
        target=expected[position]
        for field in ('brick_id','color_group','visible_face'):
            if field in target and item.get(field)!=target[field]:
                issues.append(dict(kind='mismatch',position=list(position),field=field,
                                   expected=target[field],observed=item.get(field)))
    for position in sorted(set(expected)-seen):
        issues.append(dict(kind='missing_position',position=list(position)))
    return dict(status='failed' if issues else 'passed',independent=observations['source']=='perception',
                source=observations['source'],observation_id=observations['observation_id'],
                observed_positions=len(seen),issues=issues)

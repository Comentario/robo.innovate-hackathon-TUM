"""Offline integration stand-in; no hardware adapters or shared reservations."""
from collections import Counter
from copy import deepcopy

from planning import make_plan
from planning.faces import face_candidates, make_face_plan


def validate_plan(plan, inventory):
    """Check the consumer boundary before simulating any reservation or pick."""
    if not isinstance(plan, dict) or plan.get('schema_version') not in ('0.2', '0.3'):
        raise ValueError('unsupported plan schema')
    shape = plan.get('shape')
    if not isinstance(shape, dict) or set(shape) != {'rows', 'columns', 'layers'}:
        raise ValueError('invalid plan shape')
    if any(type(n) is not int or n <= 0 for n in shape.values()):
        raise ValueError('invalid plan dimensions')
    if not isinstance(inventory, list):
        raise ValueError('inventory must be a list')
    face_choices = face_candidates(inventory)[0] if plan['schema_version'] == '0.3' else None
    source = {}
    for brick in inventory:
        if not isinstance(brick, dict) or not isinstance(brick.get('id'), str) or not brick['id'].strip():
            raise ValueError('inventory requires nonempty string IDs')
        if face_choices is None and (not isinstance(brick.get('color_group'), str) or not brick['color_group'].strip()):
            raise ValueError('inventory requires color categories')
        if brick['id'] in source:
            raise ValueError('duplicate inventory ID')
        source[brick['id']] = brick
    placements = plan.get('placements')
    coordinates = [(l,r,c) for l in range(shape['layers'])
                   for r in range(shape['rows']) for c in range(shape['columns'])]
    if not isinstance(placements, list) or len(placements) != len(coordinates):
        raise ValueError('plan must fill every logical position')
    used = set()
    for step, (p, position) in enumerate(zip(placements, coordinates), 1):
        if not isinstance(p, dict):
            raise ValueError('placements must be objects')
        if type(p.get('step')) is not int or p['step'] != step:
            raise ValueError('steps must be contiguous and ordered')
        if any(type(p.get(k)) is not int for k in ('layer', 'row', 'column')):
            raise ValueError('coordinates must be integers')
        if tuple(p[k] for k in ('layer', 'row', 'column')) != position:
            raise ValueError('positions must follow complete layer-row-column order')
        brick_id = p.get('brick_id')
        if not isinstance(brick_id, str) or brick_id not in source or brick_id in used:
            raise ValueError('plan references an unavailable or repeated brick ID')
        if face_choices is None:
            if p.get('color_group') != source[brick_id]['color_group']:
                raise ValueError('plan category does not match inventory')
        elif not any(all(p.get(k) == c[k] for k in ('orientation_id', 'visible_face', 'color_group'))
                     for c in face_choices[brick_id]):
            raise ValueError('selected face or orientation is not observed and allowed')
        used.add(brick_id)
    actual = Counter(p['color_group'] for p in placements)
    blend = plan.get('blend')
    if not isinstance(blend, dict) or any(type(n) is not int or n < 0 for n in blend.values()):
        raise ValueError('invalid blend counts')
    if actual != Counter(blend):
        raise ValueError('blend counts do not match placements')


def simulate_plan(plan, inventory, *, fail_step=None):
    """Simulate one fresh run; never command a robot or mutate the caller's stock."""
    validate_plan(plan, inventory)
    placements = plan['placements']
    if fail_step is not None and (type(fail_step) is not int or not 1 <= fail_step <= len(placements)):
        raise ValueError('fail_step must identify a placement in this plan')
    events = [dict(event='plan_validated', placements=len(placements)),
              dict(event='reservation_simulated', brick_ids=[p['brick_id'] for p in placements])]
    confirmed = []
    for p in placements:
        if p['step'] == fail_step:
            events.append(dict(event='placement_failed', step=p['step'], brick_id=p['brick_id'],
                               reason='injected_failure_before_pick'))
            events.append(dict(event='run_stopped', next_action='reconcile_inventory_and_pallet'))
            break
        confirmed.append(deepcopy(p))
        events.append(dict(event='placement_confirmed', step=p['step'], brick_id=p['brick_id']))
    else:
        events.append(dict(event='run_completed'))
    consumed = {p['brick_id'] for p in confirmed}
    released = [p['brick_id'] for p in placements if p['brick_id'] not in consumed]
    events.append(dict(event='simulated_reservations_released', brick_ids=released))
    return dict(schema_version='dry-run-0.1', execution='simulation_only',
                status='stopped' if fail_step is not None else 'completed',
                plan=deepcopy(plan), events=events, confirmed_placements=confirmed,
                remaining_inventory=deepcopy([b for b in inventory if b['id'] not in consumed]),
                resume_supported=False)


def run_demo(inventory, config, *, fail_step=None, face_aware=False):
    """Planning rejection emits no simulated execution events."""
    if not isinstance(config, dict):
        raise ValueError('config must be an object')
    allowed = {'rows', 'columns', 'layers', 'target_ratios', 'mode', 'tone_values', 'shortage_policy'}
    if set(config) - allowed or not {'rows', 'columns'} <= set(config):
        raise ValueError('config requires rows/columns and known planner keys')
    try:
        planner = make_face_plan if face_aware else make_plan
        plan = planner(inventory, **config)
    except ValueError as error:
        return dict(schema_version='dry-run-0.1', execution='simulation_only', status='rejected',
                    reason=str(error), events=[], confirmed_placements=[],
                    remaining_inventory=deepcopy(inventory), resume_supported=False)
    return simulate_plan(plan, inventory, fail_step=fail_step)

"""Face-aware planning with declared orientation candidates, independent of hardware."""
from collections import Counter
from copy import deepcopy

from . import blend_planner, make_plan


def face_candidates(inventory):
    """Return observed, allowed choices; never infer an unobserved face."""
    if not isinstance(inventory, list):
        raise ValueError('face inventory must be a list')
    candidates, unknown = {}, {}
    for brick in inventory:
        if not isinstance(brick, dict) or not isinstance(brick.get('id'), str) or not brick['id'].strip():
            raise ValueError('bricks require nonempty string IDs')
        brick_id = brick['id']
        if brick_id in candidates:
            raise ValueError('duplicate brick ID')
        faces, orientations = brick.get('faces'), brick.get('allowed_orientations')
        if not isinstance(faces, dict) or not isinstance(orientations, list) or not orientations:
            raise ValueError('each brick requires faces and allowed_orientations')
        choices, unseen, ids = [], [], set()
        for orientation in orientations:
            if not isinstance(orientation, dict):
                raise ValueError('orientations must be objects')
            oid, face = orientation.get('id'), orientation.get('visible_face')
            if any(not isinstance(v, str) or not v.strip() for v in (oid, face)) or oid in ids:
                raise ValueError('orientation IDs must be unique with a visible_face')
            ids.add(oid)
            observation = faces.get(face)
            if observation is None:
                unseen.append(face)
                continue
            if not isinstance(observation, dict) or not isinstance(observation.get('color_group'), str) or not observation['color_group'].strip():
                raise ValueError('observed faces require a color_group')
            choices.append(dict(orientation_id=oid, visible_face=face,
                                color_group=observation['color_group']))
        candidates[brick_id] = sorted(choices, key=lambda c: (c['color_group'], c['orientation_id']))
        if unseen:
            unknown[brick_id] = sorted(set(unseen))
    return candidates, unknown


def make_face_plan(inventory, *, rows, columns, layers=1, target_ratios=None,
                   mode='mixed', tone_values=None, shortage_policy='reject'):
    """Match shade quotas to distinct bricks, then plan their selected visible faces."""
    if any(type(n) is not int or n <= 0 for n in (rows, columns, layers)):
        raise ValueError('dimensions must be positive integers')
    if shortage_policy not in ('reject', 'redistribute'):
        raise ValueError('shortage_policy must be reject or redistribute')
    if not isinstance(target_ratios, dict) or not target_ratios:
        raise ValueError('face-aware planning requires an explicit target recipe')
    capacity = rows * columns * layers
    # Unlimited synthetic stock uses the existing quota rule, including rounding.
    unlimited = [dict(id=f'{gidx}_{i}', color_group=group)
                 for gidx, group in enumerate(target_ratios) for i in range(capacity)]
    quotas, ratios = blend_planner(unlimited, capacity, target_ratios)
    choices, unknown = face_candidates(inventory)
    options = {bid: {c['color_group'] for c in cs if ratios.get(c['color_group'], 0) > 0}
               for bid, cs in choices.items()}
    slots = [g for g, count in quotas.items() for _ in range(count)]
    slot_to_brick, brick_to_slot = {}, {}

    def match(slot, seen):
        for bid in sorted(options):
            if bid in seen or slots[slot] not in options[bid]:
                continue
            seen.add(bid)
            if bid not in brick_to_slot or match(brick_to_slot[bid], seen):
                slot_to_brick[slot] = bid
                brick_to_slot[bid] = slot
                return True
        return False

    for slot in range(len(slots)):
        match(slot, set())
    selected = {bid: slots[slot] for bid, slot in brick_to_slot.items()}
    if len(selected) < capacity and shortage_policy == 'reject':
        raise ValueError('observed allowed faces cannot satisfy the rounded target recipe')
    while len(selected) < capacity:
        counts = Counter(selected.values())
        available = [(bid, group) for bid, groups in options.items() if bid not in selected
                     for group in groups]
        if not available:
            raise ValueError('insufficient bricks with observed allowed faces')
        bid, group = min(available, key=lambda pair: (-(capacity * ratios[pair[1]] - counts[pair[1]]), pair[0], pair[1]))
        selected[bid] = group
    selected_faces = {bid: next(c for c in choices[bid] if c['color_group'] == group)
                      for bid, group in selected.items()}
    flat = [dict(id=bid, color_group=group) for bid, group in selected.items()]
    plan = make_plan(flat, rows=rows, columns=columns, layers=layers,
                     target_ratios=target_ratios, mode=mode, tone_values=tone_values,
                     shortage_policy=shortage_policy)
    plan['schema_version'] = '0.3'
    plan['face_policy'] = dict(visible_surface='single_display_face',
                               unknown_allowed_faces=unknown,
                               excluded_brick_ids=sorted(bid for bid, cs in choices.items() if not cs),
                               orientation_source='declared_candidates_not_robot_verified')
    for placement in plan['placements']:
        placement.update(deepcopy(selected_faces[placement['brick_id']]))
    return plan

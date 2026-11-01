"""Explicit mock classifications; no image classifier, scheduler or robot commands."""


def join(candidate, frame_id, classifications):
    if candidate['decision'] != 'present':
        return {'status': 'abstain', 'destination': None, 'reason': 'candidate_not_present'}
    matches = [row for row in classifications if row.get('frame_id') == frame_id
               and row.get('candidate_id') == candidate['candidate_id']]
    if len(matches) != 1:
        return {'status': 'abstain', 'destination': None, 'reason': 'missing_or_duplicate_exact_join'}
    row = matches[0]
    if row.get('quality') == 'faulty':
        return {'status': 'joined', 'destination': 'reject', 'reason': 'mock_faulty'}
    if row.get('quality') == 'good' and row.get('label') in ('dark_red', 'tan'):
        return {'status': 'joined', 'destination': 'main' if row['label'] == 'dark_red' else 'buffer',
                'reason': 'mock_good_selected' if row['label'] == 'dark_red' else 'mock_good_unselected'}
    return {'status': 'abstain', 'destination': None, 'reason': 'unknown_classification'}


def fixtures(frames):
    selected = next(((frame_id, c) for frame_id, candidates in sorted(frames.items())
                     for c in sorted(candidates, key=lambda x: x['candidate_id'])
                     if c['decision'] == 'present'), None)
    if selected is None:
        return {'schema': 'challenge1-mock-v1', 'fixtures_available': False,
                'fixtures': [], 'guard_checks': [], 'reason': 'no_present_candidate'}
    frame_id, candidate = selected
    rows = []
    for identity, quality, label in (('good_selected', 'good', 'dark_red'),
                                    ('good_unselected', 'good', 'tan'),
                                    ('faulty', 'faulty', None), ('unknown', 'unknown', None)):
        classification = {'frame_id': frame_id, 'candidate_id': candidate['candidate_id'],
                          'quality': quality, 'label': label}
        rows.append({'fixture_id': identity, 'frame_id': frame_id,
                     'candidate_id': candidate['candidate_id'], 'input_classification': classification,
                     'result': join(candidate, frame_id, [classification])})
    correct = rows[0]['input_classification']
    guards = [('wrong_frame', candidate, [{**correct, 'frame_id': 'unmatched'}]),
              ('wrong_candidate', candidate, [{**correct, 'candidate_id': 'unmatched'}]),
              ('nonpresent', {**candidate, 'decision': 'uncertain'}, [correct]),
              ('duplicate_join', candidate, [correct, correct])]
    checks = [{'name': name, 'result': join(c, frame_id, classifications)}
              for name, c, classifications in guards]
    for check in checks:
        check['passed'] = check['result']['status'] == 'abstain' and check['result']['destination'] is None
    return {'schema': 'challenge1-mock-v1', 'fixtures_available': True, 'fixtures': rows,
            'guard_checks': checks, 'limitations': 'Explicit mock label values only; no live Challenge1 service or robot commands'}


def self_test():
    result = fixtures({'f000': [{'candidate_id': 'candidate0', 'decision': 'present'}]})
    assert [row['result']['destination'] for row in result['fixtures']] == ['main', 'buffer', 'reject', None]
    assert all(check['passed'] for check in result['guard_checks'])
    assert fixtures({'f000': [{'candidate_id': 'candidate0', 'decision': 'missing'}]})['fixtures_available'] is False
    print('Exact join, four mock fixtures, unknown/mismatch/nonpresent/duplicate abstention: PASS')


if __name__ == '__main__':
    self_test()

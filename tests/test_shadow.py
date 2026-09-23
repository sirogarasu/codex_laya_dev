import json
from urllib.error import URLError

import pytest

from harness.shadow import evaluate, load_cases, run


def case():
    return {'id': 'one', 'question': 'tool', 'request': {'input': 'Read', 'schema': {
        'tool': {'type': 'choice', 'instructions': 'Select', 'criteria': ['read', 'write', 'stop']}}},
        'expected': 'read', 'allowed_choices': ['read', 'stop']}


def response(choice='read', confidence=.95):
    return {'answers': {'tool': {'type': 'choice', 'choice': choice, 'confidence': confidence}},
            'confidence': confidence}


@pytest.mark.parametrize('choice,confidence,reason', [
    ('read', .95, 'eligible'), ('write', 1, 'policy_denied'),
    ('read', .2, 'low_confidence'), ('read', None, 'confidence_missing'),
    ('read', True, 'confidence_missing'), ('read', float('nan'), 'confidence_missing'),
])
def test_gating(choice, confidence, reason):
    result = evaluate(case(), response(choice, confidence), .8)
    assert result['reason'] == reason
    assert result['would_accept'] == (reason == 'eligible')


def test_missing_aggregate():
    body = response()
    del body['confidence']
    assert not evaluate(case(), body, .8)['would_accept']


def test_unknown_choice():
    with pytest.raises(ValueError):
        evaluate(case(), response('shell'), .8)


def test_records_errors_and_continues(tmp_path):
    cases = [case(), {**case(), 'id': 'two'}, {**case(), 'id': 'three'}]
    replies = iter([URLError('offline'), response('stop'), response('write')])
    def predictor(*args):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply
    output = tmp_path / 'results.jsonl'
    summary = run(cases, 'unused', output, predictor=predictor)
    assert summary['errors'] == 1
    assert summary['accepted_errors'] == 1
    assert summary['policy_violations'] == 1
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert all(r['executed'] is False for r in records)
    assert all('request' not in r for r in records)
    with pytest.raises(FileExistsError):
        run(cases, 'unused', output, predictor=predictor)


def test_duplicate_ids(tmp_path):
    path = tmp_path / 'cases.jsonl'
    path.write_text('\n'.join(json.dumps(case()) for _ in range(2)))
    with pytest.raises(ValueError):
        load_cases(path)


def test_example_dataset():
    assert len(load_cases('examples/tool_selection.jsonl')) == 8

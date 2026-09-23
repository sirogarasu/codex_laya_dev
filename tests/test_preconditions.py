from copy import deepcopy

import pytest

from harness.preconditions import check_preconditions
from harness.shadow import evaluate


def guard():
    return {'operation_count': 1, 'candidates': {'read': {
        'required_arguments': ['target'], 'arguments': {'target': 'README.md'}}}}


@pytest.mark.parametrize('value', [None, '', '   ', [], {}])
def test_missing_target(value):
    data = guard()
    data['candidates']['read']['arguments']['target'] = value
    assert check_preconditions(data, 'read') == 'argument_missing'


@pytest.mark.parametrize('count', [0, 2, 3])
def test_unresolved_operations(count):
    data = guard()
    data['operation_count'] = count
    assert check_preconditions(data, 'read') == 'unresolved_operations'


@pytest.mark.parametrize('data', [None, {}, {'operation_count': True, 'candidates': {}},
                                {'operation_count': 1, 'candidates': []}])
def test_malformed(data):
    assert check_preconditions(data, 'read') == 'invalid_preconditions'


def test_unknown_candidate():
    assert check_preconditions(guard(), 'write') == 'candidate_missing'


def test_valid_and_nonmutating():
    data = guard()
    original = deepcopy(data)
    assert check_preconditions(data, 'read') == 'passed'
    assert data == original


def test_full_confidence_cannot_override_missing_target():
    data = guard()
    data['candidates']['read']['arguments'] = {}
    case = {'question': 'tool', 'expected': 'stop', 'allowed_choices': ['read', 'stop'],
            'request': {'schema': {'tool': {'criteria': ['read', 'stop']}}}, 'preconditions': data}
    response = {'answers': {'tool': {'type': 'choice', 'choice': 'read', 'confidence': 1.}}, 'confidence': 1.}
    result = evaluate(case, response, .8)
    assert result['reason'] == 'argument_missing'
    assert not result['would_accept']
    assert not result['correct']
    case['preconditions'] = guard()
    case['allowed_choices'] = ['stop']
    result = evaluate(case, response, .8)
    assert result['precondition'] == 'passed'
    assert result['reason'] == 'policy_denied'
    assert not result['would_accept']

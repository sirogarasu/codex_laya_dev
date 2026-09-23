import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

spec = importlib.util.spec_from_file_location('decision_api', Path(__file__).parents[1] / 'laya/api.py')
api = importlib.util.module_from_spec(spec)
# Only this module import is isolated; production continues to import real CUDA dependencies.
with patch.dict(sys.modules, {'laya': Mock(), 'torch': Mock()}):
    spec.loader.exec_module(api)


@pytest.fixture
def client(monkeypatch):
    model = Mock(device=SimpleNamespace(type='cuda'))
    model.predict.return_value = {'answers': {'route': {'type': 'choice', 'choice': 'read', 'confidence': .9}}}
    monkeypatch.setattr(api, 'agent', model)
    # Deliberately omit lifespan: these tests exercise the API boundary, not model loading.
    yield TestClient(api.app), model


def request():
    return {'input': {'task': 'Read a file'}, 'schema': {'route': {
        'type': 'choice', 'instructions': 'Select a tool', 'criteria': ['read', 'stop']}}}


def test_decide_and_forward_schema(client):
    http, model = client
    response = http.post('/v1/decide', json=request())
    assert response.status_code == 200
    assert response.json()['confidence'] == .9
    assert model.predict.call_args.args[1] == request()['schema']


@pytest.mark.parametrize('change', [
    lambda r: r.update(input='  '), lambda r: r.update(input={}),
    lambda r: r.update(schema={}), lambda r: r.update(unknown=True),
    lambda r: r['schema']['route'].update(type='unknown'),
    lambda r: r['schema']['route'].update(criteria=['read', 'read']),
    lambda r: r['schema']['route'].update(criteria=['read', {}]),
    lambda r: r['schema']['route'].update(instructions=' '),
    lambda r: r['schema']['route'].update(type='score', criteria={'a': 'b', 'c': 'd'}),
    lambda r: r['schema']['route'].update(type='noul', criteria=['yes', 'no']),
])
def test_invalid_input_never_calls_model(client, change):
    http, model = client
    body = request()
    change(body)
    assert http.post('/v1/decide', json=body).status_code == 422
    model.predict.assert_not_called()


@pytest.mark.parametrize('question', [
    {'type': 'choice', 'instructions': 'Select', 'criteria': {'a': {'desc': 'Read'}, 'b': None}},
    {'type': 'score', 'instructions': 'Rate', 'criteria': ['low', 'high']},
    {'type': 'noul', 'instructions': 'Ready?'},
    {'type': 'noul', 'instructions': 'Ready?', 'criteria': {'true': 'yes', 'false': 'no'}},
])
def test_supported_questions(question):
    assert api.Question.model_validate(question).type == question['type']


@pytest.mark.parametrize('value', [None, True, -1, 1.1, float('nan'), float('inf'), '0.9'])
def test_missing_or_invalid_confidence(value):
    assert api.decision_confidence({'a': {'confidence': .9}, 'b': {'confidence': value}}) is None


def test_confidence_minimum():
    assert api.decision_confidence({'a': {'confidence': .9}, 'b': {'confidence': .4}}) == .4
    assert api.decision_confidence({}) is None


def test_gpu_fallback_rejects_result(client):
    http, model = client
    def fallback(*args):
        model.device.type = 'cpu'
        return {'answers': {'route': {'choice': 'read', 'confidence': .9}}}
    model.predict.side_effect = fallback
    assert http.post('/v1/decide', json=request()).status_code == 503
    assert http.get('/readyz').status_code == 503
    assert http.post('/v1/decide', json=request()).status_code == 503
    assert model.predict.call_count == 1


def test_unloaded_model(client, monkeypatch):
    http, _ = client
    monkeypatch.setattr(api, 'agent', None)
    assert http.get('/readyz').status_code == 503
    assert http.post('/v1/decide', json=request()).status_code == 503


@pytest.mark.parametrize('result', [{'answers': {}}, {'answers': {'route': []}}, {'answers': {'route': {'confidence': float('nan')}}}])
def test_malformed_model_response(client, result):
    http, model = client
    model.predict.return_value = result
    assert http.post('/v1/decide', json=request()).status_code == 500


def test_option_budget_and_internal_error(client):
    http, model = client
    model.predict.side_effect = ValueError("question 'route' options exceed head_max_len=192")
    assert http.post('/v1/decide', json=request()).status_code == 422
    model.predict.side_effect = RuntimeError('private model internals')
    response = http.post('/v1/decide', json=request())
    assert response.status_code == 500
    assert 'private' not in response.text

"""Check the deployed GPU API contract without executing any selected action."""
import argparse
import json
import math
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from harness.shadow import probability


def exchange(base_url, path, payload=None, timeout=30):
    request = Request(base_url.rstrip('/') + path,
                      data=None if payload is None else json.dumps(payload).encode(),
                      headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, None


def check(condition, message):
    if not condition:
        raise ValueError(message)


def verify(base_url, timeout=30, transport=exchange):
    def call(path, payload=None):
        return transport(base_url, path, payload, timeout)

    status, ready = call('/readyz')
    check(status == 200 and ready == {'status': 'ready'}, 'API is not ready')
    status, metadata = call('/v1/metadata')
    check(status == 200 and isinstance(metadata, dict), 'metadata unavailable')
    device = metadata.get('device')
    check(isinstance(device, str) and (device == 'cuda' or
          (device.startswith('cuda:') and device[5:].isdigit())),
          'CUDA metadata missing; rebuild the API or restore GPU availability')
    schema = {
        'tool': {'type': 'choice', 'instructions': 'Select a tool for the task.',
                 'criteria': ['read_file', 'list_files', 'stop']},
        'explicit': {'type': 'noul', 'instructions': 'Does the task explicitly ask to read a file?'},
        'clarity': {'type': 'score', 'instructions': 'Rate how clear the task is.',
                    'criteria': ['unclear', 'partly clear', 'clear']},
    }
    status, body = call('/v1/decide', {'input': {'task': 'Read README.md.'}, 'schema': schema})
    check(status == 200 and isinstance(body, dict), 'decision request failed')
    answers = body.get('answers')
    check(isinstance(answers, dict) and set(answers) == set(schema), 'answer IDs mismatch')
    for key, question in schema.items():
        answer = answers[key]
        check(isinstance(answer, dict) and answer.get('type') == question['type'], 'answer type mismatch')
        check(probability(answer.get('confidence')), 'invalid item confidence')
    check(answers['tool'].get('choice') in schema['tool']['criteria'], 'unknown choice')
    check(probability(answers['explicit'].get('noul')), 'invalid noul probability')
    score = answers['clarity'].get('score')
    check(not isinstance(score, bool) and isinstance(score, (int, float))
          and math.isfinite(score) and 0 <= score <= 2, 'invalid ordinal score')
    check(probability(body.get('confidence')) and
          body['confidence'] == min(a['confidence'] for a in answers.values()), 'aggregate confidence mismatch')
    for invalid in [
        {'input': ' ', 'schema': schema},
        {'input': 'Read README.md.', 'schema': {}},
        {'input': 'Read README.md.', 'schema': {'tool': {
            'type': 'choice', 'instructions': 'Select', 'criteria': ['read', 'read']}}},
    ]:
        status, _ = call('/v1/decide', invalid)
        check(status == 422, 'invalid input was not rejected with HTTP 422')
    status, ready = call('/readyz')
    check(status == 200 and ready == {'status': 'ready'}, 'API lost readiness after inference')
    return {'status': 'passed', 'device': device, 'model': body.get('model'),
            'decision_types': ['choice', 'noul', 'score'], 'invalid_requests_rejected': 3,
            'executed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://laya-api:8000')
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('timeout must be finite and positive')
    try:
        result = verify(args.base_url, args.timeout)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

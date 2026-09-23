"""Evaluate one choice question per case. Never invoke the selected tool."""
import argparse
import json
import math
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from harness.preconditions import check_preconditions


def probability(value):
    return (
        not isinstance(value, bool) and isinstance(value, (int, float))
        and math.isfinite(value) and 0 <= value <= 1
    )


def load_cases(path):
    cases = []
    seen = set()
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        identifier = case['id']
        question = case['question']
        schema = case['request']['schema']
        q = schema[question]
        labels = q['criteria']
        allowed = case['allowed_choices']
        if (
            not isinstance(identifier, str) or not identifier.strip() or identifier in seen
            or set(schema) != {question} or q['type'] != 'choice'
            or not isinstance(labels, (list, dict)) or len(labels) < 2
            or any(not isinstance(label, str) or not label.strip() for label in labels)
            or len(set(labels)) != len(labels)
            or not isinstance(allowed, list) or not set(allowed) <= set(labels)
            or case['expected'] not in labels
        ):
            raise ValueError('invalid or duplicate case: ' + str(identifier))
        seen.add(identifier)
        cases.append(case)
    if not cases:
        raise ValueError('dataset must not be empty')
    return cases


def evaluate(case, response, threshold):
    answers = response['answers']
    if set(answers) != {case['question']}:
        raise ValueError('unexpected answer IDs')
    answer = answers[case['question']]
    choice = answer['choice']
    if answer.get('type') != 'choice' or choice not in case['request']['schema'][case['question']]['criteria']:
        raise ValueError('invalid choice answer')
    confidence = answer.get('confidence')
    complete = response.get('confidence')
    # Require both item and aggregate confidence, including with older APIs.
    known = probability(confidence) and probability(complete)
    effective = min(confidence, complete) if known else None
    allowed = choice in case['allowed_choices']
    precondition = (check_preconditions(case['preconditions'], choice)
                    if 'preconditions' in case else 'not_checked')
    reason = (
        precondition if precondition not in {'passed', 'not_checked'} else
        'policy_denied' if not allowed else
        'confidence_missing' if not known else
        'low_confidence' if effective < threshold else 'eligible'
    )
    return {
        'choice': choice, 'confidence': effective, 'precondition': precondition,
        'correct': choice == case['expected'], 'policy_violation': not allowed,
        'would_accept': reason == 'eligible', 'reason': reason,
        'model': response.get('model'),
    }


def predict(base_url, request, timeout):
    req = Request(
        base_url.rstrip('/') + '/v1/decide',
        data=json.dumps(request, ensure_ascii=False, allow_nan=False).encode(),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    with urlopen(req, timeout=timeout) as response:
        return json.load(response)


def summarize(records):
    successful = [r for r in records if 'error' not in r]
    accepted = [r for r in successful if r['would_accept']]
    bins = []
    for low, high in [(0, .5), (.5, .8), (.8, 1.)]:
        group = [r for r in successful if r['confidence'] is not None
                 and low <= r['confidence'] and (r['confidence'] < high or high == 1)]
        bins.append({'range': [low, high], 'count': len(group),
                     'accuracy': sum(r['correct'] for r in group) / len(group) if group else None})
    return {
        'mode': 'shadow', 'total': len(records), 'errors': len(records) - len(successful),
        'accuracy': sum(r['correct'] for r in successful) / len(successful) if successful else None,
        'policy_violations': sum(r['policy_violation'] for r in successful),
        'would_accept': len(accepted),
        'precondition_rejections': sum(r.get('precondition', 'not_checked') not in
                                      {'passed', 'not_checked'} for r in successful),
        'accepted_errors': sum(not r['correct'] for r in accepted),
        'mean_latency_ms': sum(r['latency_ms'] for r in records) / len(records) if records else None,
        'confidence_bins': bins,
    }


def run(cases, base_url, output, threshold=.8, timeout=30, predictor=predict):
    if not probability(threshold) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('invalid threshold or timeout')
    records = []
    # Exclusive creation prevents accidentally replacing a previous evaluation.
    with Path(output).open('x') as stream:
        for case in cases:
            start = time.perf_counter()
            record = {'id': case['id'], 'mode': 'shadow', 'executed': False,
                      'expected': case['expected'], 'threshold': threshold}
            try:
                record.update(evaluate(case, predictor(base_url, case['request'], timeout), threshold))
            except HTTPError as error:
                record.update(error=f'HTTP {error.code}', would_accept=False)
            except (URLError, OSError, ValueError, KeyError, TypeError) as error:
                record.update(error=type(error).__name__, would_accept=False)
            record['latency_ms'] = round((time.perf_counter() - start) * 1000, 3)
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()
            records.append(record)
    return summarize(records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cases')
    parser.add_argument('--base-url', default='http://laya-api:8000')
    parser.add_argument('--output', required=True)
    parser.add_argument('--threshold', type=float, default=.8)
    parser.add_argument('--timeout', type=float, default=30)
    args = parser.parse_args()
    try:
        summary = run(load_cases(args.cases), args.base_url, args.output, args.threshold, args.timeout)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'{type(error).__name__}: {error}\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())

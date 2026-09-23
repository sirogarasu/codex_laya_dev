import pytest

from harness.smoke import verify


def transport(device='cuda:0', aggregate=.8, invalid_status=422):
    def call(base, path, payload, timeout):
        if path == '/readyz':
            return 200, {'status': 'ready'}
        if path == '/v1/metadata':
            return 200, {'device': device}
        if payload['input'] == {'task': 'Read README.md.'}:
            return 200, {'answers': {
                'tool': {'type': 'choice', 'choice': 'read_file', 'confidence': .9},
                'explicit': {'type': 'noul', 'noul': .9, 'confidence': .9},
                'clarity': {'type': 'score', 'score': 1.8, 'confidence': .8},
            }, 'confidence': aggregate}
        return invalid_status, None
    return call


def test_contract():
    assert verify('unused', transport=transport())['executed'] is False


@pytest.mark.parametrize('device', [None, 'cpu', 'cuda_fake', 'cuda:invalid'])
def test_old_or_cpu_service_fails(device):
    with pytest.raises(ValueError, match='CUDA'):
        verify('unused', transport=transport(device=device))


def test_bad_aggregate():
    with pytest.raises(ValueError, match='aggregate'):
        verify('unused', transport=transport(aggregate=.9))


def test_missing_input_validation():
    with pytest.raises(ValueError, match='422'):
        verify('unused', transport=transport(invalid_status=200))

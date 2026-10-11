import copy
import pytest

from ai_os_decision.recommendation_validation import load_request, validate_request


CONTEXTS = {
    'model-routing': {'candidates': [
        {'id': 'small', 'available': True, 'local': True, 'capable': True, 'estimated_cost': 0},
        {'id': 'large', 'available': True, 'local': True, 'capable': True, 'estimated_cost': 0}],
        'local_only': True, 'budget': 0},
    'tool-risk': {'tool_id': 'files', 'action': 'read', 'arguments': {'path': 'example.txt'}, 'permitted': True},
    'intent-domain': {'intents': {'coding': 'write code', 'unknown': 'other'},
                      'domains': {'software': 'software', 'unknown': 'other'}},
    'loop': {'iteration': 0, 'max_iterations': 3, 'elapsed_seconds': 0, 'timeout_seconds': 60,
             'cost': 0, 'budget': 1, 'goal_complete': False, 'verification_pending': False},
    'rag-rerank': {'query': 'Python tests', 'candidates': [
        {'id': 'a', 'source': 'example:a', 'excerpt': 'Python pytest tests'},
        {'id': 'b', 'source': 'example:b', 'excerpt': 'Cooking recipes'}]},
    'guardrails': {'content': 'Summarize the source.', 'origin': 'synthetic'},
}


def request(profile):
    return {'schema': 'ai-os-recommendation-request/v1', 'text': 'Review this task.',
            'environment': 'dev', 'context': copy.deepcopy(CONTEXTS[profile])}


@pytest.mark.parametrize('profile', CONTEXTS)
def test_valid_profiles_and_deep_copy(profile):
    data = request(profile)
    out = validate_request(profile, data)
    assert out == data and out is not data and out['context'] is not data['context']


def test_rejects_duplicate_keys(tmp_path):
    path = tmp_path / 'request.json'
    path.write_text('{"text":"a","text":"b"}')
    with pytest.raises(ValueError):
        load_request(str(path))


def test_size_limit_before_parse(tmp_path):
    path = tmp_path / 'request.json'
    path.write_bytes(b'{}' + b' ' * 65534)
    assert load_request(str(path)) == {}
    path.write_bytes(b'{}' + b' ' * 65535)
    with pytest.raises(ValueError):
        load_request(str(path))


@pytest.mark.parametrize('value', [True, '1', -1, float('nan'), float('inf')])
def test_rejects_bool_as_number(value):
    data = request('loop')
    data['context']['cost'] = value
    with pytest.raises((TypeError, ValueError)):
        validate_request('loop', data)


@pytest.mark.parametrize('profile', CONTEXTS)
def test_rejects_unknown_fields(profile):
    data = request(profile)
    data['context']['unexpected'] = True
    with pytest.raises(ValueError):
        validate_request(profile, data)


def test_rejects_deep_arguments():
    data = request('tool-risk')
    nested = {}
    for _ in range(20):
        nested = {'child': nested}
    data['context']['arguments'] = nested
    with pytest.raises(ValueError):
        validate_request('tool-risk', data)


@pytest.mark.parametrize('value', ['false', 1, None])
def test_permission_requires_boolean(value):
    data = request('tool-risk')
    data['context']['permitted'] = value
    with pytest.raises((TypeError, ValueError)):
        validate_request('tool-risk', data)


@pytest.mark.parametrize('value', ['bad\x00text', 'bad\ntext', object()])
def test_rejects_controls_and_objects(value):
    data = request('guardrails')
    data['context']['content'] = value
    with pytest.raises((TypeError, ValueError)):
        validate_request('guardrails', data)


def test_rejects_duplicate_candidate_ids():
    data = request('rag-rerank')
    data['context']['candidates'][1]['id'] = 'a'
    with pytest.raises(ValueError):
        validate_request('rag-rerank', data)

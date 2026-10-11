from types import SimpleNamespace
import subprocess

import pytest

from ai_os_decision.models import DecisionAnswer, DecisionResult
from ai_os_decision.policy import PolicyEngine
from ai_os_decision.recommendations import recommend
from test_recommendation_validation import CONTEXTS, request


class Fake:
    def __init__(self, error=None, mutate=None):
        self.error, self.mutate, self.calls = error, mutate, []

    def decide(self, state, questions):
        self.calls.append((state, questions))
        if self.error:
            raise self.error
        answers = {q.id: DecisionAnswer(q.id, q.kind, next(iter(q.options)) if q.kind == 'choice' else 2., .9)
                   for q in questions}
        if self.mutate:
            self.mutate(answers)
        return DecisionResult(answers, 'laya', 1.)


def runtime(engine=None):
    return SimpleNamespace(policy=PolicyEngine({'policy': {'deny_patterns': ['BLOCK_THIS'],
                           'approval_required': [{'env': 'production', 'actions': ['deploy']}]}}),
                           laya=engine or Fake())


@pytest.mark.parametrize('profile', CONTEXTS)
def test_success(profile):
    out = recommend(profile, request(profile), runtime())
    assert out['laya']['status'] == 'ok'
    assert out['execution_enabled'] is False
    assert out['schema'] == 'ai-os-recommendation/v1'


@pytest.mark.parametrize('profile', CONTEXTS)
def test_deny_in_context_skips_engine(profile):
    data = request(profile)
    # A nested field must be checked, not only the user text.
    c = data['context']
    if profile in ('rag-rerank', 'model-routing'):
        c['candidates'][0]['id'] = 'BLOCK_THIS'
    elif profile == 'tool-risk':
        c['arguments']['path'] = 'BLOCK_THIS'
    elif profile == 'guardrails':
        c['content'] = 'BLOCK_THIS'
    elif profile == 'intent-domain':
        c['domains']['unknown'] = 'BLOCK_THIS'
    else:
        data['text'] = 'BLOCK_THIS'
    r = runtime()
    out = recommend(profile, data, r)
    assert out['status'] == 'denied' and not r.laya.calls


@pytest.mark.parametrize('profile', CONTEXTS)
@pytest.mark.parametrize('error', [subprocess.TimeoutExpired('worker', .01), RuntimeError('missing checkpoint')])
def test_timeout_and_missing_checkpoint_fallback(profile, error):
    out = recommend(profile, request(profile), runtime(Fake(error)))
    assert out['laya']['fallback_used']
    assert out['execution_enabled'] is False
    if profile in ('tool-risk', 'guardrails'):
        assert out['status'] == 'review_required'


@pytest.mark.parametrize('profile', CONTEXTS)
def test_invalid_answer_fallback(profile):
    out = recommend(profile, request(profile), runtime(Fake(mutate=lambda a: a.clear())))
    assert out['laya']['error'] == 'invalid_answer'


@pytest.mark.parametrize('kind,value,confidence', [('score', 'foreign', .9), ('choice', 'foreign', .9),
                                                 ('choice', 'small', float('nan'))])
def test_wrong_kind_nan_and_extra_answers(kind, value, confidence):
    def mutate(answers):
        answers['model'] = DecisionAnswer('model', kind, value, confidence)
    out = recommend('model-routing', request('model-routing'), runtime(Fake(mutate=mutate)))
    assert out['laya']['fallback_used']


def test_policy_approval_survives_low_risk():
    data = request('tool-risk')
    data['environment'], data['context']['action'] = 'production', 'deploy'
    out = recommend('tool-risk', data, runtime())
    assert out['status'] == 'review_required' and out['policy']['approval_required']


def test_permission_denied_skips_laya():
    data = request('tool-risk')
    data['context']['permitted'] = False
    r = runtime()
    assert recommend('tool-risk', data, r)['status'] == 'denied'
    assert not r.laya.calls


def test_full_context_reaches_engine_and_no_input_echo():
    data = request('rag-rerank')
    data['context']['candidates'] = [{'id': str(i), 'source': f'example:{i}', 'excerpt': 'unique excerpt'}
                                      for i in range(16)]
    r = runtime()
    out = recommend('rag-rerank', data, r)
    assert r.laya.calls[0][0].extra['profile_context']['candidates'][-1]['id'] == '15'
    assert len(out['recommendation']['ranking']) == 16
    assert 'unique excerpt' not in str(out)

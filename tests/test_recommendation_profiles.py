import pytest

from ai_os_decision.recommendation_profiles import build_profile, resolve_profile
from test_recommendation_validation import request


def test_filters_unavailable_remote_over_budget():
    data = request('model-routing')
    c = data['context']['candidates']
    c[0]['local'] = False
    assert build_profile('model-routing', data).fallback['model'] == 'large'
    c[1]['estimated_cost'] = 5
    assert build_profile('model-routing', data).mandatory_review


def test_single_model_skips_choice():
    data = request('model-routing')
    data['context']['candidates'].pop()
    plan = build_profile('model-routing', data)
    assert plan.skip_reason == 'not_required'
    assert resolve_profile(plan, None)['recommendation']['model'] == 'small'


def test_tool_write_requires_review():
    data = request('tool-risk')
    data['context']['action'] = 'write'
    plan = build_profile('tool-risk', data)
    assert resolve_profile(plan, {'risk': 'low'})['review_required']


@pytest.mark.parametrize('key,value', [('iteration', 3), ('elapsed_seconds', 60), ('cost', 1), ('goal_complete', True)])
def test_loop_each_limit_stops(key, value):
    data = request('loop')
    data['context'][key] = value
    plan = build_profile('loop', data)
    assert not plan.questions
    assert resolve_profile(plan, {'next_step': 'continue'})['recommendation']['next_step'] == 'stop'


def test_pending_verification_wins():
    data = request('loop')
    data['context']['verification_pending'] = True
    assert build_profile('loop', data).fallback['next_step'] == 'verify'


def test_rag_stable_ties_preserve_sources():
    plan = build_profile('rag-rerank', request('rag-rerank'))
    out = resolve_profile(plan, {'doc_0': 2., 'doc_1': 2.})
    assert [x['id'] for x in out['recommendation']['ranking']] == ['a', 'b']
    assert out['recommendation']['ranking'][1]['source'] == 'example:b'
    assert plan.state.extra['profile_context']['candidates'][-1]['id'] == 'b'


def test_intent_fallback_unknown():
    out = resolve_profile(build_profile('intent-domain', request('intent-domain')), None)
    assert out['recommendation'] == {'intent': 'unknown', 'domain': 'unknown'}


def test_guardrail_fallback_requires_review():
    plan = build_profile('guardrails', request('guardrails'))
    assert resolve_profile(plan, None)['review_required']
    assert not resolve_profile(plan, {'guardrail': 'no_issue_detected'})['review_required']

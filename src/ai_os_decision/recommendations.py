"""Policy-first local recommendations. Never execute recommended actions."""
from __future__ import annotations

import math
import subprocess
import time
import uuid

from ai_os_decision.recommendation_profiles import build_profile, resolve_profile
from ai_os_decision.recommendation_validation import validate_request


def empty_result(profile: str, status: str) -> dict:
    return {'schema': 'ai-os-recommendation/v1', 'profile': profile, 'status': status,
            'decision_id': f'recommend-{uuid.uuid4().hex[:12]}', 'execution_enabled': False,
            'policy': None, 'recommendation': None,
            'laya': {'attempted': False, 'status': 'not_attempted', 'fallback_used': False,
                     'latency_ms': 0., 'error': None, 'observation': {}}}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _observe(result, questions):
    if result.provider != 'laya' or result.fallback_used or set(result.answers) != {q.id for q in questions}:
        raise ValueError('invalid model result')
    observed = {}
    for q in questions:
        a = result.answers[q.id]
        if (a.question_id != q.id or a.kind != q.kind or type(a.confidence) not in (int, float)
                or not math.isfinite(a.confidence) or not 0 <= a.confidence <= 1):
            raise ValueError('invalid model answer')
        if q.kind == 'choice' and (type(a.value) is not str or a.value not in q.options):
            raise ValueError('unknown model choice')
        if q.kind == 'score' and (type(a.value) not in (int, float) or not math.isfinite(a.value)
                                  or not 0 <= a.value <= len(q.criteria) - 1):
            raise ValueError('invalid model score')
        if q.kind == 'boolean' and type(a.value) is not bool:
            raise ValueError('invalid model boolean')
        observed[q.id] = a.value
    return observed


def recommend(profile: str, request: object, runtime) -> dict:
    out = empty_result(profile, 'invalid_request')
    try:
        data = validate_request(profile, request)
    except (TypeError, ValueError, OverflowError, RecursionError):
        return out
    if not runtime.policy.fail_closed:
        out['status'] = 'invalid_config'
        return out
    c = data['context']
    pieces = list(_strings(data))
    checks = [runtime.policy.check(piece, data['environment'], c.get('action', '') if profile == 'tool-risk' else '')
              for piece in [*pieces, ' '.join(pieces)]]
    policy = {'denied': any(p['denied'] for p in checks),
              'approval_required': any(p['approval_required'] for p in checks),
              'risk': max(p['risk'] for p in checks),
              'reasons': sorted({reason for p in checks for reason in p['reasons']})}
    if profile == 'tool-risk' and not c['permitted']:
        policy['denied'], policy['risk'] = True, 1.
        policy['reasons'].append('host_permission_missing')
    out['policy'] = policy
    if policy['denied']:
        out['status'], out['laya']['status'] = 'denied', 'skipped_policy'
        return out
    plan = build_profile(profile, data)
    observed = None
    if plan.skip_reason:
        out['laya']['status'] = plan.skip_reason
    else:
        started = time.perf_counter()
        out['laya']['attempted'] = True
        try:
            result = runtime.laya.decide(plan.state, plan.questions)
            observed = _observe(result, plan.questions)
            out['laya']['status'], out['laya']['observation'] = 'ok', observed
        except Exception as exc:
            if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
                error = 'timeout'
            elif isinstance(exc, (ValueError, TypeError, KeyError, AttributeError, OverflowError)):
                error = 'invalid_answer'
            elif type(exc).__name__ == 'ContextWindowExceeded':
                error = 'context_too_large'
            elif isinstance(exc, RuntimeError) and str(exc).startswith('worker-overloaded:'):
                error = 'overloaded'
            else:
                error = 'unavailable'
            out['laya'].update(status=error, error=error, fallback_used=True)
        out['laya']['latency_ms'] = round((time.perf_counter() - started) * 1000, 2)
    resolved = resolve_profile(plan, observed)
    out['recommendation'] = resolved['recommendation']
    out['status'] = 'review_required' if policy['approval_required'] or resolved['review_required'] else 'ready'
    return out

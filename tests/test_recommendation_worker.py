from types import SimpleNamespace

import pytest

from ai_os_decision.laya_engine import LayaDecisionEngine
from ai_os_decision.models import DecisionQuestion, DecisionState
from ai_os_decision.system_one_backends import MAX_CONCURRENT_WORKERS, _WORKER_SEMAPHORE, run_worker


def test_bounded_worker_admission():
    held = 0
    try:
        for _ in range(MAX_CONCURRENT_WORKERS):
            assert _WORKER_SEMAPHORE.acquire(blocking=False)
            held += 1
        with pytest.raises(RuntimeError, match='worker-overloaded'):
            run_worker('must-not-spawn', [], {}, .01)
    finally:
        for _ in range(held):
            _WORKER_SEMAPHORE.release()


@pytest.mark.parametrize('score,confidence', [('2', .9), (True, .9), (2., True), (2., '0.9'),
                                             (None, .9), (2., None)])
def test_profile_worker_rejects_raw_numeric_coercion(monkeypatch, score, confidence):
    engine = LayaDecisionEngine()
    agent = SimpleNamespace(system_one=lambda *a: {'answers': {
        'q': {'type': 'score', 'score': score, 'confidence': confidence}}})
    monkeypatch.setattr(engine, '_load', lambda: agent)
    monkeypatch.setattr('ai_os_decision.laya_engine.check_full_context', lambda *a: None)
    with pytest.raises(ValueError):
        engine.decide(DecisionState(text='test', extra={'_require_full_context': True}),
                      [DecisionQuestion('q', 'score', 'score relevance', criteria=['none', 'weak', 'strong'])])


def test_invalid_raw_answer_survives_worker_boundary(tmp_path):
    from ai_os_decision.cli import _runtime
    from ai_os_decision.recommendations import recommend
    from test_recommendation_validation import request
    model = tmp_path / 'checkpoint'
    model.mkdir()
    (model / 'rl_common.py').write_text('''
import json
serialize_state = json.dumps
def build_sequence(*args):
    return [], []
''')
    (model / 'rl_agent_api.py').write_text('''
class Tokenizer:
    mask_token = '[MASK]'
    def __call__(self, *args, **kwargs):
        return {'input_ids': []}
class RLAgent:
    def __init__(self, model_dir):
        self.tok = Tokenizer()
        self.cfg = {'max_len': 512, 'head_max_len': 192}
    def _to_internal(self, question):
        return question
    def system_one(self, state, questions):
        return {'answers': {'model': {'type': 'choice', 'choice': 'small', 'confidence': True}}}
''')
    out = recommend('model-routing', request('model-routing'),
                    _runtime('config.example.yaml', str(model), 2000, require_policy=True))
    assert out['laya']['fallback_used']
    assert out['laya']['error'] == 'invalid_answer'
    assert out['laya']['observation'] == {}

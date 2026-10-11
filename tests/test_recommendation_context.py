import sys
from types import SimpleNamespace

import pytest

from ai_os_decision.laya_engine import ContextWindowExceeded, check_full_context


def test_context_overflow_rejected_before_inference(monkeypatch):
    def build(tok, state, q, max_len, head_max_len):
        return [0] * 10, [1, 2]
    monkeypatch.setitem(sys.modules, 'rl_common', SimpleNamespace(
        serialize_state=lambda state: state.get('text', ''), build_sequence=build))
    tok = lambda text, **kwargs: {'input_ids': list(text)}
    tok.mask_token = '[MASK]'
    agent = SimpleNamespace(tok=tok, cfg={'max_len': 20, 'head_max_len': 10}, _to_internal=lambda q: q)
    check_full_context(agent, {'text': 'a' * 10}, {'q': {}})
    with pytest.raises(ContextWindowExceeded):
        check_full_context(agent, {'text': 'a' * 11}, {'q': {}})


def test_context_guard_fails_closed_for_unsupported_adapter():
    with pytest.raises(ContextWindowExceeded):
        check_full_context(object(), {}, {})

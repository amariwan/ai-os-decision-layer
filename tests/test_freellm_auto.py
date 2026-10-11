from dataclasses import replace
from argparse import Namespace

import pytest

from ai_os_decision.freellm_auto import select_model
from ai_os_decision.models import DecisionAnswer, DecisionResult
from test_system_one import request


def rows():
    return [{'id': 'alpha', 'name': 'Alpha', 'available': True, 'context_length': 32768, 'execution_status': 'ready'},
            {'id': 'beta', 'name': 'Beta', 'available': True, 'context_length': 32768, 'execution_status': 'ready'},
            {'id': 'locked', 'available': False, 'context_length': 32768, 'execution_status': 'needsKey'},
            {'id': 'auto', 'available': True, 'context_length': 32768, 'execution_status': 'ready'},
            {'id': 'embedding-only', 'available': True, 'context_length': 32768, 'execution_status': 'ready'},
            {'id': 'slot-alias', 'name': 'Slot (auto-routed)', 'available': True, 'context_length': 32768}]


CFG = {'policy': {'deny_patterns': ['BLOCK_THIS']},
       'freellm': {'enabled': True, 'allow_private': False, 'auto_enabled': True, 'allow_auto_calls': True}}


class Laya:
    def decide(self, state, questions):
        assert set(questions[0].options) == {'alpha', 'beta'}
        return DecisionResult({'model': DecisionAnswer('model', 'choice', 'beta', .9)}, 'laya', 1.)


def test_auto_selects_only_current_eligible_models():
    result = select_model(request(), CFG, rows(), Laya())
    assert result['model'] == 'beta' and result['source'] == 'laya'
    assert result['pricing'] == 'unknown'
    assert result['mode'] == 'auto'
    assert result['candidates'] == ['beta', 'alpha']


def test_rows_without_ready_status_are_not_candidates():
    data = rows() + [{'id': 'ghost', 'available': True, 'context_length': 32768,
                      'execution_status': 'needsKey'}]
    result = select_model(request(), CFG, data, Laya())
    assert 'ghost' not in result['candidates'] and 'slot-alias' not in result['candidates']


def test_auto_free_marks_mode_but_keeps_eligible_candidates():
    result = select_model(request(), CFG, rows(), Laya(), free_only=True)
    assert result['mode'] == 'auto_free' and result['candidates'] == ['beta', 'alpha']


@pytest.mark.parametrize('text', ['BLOCK_THIS', 'password=do-not-transfer'])
def test_restricted_input_never_reaches_laya(text):
    class NoCall:
        def decide(self, *a):
            raise AssertionError('must not infer')
    result = select_model(request(text), CFG, rows(), NoCall())
    assert result['model'] is None and result['status'] == 'blocked'


def test_sensitive_question_never_reaches_laya():
    r = request()
    r.questions[0].options['atlas'] = 'password=secret'
    result = select_model(r, CFG, rows(), Laya())
    assert result['model'] is None


def test_auto_cannot_override_required_approval():
    r = replace(request(), approval_required=True)
    assert select_model(r, CFG, rows(), Laya())['model'] is None


def test_trusted_boolean_approval_blocks_cloud():
    from ai_os_decision.models import DecisionQuestion
    r = request()
    r = replace(r, questions=(DecisionQuestion('requires_human_approval', 'boolean', 'Approval?'),),
                fallback_answers={'requires_human_approval': True}, candidate_kinds={})
    assert select_model(r, CFG, rows(), Laya())['model'] is None


def test_laya_failure_has_visible_deterministic_fallback():
    class Failing:
        def decide(self, *a):
            raise TimeoutError()
    result = select_model(request(), CFG, rows(), Failing())
    assert result['model'] == 'alpha' and result['fallback_used']
    assert result['candidates'] == ['alpha', 'beta']


def test_context_and_allowlist_filter():
    cfg = {**CFG, 'freellm': {**CFG['freellm'], 'allowed_models': ['beta']}}
    assert select_model(request(), cfg, rows(), Laya())['model'] == 'beta'
    data = rows()
    data[1]['context_length'] = 1
    assert select_model(request(), cfg, data, Laya())['model'] is None


@pytest.mark.parametrize('value', ['true', 1, False])
def test_auto_requires_explicit_boolean_flag(value):
    cfg = {**CFG, 'freellm': {**CFG['freellm'], 'auto_enabled': value}}
    assert select_model(request(), cfg, rows(), Laya())['model'] is None


def test_cli_auto_refreshes_models_and_runs_selected_backend(monkeypatch, capsys):
    import json
    from argparse import Namespace
    from ai_os_decision import system_one_io as io
    captured = []
    from ai_os_decision.system_one import Capability, CapabilitySnapshot
    original = request()
    original = replace(original, inventory=CapabilitySnapshot(original.inventory.capabilities +
                       (Capability('beta', 'tool', 'client-exposed'),)))
    monkeypatch.setattr(io, 'read_request', lambda p: original)
    monkeypatch.setattr(io, 'load_config', lambda p: CFG)
    monkeypatch.setattr(io, 'freellm_inventory_rows', lambda p: rows())
    monkeypatch.setattr('ai_os_decision.cli._runtime', lambda *a, **kw: Namespace(laya=Laya()))

    class Backend:
        name = 'freellm'
        def __init__(self, model, inventory, **kw):
            captured.append(model)
            assert model in inventory.ids('model')
            assert 'beta' in inventory.ids('tool')
        def infer(self, req):
            return {'answers': {'tool': {'type': 'choice', 'choice': 'atlas', 'confidence': 1.,
                                        'probabilities': {'terminal': 0., 'atlas': 1.}}},
                    'usage': {'input_tokens': 0, 'output_tokens': 0}}
    monkeypatch.setattr(io, 'FreeLLMBackend', Backend)
    args = Namespace(request='unused', backend='freellm', model=None, config=None, approve_cloud=False)
    assert io.run_cli(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['model_routing']['model'] == 'beta'
    assert captured == ['beta']


def test_cli_private_input_does_not_discover_or_infer(monkeypatch, capsys):
    from argparse import Namespace
    from ai_os_decision import system_one_io as io
    monkeypatch.setattr(io, 'read_request', lambda p: request('password=secret'))
    monkeypatch.setattr(io, 'load_config', lambda p: CFG)
    monkeypatch.setattr(io, 'freellm_inventory_rows', lambda p: pytest.fail('no gateway calls'))
    args = Namespace(request='unused', backend='freellm', model='auto', config=None, approve_cloud=False)
    assert io.run_cli(args) == 2


def test_invalid_laya_result_is_a_visible_fallback():
    class Invalid:
        def decide(self, *a):
            return DecisionResult({'model': DecisionAnswer('wrong', 'boolean', 'beta', .9)}, 'rule', 1.)
    result = select_model(request(), CFG, rows(), Invalid())
    assert result['fallback_used'] and result['source'] == 'deterministic'


def _tool_answer(choice='atlas', measurement=None):
    raw = {'answers': {'tool': {'type': 'choice', 'choice': choice, 'confidence': 1.,
                                'probabilities': {'terminal': 0., 'atlas': 1.}}},
           'usage': {'input_tokens': 1, 'output_tokens': 1}}
    if measurement is not None:
        raw['measurement'] = measurement
    return raw


def _cli_setup(monkeypatch):
    from ai_os_decision import system_one_io as io
    from ai_os_decision.system_one import Capability, CapabilitySnapshot
    original = request()
    original = replace(original, inventory=CapabilitySnapshot(original.inventory.capabilities +
                       (Capability('beta', 'tool', 'client-exposed'),)))
    monkeypatch.setattr(io, 'read_request', lambda p: original)
    monkeypatch.setattr(io, 'load_config', lambda p: CFG)
    monkeypatch.setattr(io, 'freellm_inventory_rows', lambda p: rows())
    monkeypatch.setattr('ai_os_decision.cli._runtime', lambda *a, **kw: Namespace(laya=Laya()))
    return io


def test_cli_auto_fails_over_to_next_candidate(monkeypatch, capsys):
    import json
    from argparse import Namespace
    io = _cli_setup(monkeypatch)
    captured = []

    class Backend:
        name = 'freellm'
        def __init__(self, model, inventory, **kw):
            captured.append(model)
            assert model in inventory.ids('model')
        def infer(self, req):
            if captured[-1] == 'beta':
                raise ValueError('cloud rejected request')
            return _tool_answer()
    monkeypatch.setattr(io, 'FreeLLMBackend', Backend)
    args = Namespace(request='unused', backend='freellm', model='auto', config=None, approve_cloud=False)
    assert io.run_cli(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['model_routing']['model'] == 'alpha'
    assert captured == ['beta', 'alpha']
    assert out['model_routing']['attempts'] == [
        {'model': 'beta', 'error': 'ValueError'}, {'model': 'alpha', 'error': None}]


def test_cli_auto_free_accepts_only_zero_cost_evidence(monkeypatch, capsys):
    import json
    from argparse import Namespace
    io = _cli_setup(monkeypatch)
    captured = []

    class Backend:
        name = 'freellm'
        def __init__(self, model, inventory, **kw):
            captured.append(model)
        def infer(self, req):
            if captured[-1] == 'beta':
                return _tool_answer(measurement={'cost': 1, 'is_byok': False})
            return _tool_answer(measurement={'cost': 0, 'upstream_cost': 0, 'is_byok': False})
    monkeypatch.setattr(io, 'FreeLLMBackend', Backend)
    args = Namespace(request='unused', backend='freellm', model='auto-free', config=None, approve_cloud=False)
    assert io.run_cli(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out['model_routing']['mode'] == 'auto_free'
    assert out['model_routing']['model'] == 'alpha'
    assert out['model_routing']['attempts'] == [
        {'model': 'beta', 'error': 'non_free_cost'}, {'model': 'alpha', 'error': None}]


def test_cli_auto_free_blocks_without_free_evidence(monkeypatch, capsys):
    import json
    from argparse import Namespace
    io = _cli_setup(monkeypatch)

    class Backend:
        name = 'freellm'
        def __init__(self, model, inventory, **kw):
            pass
        def infer(self, req):
            return _tool_answer()  # no cost measurement: unverified, never free
    monkeypatch.setattr(io, 'FreeLLMBackend', Backend)
    args = Namespace(request='unused', backend='freellm', model='auto-free', config=None, approve_cloud=False)
    assert io.run_cli(args) == 2
    out = json.loads(capsys.readouterr().out)
    assert out['model_routing']['model'] is None
    assert out['cloud_eligibility']['reason'] == 'no_free_model'

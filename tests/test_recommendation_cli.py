import json
import sys

from ai_os_decision.cli import main
from test_recommendation_validation import request
from test_recommendations import Fake, runtime


def invoke(tmp_path, monkeypatch, capsys, profile='model-routing', engine=None, extra=(), raw=None):
    path = tmp_path / 'request.json'
    path.write_text(raw if raw is not None else json.dumps(request(profile)))
    monkeypatch.setattr('ai_os_decision.cli._runtime', lambda *a, **kw: runtime(engine))
    monkeypatch.setattr(sys, 'argv', ['ai-os', 'recommend', profile, str(path), *extra])
    code = main()
    return code, json.loads(capsys.readouterr().out)


def test_recommend_cli_success(tmp_path, monkeypatch, capsys):
    code, out = invoke(tmp_path, monkeypatch, capsys)
    assert code == 0 and out['laya']['status'] == 'ok'


def test_require_laya_exit_3(tmp_path, monkeypatch, capsys):
    code, out = invoke(tmp_path, monkeypatch, capsys, engine=Fake(RuntimeError('unavailable')),
                       extra=('--require-laya',))
    assert code == 3 and out['laya']['fallback_used']


def test_review_precedes_strict_exit(tmp_path, monkeypatch, capsys):
    code, out = invoke(tmp_path, monkeypatch, capsys, 'tool-risk', Fake(RuntimeError('unavailable')),
                       ('--require-laya',))
    assert code == 2 and out['status'] == 'review_required'


def test_duplicate_json_exit_2(tmp_path, monkeypatch, capsys):
    code, out = invoke(tmp_path, monkeypatch, capsys, raw='{"text":"a","text":"b"}')
    assert code == 2 and out['status'] == 'invalid_request'


def test_invalid_config_json(tmp_path, monkeypatch, capsys):
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request('model-routing')))
    monkeypatch.setattr(sys, 'argv', ['ai-os', 'recommend', 'model-routing', str(path),
                                     '--config', str(tmp_path / 'missing')])
    code = main()
    assert code == 2
    assert json.loads(capsys.readouterr().out)['status'] == 'invalid_config'

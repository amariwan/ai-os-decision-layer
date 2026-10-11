import pytest

from ai_os_decision.gateway_credentials import gateway_key, normalize_gateway_url


def test_gateway_url_accepts_user_v1_base_once():
    assert normalize_gateway_url('http://127.0.0.1:31415/v1/') == 'http://127.0.0.1:31415'


@pytest.mark.parametrize('url', ['https://example.com', 'http://127.0.0.1:31415/a',
                                'http://u:p@127.0.0.1:31415', 'http://localhost:31415?x=1'])
def test_gateway_url_rejects_remote_credentials_and_other_paths(url):
    with pytest.raises(ValueError):
        normalize_gateway_url(url)


def test_environment_credentials_win_without_keychain(monkeypatch):
    monkeypatch.setenv('FREELLMAPI_KEY', 'synthetic-only')
    monkeypatch.setattr('ai_os_decision.gateway_credentials._keychain',
                        lambda *a: (_ for _ in ()).throw(AssertionError('must not access keychain')))
    assert gateway_key() == 'synthetic-only'


def test_keychain_is_used_without_environment(monkeypatch):
    monkeypatch.delenv('FREELLMAPI_KEY', raising=False)
    monkeypatch.setattr('ai_os_decision.gateway_credentials._keychain', lambda: 'from-keychain')
    assert gateway_key() == 'from-keychain'


def test_gateway_never_follows_authenticated_redirect(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from ai_os_decision.system_one_worker import cloud_json
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header('Location', '/other')
            self.end_headers()

        def log_message(self, *args):
            pass

    monkeypatch.setenv('FREELLMAPI_KEY', 'synthetic-only')
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result, _ = cloud_json(f'http://127.0.0.1:{server.server_port}/v1', '/v1/models')
        assert 'transport_error' in result
        assert seen == ['/v1/models']
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

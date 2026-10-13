"""The agent's local web server: loopback only, a token in the URL fragment turned into an HttpOnly cookie, a Host
allow-list, no CORS. Everything an attacker's web page in the same browser could try must fail."""

import http.client
import json

import pytest

from driftwatch_llm.agent.dashboard import DashboardServer

PID = "11111111-2222-4333-8444-555555555555"


class Provider:
    def __init__(self):
        self.touched = 0

    def projects(self):
        return [PID]

    def series(self, project_id, range_name):
        return {"embedding_drift": [{"timestamp": "2026-10-13T10:00:00+00:00", "value": 0.05}], "combined_score": []}

    def status(self):
        return {"sync": {"state": "synced", "pending": 0}, "embedder": "ready"}

    def touch(self):
        self.touched += 1


@pytest.fixture
def server(tmp_path):
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>shell</html>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")
    provider = Provider()
    s = DashboardServer(provider, static_dir=static)
    s.port = s.start()
    s.provider = provider
    yield s
    s.stop()


def req(server, method, path, headers=None, body=None, host=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    h = {"Host": host or f"127.0.0.1:{server.port}"}
    h.update(headers or {})
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    for k, v in h.items():
        conn.putheader(k, v)
    data = body.encode() if isinstance(body, str) else body
    if data is not None:
        conn.putheader("Content-Length", str(len(data)))
    conn.endheaders(data)
    r = conn.getresponse()
    out = (r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read())
    conn.close()
    return out


def login(server):
    status, headers, _ = req(server, "POST", "/session", {"Content-Type": "application/json"}, json.dumps({"token": server.token}))
    assert status == 204
    return headers["set-cookie"].split(";")[0]


def test_it_listens_on_loopback_only(server):
    assert server.address[0] == "127.0.0.1"


def test_the_shell_is_served_without_a_session_but_no_data_is(server):
    status, headers, body = req(server, "GET", "/")
    assert status == 200 and b"shell" in body and "no-store" in headers["cache-control"]
    assert req(server, "GET", "/api/projects")[0] == 401
    assert req(server, "GET", f"/api/series?project={PID}&range=24h")[0] == 401
    assert req(server, "GET", "/api/status")[0] == 401


def test_the_token_becomes_an_httponly_samesite_strict_cookie(server):
    status, headers, _ = req(server, "POST", "/session", {"Content-Type": "application/json"}, json.dumps({"token": server.token}))
    cookie = headers["set-cookie"]
    assert status == 204 and "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Path=/" in cookie
    assert server.token not in cookie  # the cookie is a separate session id, not the URL token itself


def test_the_token_works_once_so_a_link_seen_in_a_process_list_is_useless_afterwards(server):
    old = server.token
    login(server)
    again = req(server, "POST", "/session", {"Content-Type": "application/json"}, json.dumps({"token": old}))
    assert again[0] == 401 and "set-cookie" not in again[1]
    fresh = server.issue_token()  # `driftwatch dashboard` again: a new link, the old one stays dead
    assert fresh != old
    assert req(server, "POST", "/session", {"Content-Type": "application/json"}, json.dumps({"token": old}))[0] == 401
    assert req(server, "POST", "/session", {"Content-Type": "application/json"}, json.dumps({"token": fresh}))[0] == 204


def test_a_wrong_missing_or_malformed_token_gets_no_session(server):
    json_h = {"Content-Type": "application/json"}
    for body in (json.dumps({"token": "nope"}), json.dumps({}), "not json", json.dumps({"token": 5}), json.dumps(["x"])):
        status, headers, _ = req(server, "POST", "/session", json_h, body)
        assert status in (400, 401, 403) and "set-cookie" not in headers


def test_a_session_needs_a_json_content_type_so_a_cross_site_form_cannot_make_one(server):
    status, headers, _ = req(server, "POST", "/session", {"Content-Type": "text/plain"}, json.dumps({"token": server.token}))
    assert status == 415 and "set-cookie" not in headers


def test_with_the_cookie_the_api_answers(server):
    cookie = login(server)
    h = {"Cookie": cookie}
    status, headers, body = req(server, "GET", "/api/projects", h)
    assert status == 200 and json.loads(body) == [PID] and "no-store" in headers["cache-control"]
    status, _, body = req(server, "GET", f"/api/series?project={PID}&range=24h", h)
    assert status == 200 and json.loads(body)["embedding_drift"][0]["value"] == 0.05
    status, _, body = req(server, "GET", "/api/status", h)
    assert status == 200 and json.loads(body)["sync"]["state"] == "synced"
    assert server.provider.touched >= 3  # a viewer keeps the agent alive


def test_a_forged_or_other_cookie_is_refused(server):
    login(server)
    assert req(server, "GET", "/api/projects", {"Cookie": "dw_session=forged"})[0] == 401


def test_a_foreign_host_header_is_refused_even_with_a_valid_cookie(server):
    cookie = login(server)  # DNS rebinding: the attacker's name resolves to 127.0.0.1, the browser sends their Host
    for host in ("evil.example.com", f"evil.example.com:{server.port}", "127.0.0.1", f"127.0.0.1:{server.port + 1}", f"[::1]:{server.port}"):
        status, _, body = req(server, "GET", "/api/projects", {"Cookie": cookie}, host=host)
        assert status == 403 and PID.encode() not in body, host
    assert req(server, "GET", "/", host="evil.example.com")[0] == 403
    assert req(server, "GET", "/api/projects", {"Cookie": cookie}, host=f"localhost:{server.port}")[0] == 200


def test_a_foreign_origin_is_refused_and_there_are_no_cors_headers(server):
    cookie = login(server)
    status, headers, _ = req(server, "GET", "/api/projects", {"Cookie": cookie, "Origin": "https://evil.example.com"})
    assert status == 403 and not any(k.startswith("access-control") for k in headers)
    status, headers, _ = req(server, "GET", "/api/projects", {"Cookie": cookie, "Origin": f"http://127.0.0.1:{server.port}"})
    assert status == 200 and not any(k.startswith("access-control") for k in headers)
    forged = req(server, "POST", "/session", {"Content-Type": "application/json", "Origin": "https://evil.example.com"},
                 json.dumps({"token": server.token}))
    assert forged[0] == 403 and "set-cookie" not in forged[1]
    status, headers, _ = req(server, "OPTIONS", "/api/projects", {"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"})
    assert status in (403, 405, 501) and not any(k.startswith("access-control") for k in headers)


def test_cross_site_fetch_metadata_is_refused(server):
    cookie = login(server)
    assert req(server, "GET", "/api/projects", {"Cookie": cookie, "Sec-Fetch-Site": "cross-site"})[0] == 403
    assert req(server, "GET", "/api/projects", {"Cookie": cookie, "Sec-Fetch-Site": "same-origin"})[0] == 200


def test_bad_parameters_are_rejected_not_passed_on(server):
    h = {"Cookie": login(server)}
    for path in (
        "/api/series",
        "/api/series?project=../../etc&range=24h",
        f"/api/series?project={PID}&range=forever",
        f"/api/series?project={PID}&range=24h&project={PID}",
    ):
        assert req(server, "GET", path, h)[0] == 400, path


def test_static_files_cannot_escape_their_folder(server):
    assert req(server, "GET", "/assets/app.js")[0] == 200
    for path in ("/assets/../../secret.txt", "/assets/%2e%2e/%2e%2e/secret.txt", "/..%2fsecret.txt", "/assets/..%5c..%5csecret.txt"):
        status, _, body = req(server, "GET", path)
        assert status in (400, 404) and b"outside" not in body, path


def test_security_headers_on_every_response(server):
    _, headers, _ = req(server, "GET", "/")
    csp = headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp and "default-src 'self'" in csp
    assert headers["x-content-type-options"] == "nosniff" and headers["referrer-policy"] == "no-referrer"


def test_without_built_files_a_plain_explanation_is_shown(tmp_path):
    s = DashboardServer(Provider(), static_dir=tmp_path / "missing")
    s.port = s.start()
    try:
        status, _, body = req(s, "GET", "/")
        assert status == 200 and b"not included" in body.lower()
    finally:
        s.stop()


def test_only_get_and_the_session_post_exist(server):
    cookie = login(server)
    for method in ("PUT", "DELETE", "PATCH"):
        assert req(server, method, "/api/projects", {"Cookie": cookie})[0] in (405, 501)
    assert req(server, "POST", "/api/projects", {"Cookie": cookie, "Content-Type": "application/json"}, "{}")[0] in (404, 405)


def test_an_oversized_session_body_is_refused(server):
    try:
        status, _, _ = req(server, "POST", "/session", {"Content-Type": "application/json"}, "x" * 100_000)
    except (ConnectionError, http.client.HTTPException):
        return  # the server hung up without reading the body: also a refusal
    assert status in (400, 413)

import json

import httpx
import pytest

from driftwatch_llm.api import Api, ApiError, DeviceStart, PollResult
from driftwatch_llm.endpoints import Endpoints

EP = Endpoints(supabase_url="https://example.supabase.co", publishable_key="sb_publishable_test", web_origin="https://web.example")
DEVICE_CODE = "d" * 64
KEY = "dw_0123456789_" + "a" * 64
PID = "11111111-1111-4111-8111-111111111111"


def api_with(handler):
    seen: list[httpx.Request] = []

    def wrapper(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return Api(EP, transport=httpx.MockTransport(wrapper)), seen


def reply(data, status=200):
    return lambda request: httpx.Response(status, json=data)


def test_start_device_login_posts_to_the_rpc_with_only_the_publishable_key():
    api, seen = api_with(reply({"device_code": DEVICE_CODE, "user_code": "BCDFGHJK", "expires_in": 600, "interval": 5}))
    out = api.start_device_login("laptop", "Linux 6.1")
    assert out == DeviceStart(device_code=DEVICE_CODE, user_code="BCDFGHJK", expires_in=600, interval=5)
    req = seen[0]
    assert req.method == "POST"
    assert str(req.url) == "https://example.supabase.co/rest/v1/rpc/start_device_login"
    assert req.headers["apikey"] == "sb_publishable_test"
    assert "authorization" not in req.headers
    assert json.loads(req.content) == {"p_device_name": "laptop", "p_device_os": "Linux 6.1"}
    assert req.headers["user-agent"].startswith("driftwatch-llm/")


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"device_code": "short", "user_code": "BCDFGHJK", "expires_in": 600, "interval": 5},
        {"device_code": DEVICE_CODE, "user_code": "bcdfghjk", "expires_in": 600, "interval": 5},
        {"device_code": DEVICE_CODE, "user_code": "BCDFGHJK", "expires_in": "600", "interval": 5},
        {"device_code": DEVICE_CODE, "user_code": "BCDFGHJK", "expires_in": 600, "interval": 0},
        ["not", "an", "object"],
        None,
    ],
)
def test_start_rejects_malformed_responses(bad):
    api, _ = api_with(reply(bad))
    with pytest.raises(ApiError) as exc:
        api.start_device_login("laptop", "Linux")
    assert "Unexpected response" in str(exc.value)


def test_poll_returns_status_and_only_approved_carries_a_key():
    api, seen = api_with(reply({"status": "approved", "api_key": KEY, "project_id": PID, "project_name": "My app"}))
    out = api.poll_device_login(DEVICE_CODE)
    assert out == PollResult(status="approved", api_key=KEY, project_id=PID, project_name="My app")
    assert json.loads(seen[0].content) == {"p_device_code": DEVICE_CODE}
    assert str(seen[0].url).endswith("/rest/v1/rpc/poll_device_login")
    for status in ("authorization_pending", "slow_down", "access_denied", "expired_token", "key_limit"):
        api2, _ = api_with(reply({"status": status}))
        assert api2.poll_device_login(DEVICE_CODE) == PollResult(status=status)


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "approved", "api_key": "nope", "project_id": PID, "project_name": "x"},
        {"status": "approved", "api_key": KEY, "project_id": "not-a-uuid", "project_name": "x"},
        {"status": "approved", "project_id": PID, "project_name": "x"},
        {"status": "authorization_pending", "api_key": KEY},  # a key outside "approved" is never accepted
        {"status": "mystery"},
        {"nostatus": 1},
    ],
)
def test_poll_rejects_inconsistent_responses_without_echoing_them(bad):
    api, _ = api_with(reply(bad))
    with pytest.raises(ApiError) as exc:
        api.poll_device_login(DEVICE_CODE)
    assert KEY not in str(exc.value) and "mystery" not in str(exc.value)


def test_poll_cleans_the_project_name_it_will_print():
    api, _ = api_with(reply({"status": "approved", "api_key": KEY, "project_id": PID, "project_name": "a\x1b[31mb\n" + "x" * 200}))
    out = api.poll_device_login(DEVICE_CODE)
    assert "\x1b" not in out.project_name and "\n" not in out.project_name
    assert len(out.project_name) <= 64


def test_revoke_posts_the_key_and_tolerates_an_empty_body():
    api, seen = api_with(lambda r: httpx.Response(204))
    api.revoke_api_key(KEY)
    assert json.loads(seen[0].content) == {"p_api_key": KEY}
    assert str(seen[0].url).endswith("/rest/v1/rpc/revoke_api_key_by_secret")
    api2, _ = api_with(lambda r: httpx.Response(200, content=b"null", headers={"content-type": "application/json"}))
    api2.revoke_api_key(KEY)


def test_errors_map_to_fixed_sentences():
    cases = [
        (429, {"code": "PT429", "message": "raw"}, "Too many sign-in requests"),
        (422, {"code": "PT422", "message": "invalid device name"}, "invalid device name"),
        (500, {"code": "XX000", "message": "relation secret_table is broken"}, "HTTP 500"),
        (401, {"message": "JWT invalid"}, "not accepted"),
    ]
    for status, body, expect in cases:
        api, _ = api_with(reply(body, status))
        with pytest.raises(ApiError) as exc:
            api.start_device_login("laptop", "Linux")
        assert expect in str(exc.value), (status, str(exc.value))
        assert "secret_table" not in str(exc.value) and "JWT" not in str(exc.value)


def test_non_json_and_network_failures_are_fixed_sentences_that_hide_secrets():
    api, _ = api_with(lambda r: httpx.Response(200, content=b"<html>oops</html>"))
    with pytest.raises(ApiError) as exc:
        api.poll_device_login(DEVICE_CODE)
    assert "Unexpected response" in str(exc.value)

    def boom(request):
        raise httpx.ConnectTimeout(f"timed out talking to {request.url} with {DEVICE_CODE}")

    api2, _ = api_with(boom)
    with pytest.raises(ApiError) as net:
        api2.poll_device_login(DEVICE_CODE)
    assert "Could not reach DriftWatch" in str(net.value)
    assert DEVICE_CODE not in str(net.value) and DEVICE_CODE not in repr(net.value)


def test_422_message_from_the_server_is_clipped():
    api, _ = api_with(reply({"code": "PT422", "message": "x" * 500}, 422))
    with pytest.raises(ApiError) as exc:
        api.start_device_login("a", "b")
    assert len(str(exc.value)) <= 140

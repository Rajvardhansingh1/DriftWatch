"""Api.ingest_event: the call the local agent uses to deliver events."""
import json

import httpx
import pytest

from driftwatch_llm.api import Api, AuthRejected, Rejected, TransientError
from driftwatch_llm.endpoints import Endpoints

EP = Endpoints(supabase_url="https://example.supabase.co", publishable_key="sb_publishable_test", web_origin="https://web.example")
KEY = "dw_0123456789_" + "a" * 64
EVENT = {"event_id": "00000000-0000-4000-8000-000000000001", "signal": "embedding_drift", "value": 0.1}


def api_with(handler):
    seen: list[httpx.Request] = []

    def wrapper(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return Api(EP, transport=httpx.MockTransport(wrapper)), seen


def test_posts_the_key_and_event_and_returns_the_server_word():
    api, seen = api_with(lambda r: httpx.Response(200, json="accepted"))
    assert api.ingest_event(KEY, EVENT) == "accepted"
    req = seen[0]
    assert str(req.url) == "https://example.supabase.co/rest/v1/rpc/ingest_event"
    assert json.loads(req.content) == {"p_api_key": KEY, "p_event": EVENT}
    assert req.headers["apikey"] == "sb_publishable_test" and "authorization" not in req.headers
    api2, _ = api_with(lambda r: httpx.Response(200, json="duplicate"))
    assert api2.ingest_event(KEY, EVENT) == "duplicate"


@pytest.mark.parametrize(
    "status,body,headers,expected,retry_after",
    [
        (401, {"code": "PT401", "message": "unauthorized"}, {}, AuthRejected, None),
        (422, {"code": "PT422", "message": "unknown signal"}, {}, Rejected, None),
        (429, {"code": "PT429", "message": "rate limited"}, {"Retry-After": "120"}, TransientError, 120.0),
        (429, {"code": "PT429"}, {}, TransientError, None),
        (503, {"message": "down"}, {"Retry-After": "7"}, TransientError, 7.0),
        (500, {"code": "XX000", "message": "boom"}, {}, TransientError, None),
        (401, {"message": "Invalid API key"}, {}, TransientError, None),  # the gateway, not our key check
        (403, {"message": "forbidden"}, {}, TransientError, None),
    ],
)
def test_failures_are_classified(status, body, headers, expected, retry_after):
    api, _ = api_with(lambda r: httpx.Response(status, json=body, headers=headers))
    with pytest.raises(expected) as exc:
        api.ingest_event(KEY, EVENT)
    assert type(exc.value) is expected
    assert getattr(exc.value, "retry_after", None) == retry_after
    assert KEY not in str(exc.value) and "boom" not in str(exc.value)


def test_retry_after_is_capped_and_http_dates_are_ignored():
    api, _ = api_with(lambda r: httpx.Response(429, json={"code": "PT429"}, headers={"Retry-After": "999999"}))
    with pytest.raises(TransientError) as exc:
        api.ingest_event(KEY, EVENT)
    assert exc.value.retry_after == 3600.0
    date = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
    api2, _ = api_with(lambda r: httpx.Response(429, json={"code": "PT429"}, headers=date))
    with pytest.raises(TransientError) as exc2:
        api2.ingest_event(KEY, EVENT)
    assert exc2.value.retry_after is None


def test_network_errors_and_odd_bodies_are_transient_and_hide_the_key():
    def boom(request):
        raise httpx.ConnectTimeout(f"timed out sending {KEY}")

    api, _ = api_with(boom)
    with pytest.raises(TransientError) as exc:
        api.ingest_event(KEY, EVENT)
    assert KEY not in str(exc.value) and KEY not in repr(exc.value)
    for odd in ({"status": "ok"}, 5, None, ["accepted"]):
        api2, _ = api_with(lambda r, odd=odd: httpx.Response(200, json=odd))
        with pytest.raises(TransientError):
            api2.ingest_event(KEY, EVENT)

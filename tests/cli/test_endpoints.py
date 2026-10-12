import pytest

from driftwatch_llm.endpoints import PINNED, EndpointError, resolve

DEV_ENV = {
    "DRIFTWATCH_DEV_SUPABASE_URL": "http://127.0.0.1:54321",
    "DRIFTWATCH_DEV_SUPABASE_KEY": "dev-key",
    "DRIFTWATCH_DEV_WEB_ORIGIN": "http://127.0.0.1:3100/",
}


def test_pinned_values_are_the_driftwatch_project():
    assert PINNED.supabase_url == "https://zaodlvgqowhdqobvvhpx.supabase.co"
    assert PINNED.web_origin == "https://drift-watch-rouge.vercel.app"
    assert PINNED.publishable_key.startswith("sb_publishable_")
    assert "service_role" not in PINNED.publishable_key


def test_pinned_endpoints_are_immutable():
    with pytest.raises(Exception):
        PINNED.supabase_url = "https://evil.example"  # type: ignore[misc]


def test_dev_environment_variables_are_ignored_without_the_dev_flag():
    assert resolve(dev=False, env=DEV_ENV) == PINNED


def test_dev_flag_without_variables_still_uses_the_pinned_endpoints():
    assert resolve(dev=True, env={}) == PINNED


def test_dev_flag_uses_the_dev_variables_and_strips_trailing_slashes():
    got = resolve(dev=True, env=DEV_ENV)
    assert got.supabase_url == "http://127.0.0.1:54321"
    assert got.publishable_key == "dev-key"
    assert got.web_origin == "http://127.0.0.1:3100"


@pytest.mark.parametrize(
    "url",
    ["http://example.com", "http://192.168.1.5:54321", "ftp://localhost", "file:///etc/passwd", "localhost:54321", ""],
)
def test_dev_flag_refuses_plain_http_to_remote_hosts_and_other_schemes(url):
    env = {**DEV_ENV, "DRIFTWATCH_DEV_SUPABASE_URL": url}
    if url == "":
        assert resolve(dev=True, env=env).supabase_url == PINNED.supabase_url  # empty means unset
        return
    with pytest.raises(EndpointError):
        resolve(dev=True, env=env)


def test_dev_flag_allows_https_to_any_host_and_http_to_loopback_only():
    env = {**DEV_ENV, "DRIFTWATCH_DEV_SUPABASE_URL": "https://staging.example.org"}
    assert resolve(dev=True, env=env).supabase_url == "https://staging.example.org"
    env = {**DEV_ENV, "DRIFTWATCH_DEV_WEB_ORIGIN": "http://localhost:3000"}
    assert resolve(dev=True, env=env).web_origin == "http://localhost:3000"


def test_endpoint_error_does_not_echo_a_secret_in_the_url():
    env = {**DEV_ENV, "DRIFTWATCH_DEV_SUPABASE_URL": "http://user:hunter2@example.com"}
    with pytest.raises(EndpointError) as exc:
        resolve(dev=True, env=env)
    assert "hunter2" not in str(exc.value)

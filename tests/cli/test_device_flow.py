import pytest

from driftwatch_llm.api import ApiError, DeviceStart, PollResult
from driftwatch_llm.device_flow import LoginDenied, LoginExpired, LoginFailed, run_device_login

DEVICE_CODE = "d" * 64
KEY = "dw_0123456789_" + "a" * 64
PID = "11111111-1111-4111-8111-111111111111"
APPROVED = PollResult(status="approved", api_key=KEY, project_id=PID, project_name="My app")
ORIGIN = "https://web.example"


class FakeApi:
    def __init__(self, polls, expires_in=600, interval=5):
        self._polls = list(polls)
        self.start = DeviceStart(device_code=DEVICE_CODE, user_code="BCDFGHJK", expires_in=expires_in, interval=interval)
        self.poll_calls = 0

    def start_device_login(self, name, os_name):
        self.started_with = (name, os_name)
        return self.start

    def poll_device_login(self, code):
        assert code == DEVICE_CODE
        self.poll_calls += 1
        item = self._polls.pop(0) if self._polls else PollResult(status="authorization_pending")
        if isinstance(item, Exception):
            raise item
        return item


class Clock:
    """Virtual time: sleeping advances it, so deadlines are tested without waiting."""

    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def __call__(self):
        return self.now


def run(api, clock=None, open_browser=True, open_url=None, lines=None):
    clock = clock or Clock()
    out = [] if lines is None else lines
    opened = []

    def default_open(url):
        opened.append(url)
        return True

    result = run_device_login(
        api, device_name="laptop", device_os="Linux 6.1", web_origin=ORIGIN, open_browser=open_browser,
        echo=out.append, open_url=open_url or default_open, sleep=clock.sleep, clock=clock,
    )
    return result, out, opened, clock


def test_prints_the_code_and_link_and_opens_only_the_pinned_origin():
    api = FakeApi([APPROVED])
    result, out, opened, _ = run(api)
    text = "\n".join(out)
    assert "BCDF-GHJK" in text
    assert f"{ORIGIN}/auth/device?code=BCDF-GHJK" in text
    assert "only approve" in text.lower()
    assert opened == [f"{ORIGIN}/auth/device?code=BCDF-GHJK"]
    assert result == APPROVED
    assert api.started_with == ("laptop", "Linux 6.1")


def test_no_browser_flag_never_opens_one():
    _, out, opened, _ = run(FakeApi([APPROVED]), open_browser=False)
    assert opened == []
    assert any("Open this link" in line or "open this link" in line.lower() for line in out)


def test_a_browser_that_fails_to_open_is_not_fatal():
    def explode(url):
        raise RuntimeError("no display")

    result, out, _, _ = run(FakeApi([APPROVED]), open_url=explode)
    assert result == APPROVED
    assert any("could not open" in line.lower() for line in out)
    result2, out2, _, _ = run(FakeApi([APPROVED]), open_url=lambda url: False)
    assert any("could not open" in line.lower() for line in out2)


def test_waits_the_interval_between_polls_and_slows_down_by_five_seconds():
    api = FakeApi(
        [PollResult(status="authorization_pending"), PollResult(status="slow_down"), PollResult(status="authorization_pending"), APPROVED]
    )
    _, _, _, clock = run(api)
    assert clock.sleeps == [5, 5, 10, 10]


def test_denied_expired_and_key_limit_raise_distinct_errors():
    with pytest.raises(LoginDenied):
        run(FakeApi([PollResult(status="access_denied")]))
    with pytest.raises(LoginExpired):
        run(FakeApi([PollResult(status="expired_token")]))
    with pytest.raises(LoginFailed) as exc:
        run(FakeApi([PollResult(status="key_limit")]))
    assert "10 active keys" in str(exc.value)


def test_gives_up_when_the_code_expires_without_approval():
    api = FakeApi([], expires_in=30, interval=5)
    with pytest.raises(LoginExpired):
        run(api)
    assert 5 <= api.poll_calls <= 7


def test_ctrl_c_propagates_cleanly():
    class Interrupt(Clock):
        def sleep(self, seconds):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(FakeApi([APPROVED]), clock=Interrupt())


def test_transient_network_errors_are_retried_a_few_times_then_reported():
    flaky = FakeApi([ApiError("Could not reach DriftWatch."), ApiError("Could not reach DriftWatch."), APPROVED])
    result, _, _, _ = run(flaky)
    assert result == APPROVED
    dead = FakeApi([ApiError("Could not reach DriftWatch.")] * 5)
    with pytest.raises(LoginFailed) as exc:
        run(dead)
    assert "Could not reach DriftWatch" in str(exc.value)


def test_nothing_secret_is_ever_echoed():
    lines: list[str] = []
    run(FakeApi([APPROVED]), lines=lines)
    joined = "\n".join(lines)
    assert DEVICE_CODE not in joined and KEY not in joined

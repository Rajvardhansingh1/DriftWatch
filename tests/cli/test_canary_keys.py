"""Launch gate J4: a planted fake key must never appear in any command's output, error text, agent status or local log.

Fake keys are planted exactly where real ones live (the project key in the keychain, a provider key in its store, a
relay-style secret in the environment), then every command that could echo them runs, with failures forced too.
"""

import json
import logging

import pytest

from driftwatch_llm import cli as cli_module  # noqa: F401  (import cli first: cli_agent registers on it)
from driftwatch_llm import cli_agent
from driftwatch_llm.judge_settings import JudgeSettings, write_settings
from driftwatch_llm.providerkeys import ProviderKeyStore
from tests.cli.test_cli import KEY, PID, Env
from tests.cli.test_cli_agent import STATUS, FakeAgent
from tests.cli.test_providerkeys import FakeKeyring

PROVIDER_KEY = "gsk_" + "CANARYproviderKEY0123456789abcd"
RELAY_SECRET = "RELAY-SECRET-CANARY-0000-1111-2222"
CANARIES = [KEY, PROVIDER_KEY, RELAY_SECRET]


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    e.agent = FakeAgent({"status": {"ok": True, "status": STATUS}})
    e.services.agent_client = lambda: e.agent
    e.keys = ProviderKeyStore(home=e.home, backend=FakeKeyring())
    e.services.provider_keys = e.keys
    e.services.interactive = lambda: False
    e.home.mkdir(parents=True, exist_ok=True)
    e.link(key=KEY)
    e.keys.save("groq", PROVIDER_KEY)
    monkeypatch.setenv("RELAY_SECRET_FOR_TEST", RELAY_SECRET)
    monkeypatch.setattr(cli_agent, "agent_extra_installed", lambda: True)
    return e


def clean(text: str) -> bool:
    return not any(secret in text for secret in CANARIES)


COMMANDS = [
    ("status",),
    ("doctor",),
    ("agent", "status"),
    ("agent", "stop"),
    ("key", "status"),
    ("judge", "status"),
    ("judge", "enable", "--yes"),
    ("judge", "status"),
    ("judge", "enable", "--own", "--provider", "groq", "--yes"),
    ("judge", "status"),
    ("judge", "disable"),
    ("baseline", "status"),
    ("autostart", "disable"),
    ("trust",),
]


def test_no_command_prints_a_planted_key(env):
    for args in COMMANDS:
        result = env.run(*args)
        assert clean(result.output), f"`driftwatch {' '.join(args)}` printed a planted key"
        assert clean(repr(result.exception)), f"`driftwatch {' '.join(args)}` raised with a planted key in the message"


def test_failures_do_not_print_keys_either(env):
    env.agent.absent = True  # no agent
    for args in (("agent", "status"), ("judge", "status"), ("doctor"), ("dashboard",)):
        result = env.run(*(args if isinstance(args, tuple) else (args,)))
        assert clean(result.output)
    for bad in ("short", PROVIDER_KEY + " with spaces", ""):
        result = env.run("key", "set", "groq", input=bad + "\n")
        assert clean(result.output)
    result = env.run("key", "set", "groq", PROVIDER_KEY)  # a key given as an argument is refused and not echoed back
    assert result.exit_code != 0 and clean(result.output)
    for args in (("key", "set", PROVIDER_KEY), ("key", "remove", PROVIDER_KEY), ("key", "set", "groq", PROVIDER_KEY, "extra")):
        result = env.run(*args)  # the key pasted in the wrong place: refused, and never echoed back
        assert result.exit_code != 0 and clean(result.output), args
    env.keys.delete("groq")
    result = env.run("judge", "enable", "--own", "--provider", "groq", "--yes")  # no key stored: the error names the fix, not a key
    assert result.exit_code == 1 and clean(result.output)


def test_the_stored_files_never_hold_a_key_in_a_form_a_status_or_settings_command_would_show(env):
    write_settings(env.home, JudgeSettings(enabled=True, credential="own", provider="groq"))
    settings = (env.home / "judge.json").read_text(encoding="utf-8")
    assert clean(settings)  # settings are not secrets and never contain one
    assert clean(json.dumps(env.keys.status()))
    assert clean(repr(env.secrets)) and clean(repr(env.keys))  # objects that hold keys never reveal them in repr


def test_log_records_from_the_cli_never_carry_a_key(env, caplog):
    caplog.set_level(logging.DEBUG)
    for args in COMMANDS:
        env.run(*args)
    assert clean("\n".join(r.getMessage() for r in caplog.records))


def test_the_environment_secret_is_never_read_by_the_cli_so_it_cannot_leak(env):
    result = env.run("status")
    assert clean(result.output)
    assert "RELAY_SECRET_FOR_TEST" not in result.output

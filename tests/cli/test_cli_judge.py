"""driftwatch key set|status|remove and driftwatch judge enable|disable|status."""

from __future__ import annotations

import pytest

from driftwatch_llm.judge_settings import read_settings
from driftwatch_llm.providerkeys import ProviderKeyStore
from tests.cli.test_cli import KEY, PID, Env
from tests.cli.test_cli_agent import STATUS, FakeAgent
from tests.cli.test_providerkeys import FakeKeyring

OWN = "gsk_" + "Z9y8X7w6V5u4T3s2R1q0P9o8"


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.agent = FakeAgent({"status": {"ok": True, "status": STATUS}})
    e.services.agent_client = lambda: e.agent
    e.kr = FakeKeyring()
    e.keys = ProviderKeyStore(home=e.home, backend=e.kr)
    e.services.provider_keys = e.keys
    e.services.interactive = lambda: True
    e.home.mkdir(parents=True, exist_ok=True)
    return e


# ---- key ----------------------------------------------------------------------------------------------------------
def test_key_set_reads_a_hidden_prompt_stores_it_and_never_prints_it(env):
    r = env.run("key", "set", "groq", input=OWN + "\n")
    assert r.exit_code == 0, r.output
    assert env.keys.load("groq") == (OWN, "keychain")
    assert OWN not in r.output and "keychain" in r.output.lower()


def test_key_set_can_read_from_stdin_for_scripts(env):
    r = env.run("key", "set", "openai", "--stdin", input=OWN + "\n")
    assert r.exit_code == 0 and env.keys.load("openai") == (OWN, "keychain") and OWN not in r.output


def test_a_key_is_never_taken_from_the_command_line(env):
    r = env.run("key", "set", "groq", OWN)  # a stray argument is refused, so keys do not end up in shell history
    assert r.exit_code != 0 and env.keys.load("groq") is None


def test_key_set_refuses_junk_and_unknown_providers_without_echoing(env):
    for bad in ("", "short", "has space in it here"):
        r = env.run("key", "set", "groq", input=bad + "\n")
        assert r.exit_code == 1 and (bad.strip() == "" or bad not in r.output)
    r = env.run("key", "set", "nope", input=OWN + "\n")
    assert r.exit_code != 0 and OWN not in r.output


def test_key_status_and_remove(env):
    env.keys.save("groq", OWN)
    r = env.run("key", "status")
    assert r.exit_code == 0 and "groq" in r.output and "keychain" in r.output and "openai" in r.output and OWN not in r.output
    assert env.run("key", "remove", "groq").exit_code == 0 and env.keys.load("groq") is None
    assert "not set" in env.run("key", "status").output.lower()


# ---- judge --------------------------------------------------------------------------------------------------------
def test_judge_enable_explains_what_leaves_the_machine_and_asks_first(env):
    env.link(key=KEY)
    r = env.run("judge", "enable", input="n\n")
    assert r.exit_code == 1 and read_settings(env.home).enabled is False
    for phrase in ("never", "prompts", "redact", "one in 25", "relay", "driftwatch judge disable"):
        assert phrase in r.output.lower() or phrase in r.output, phrase


def test_judge_enable_free_turns_it_on_after_confirmation(env):
    env.link(key=KEY)
    r = env.run("judge", "enable", input="y\n")
    s = read_settings(env.home)
    assert r.exit_code == 0 and s.enabled and s.credential == "free" and s.sample_every == 25 and s.max_per_day == 40


def test_judge_enable_yes_skips_the_question_and_is_required_when_not_interactive(env):
    env.link(key=KEY)
    assert env.run("judge", "enable", "--yes").exit_code == 0 and read_settings(env.home).enabled
    env.run("judge", "disable")
    env.services.interactive = lambda: False
    r = env.run("judge", "enable")
    assert r.exit_code == 1 and "--yes" in r.output and read_settings(env.home).enabled is False


def test_judge_enable_free_without_a_login_says_how_to_get_a_key(env):
    r = env.run("judge", "enable", "--yes")  # no project here at all
    assert r.exit_code == 1 and "driftwatch init" in r.output and read_settings(env.home).enabled is False


def test_judge_enable_own_needs_a_stored_key_and_sends_straight_to_the_provider(env):
    env.link(key=KEY)
    r = env.run("judge", "enable", "--own", "--provider", "groq", "--yes")
    assert r.exit_code == 1 and "driftwatch key set groq" in r.output and read_settings(env.home).enabled is False
    env.keys.save("groq", OWN)
    r = env.run("judge", "enable", "--own", "--provider", "groq", "--model", "tiny-model", "--every", "10", "--max-per-day", "20", "--yes")
    s = read_settings(env.home)
    assert r.exit_code == 0 and s.credential == "own" and s.provider == "groq" and s.model == "tiny-model" and (s.sample_every, s.max_per_day) == (10, 20)
    assert "directly" in r.output.lower() and OWN not in r.output


def test_judge_enable_refuses_bad_settings(env):
    env.link(key=KEY)
    env.keys.save("openai-compatible", OWN)
    for args in (["--every", "0"], ["--max-per-day", "-1"], ["--own", "--provider", "openai-compatible", "--base-url", "http://example.com/v1"],
                 ["--own", "--provider", "openai-compatible"], ["--own", "--provider", "nope"], ["--own", "--model", "bad model"]):
        r = env.run("judge", "enable", "--yes", *args)
        assert r.exit_code != 0 and read_settings(env.home).enabled is False, args


def test_judge_disable_turns_it_off_and_keeps_other_settings(env):
    env.link(key=KEY)
    env.run("judge", "enable", "--yes", "--every", "7")
    r = env.run("judge", "disable")
    s = read_settings(env.home)
    assert r.exit_code == 0 and s.enabled is False and s.sample_every == 7


def test_judge_status_when_off(env):
    r = env.run("judge", "status")
    assert r.exit_code == 0 and "off" in r.output.lower() and "driftwatch judge enable" in r.output


def test_judge_status_shows_the_live_state_and_the_allowance(env):
    env.link(key=KEY)
    env.run("judge", "enable", "--yes")
    live = dict(STATUS, judge={"enabled": True, "credential": "free", "provider": None, "state": "idle", "queued": 1,
                               "scored_today": 6, "max_per_day": 40, "sample_every": 25, "last_error": None, "allowance": {"remaining": 44}})
    env.agent.replies["status"] = {"ok": True, "status": live}
    r = env.run("judge", "status")
    assert r.exit_code == 0
    for text in ("on", "free allowance", "6 of 40", "44", "one in 25"):
        assert text in r.output, text


def test_judge_status_shows_a_parked_reason_and_the_fix(env):
    env.link(key=KEY)
    env.run("judge", "enable", "--yes")
    live = dict(STATUS, judge={"enabled": True, "credential": "free", "provider": None,
                               "state": "parked: free allowance used. Add your own key: driftwatch key set groq, then driftwatch judge enable --own",
                               "queued": 0, "scored_today": 3, "max_per_day": 40, "sample_every": 25, "last_error": None, "allowance": {"remaining": 0}})
    env.agent.replies["status"] = {"ok": True, "status": live}
    r = env.run("judge", "status")
    assert "free allowance used" in r.output and "driftwatch key set groq" in r.output


def test_judge_status_without_a_running_agent_still_works(env):
    env.link(key=KEY)
    env.run("judge", "enable", "--yes")
    env.agent.absent = True
    r = env.run("judge", "status")
    assert r.exit_code == 0 and "agent is not running" in r.output.lower()


def test_agent_status_and_doctor_mention_the_judge(env, monkeypatch):
    from driftwatch_llm import cli_agent

    monkeypatch.setattr(cli_agent, "agent_extra_installed", lambda: True)
    env.link(key=KEY)
    parked = dict(STATUS, judge={"enabled": True, "credential": "own", "provider": "groq", "state": "parked: the groq key was rejected (run `driftwatch key set groq`)",
                                 "queued": 0, "scored_today": 0, "max_per_day": 40, "sample_every": 25, "last_error": None, "allowance": None})
    env.agent.replies["status"] = {"ok": True, "status": parked}
    assert "judge" in env.run("agent", "status").output.lower()
    d = env.run("doctor")
    assert d.exit_code == 1 and "judge" in d.output and "driftwatch key set groq" in d.output

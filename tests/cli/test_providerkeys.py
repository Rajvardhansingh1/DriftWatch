"""Own-provider keys and judge settings: stored like project keys (keychain first, private file fallback), never shown."""

import json
import os

import pytest

from driftwatch_llm.judge_settings import JudgeSettings, SettingsError, read_settings, write_settings
from driftwatch_llm.providerkeys import PROVIDERS, KeyError_, ProviderKeyStore

GOOD = "gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2"


class FakeKeyring:
    def __init__(self):
        self.data = {}

    def set_password(self, service, user, value):
        self.data[(service, user)] = value

    def get_password(self, service, user):
        return self.data.get((service, user))

    def delete_password(self, service, user):
        self.data.pop((service, user), None)


def test_a_key_goes_to_the_keychain_and_comes_back(tmp_path):
    kr = FakeKeyring()
    store = ProviderKeyStore(home=tmp_path, backend=kr)
    assert store.save("groq", GOOD) == "keychain"
    assert store.load("groq") == (GOOD, "keychain") and store.source("groq") == "keychain"
    index = tmp_path / "provider_keys.json"  # only the list of providers that are in the keychain, never a key
    assert not index.exists() or GOOD not in index.read_text(encoding="utf-8")
    store.delete("groq")
    assert store.load("groq") is None


def test_without_a_keychain_the_key_goes_to_a_private_file(tmp_path):
    class Broken(FakeKeyring):
        def set_password(self, *a):
            raise RuntimeError(f"no keychain here {GOOD}")

    store = ProviderKeyStore(home=tmp_path, backend=Broken())
    assert store.save("openai", GOOD) == "file"
    assert store.load("openai") == (GOOD, "file")
    if os.name == "posix":
        assert (os.stat(tmp_path / "provider_keys.json").st_mode & 0o777) == 0o600
    store.delete("openai")
    assert store.load("openai") is None and not (tmp_path / "provider_keys.json").exists()


def test_errors_never_contain_the_key(tmp_path):
    store = ProviderKeyStore(home=tmp_path, backend=FakeKeyring())
    for bad in ("", "   ", "has space inside", "tab\tinside", "x" * 300, "short", "line\nbreak" + "k" * 20, "naïve" + "k" * 20):
        with pytest.raises(KeyError_) as e:
            store.save("groq", bad)
        assert bad.strip() == "" or bad not in str(e.value)
    with pytest.raises(KeyError_):
        store.save("not-a-provider", GOOD)


def test_status_lists_providers_without_values(tmp_path):
    store = ProviderKeyStore(home=tmp_path, backend=FakeKeyring())
    store.save("groq", GOOD)
    status = store.status()
    assert status["groq"] == "keychain" and status["openai"] == "none"
    assert GOOD not in json.dumps(status) and set(status) == set(PROVIDERS)


def test_the_environment_is_not_used_behind_the_users_back(tmp_path):
    store = ProviderKeyStore(home=tmp_path, backend=FakeKeyring(), env={"GROQ_API_KEY": GOOD, "OPENAI_API_KEY": GOOD})
    assert store.load("groq") is None  # grading is opt-in; a key must be given on purpose with `driftwatch key set`


# ---- judge settings -----------------------------------------------------------------------------------------------
def test_judge_is_off_by_default(tmp_path):
    s = read_settings(tmp_path)
    assert s == JudgeSettings(enabled=False, credential="free", provider="groq", model=None, base_url=None, sample_every=25, max_per_day=40)


def test_settings_round_trip_and_are_validated(tmp_path):
    write_settings(tmp_path, JudgeSettings(enabled=True, credential="own", provider="openai", model="gpt-4o-mini", base_url=None, sample_every=10, max_per_day=20))
    assert read_settings(tmp_path).credential == "own" and read_settings(tmp_path).sample_every == 10
    for bad in (
        dict(credential="other"), dict(provider="nope"), dict(sample_every=0), dict(sample_every=100000), dict(max_per_day=-1),
        dict(max_per_day=100000), dict(model="has space"), dict(model="x" * 100), dict(base_url="http://example.com/v1"),
        dict(base_url="https://user:pw@example.com/v1"), dict(base_url="ftp://example.com"),
    ):
        base = dict(enabled=True, credential="own", provider="openai", model=None, base_url=None, sample_every=25, max_per_day=40)
        base.update(bad)
        with pytest.raises(SettingsError):
            write_settings(tmp_path, JudgeSettings(**base))
    write_settings(tmp_path, JudgeSettings(enabled=True, credential="own", provider="openai", model=None, base_url="http://127.0.0.1:8080/v1", sample_every=25, max_per_day=40))
    assert read_settings(tmp_path).base_url == "http://127.0.0.1:8080/v1"  # a local server is fine over http


def test_a_damaged_or_hostile_settings_file_reads_as_off(tmp_path):
    for content in ("not json", "[]", json.dumps({"enabled": "yes please"}), json.dumps({"enabled": True, "sample_every": "x"}),
                    json.dumps({"enabled": True, "credential": "own", "provider": "../../etc", "sample_every": 5, "max_per_day": 5})):
        (tmp_path / "judge.json").write_text(content, encoding="utf-8")
        assert read_settings(tmp_path).enabled is False

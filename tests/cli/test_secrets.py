import json
import os
import stat
import sys

import pytest

from driftwatch_llm import paths
from driftwatch_llm.fileutil import write_private
from driftwatch_llm.secrets import SecretError, SecretStore

PID = "11111111-1111-4111-8111-111111111111"
PID2 = "22222222-2222-4222-8222-222222222222"
KEY = "dw_0123456789_" + "a" * 64
KEY_ENV = "dw_aaaaaaaaaa_" + "b" * 64
KEY_FILE = "dw_cccccccccc_" + "c" * 64
POSIX = sys.platform != "win32"


class FakeKeyring:
    def __init__(self):
        self.items: dict[tuple[str, str], str] = {}

    def set_password(self, service, user, value):
        self.items[(service, user)] = value

    def get_password(self, service, user):
        return self.items.get((service, user))

    def delete_password(self, service, user):
        self.items.pop((service, user), None)


class BrokenKeyring:
    """A keychain that is not there (Docker, CI, headless Linux) and whose errors echo the secret."""

    def _boom(self, *a, **k):
        raise RuntimeError(f"no keychain, value was {KEY}")

    set_password = get_password = delete_password = _boom


def store(tmp_path, kr=None, env=None):
    return SecretStore(home=tmp_path / "home", backend=kr, env=env or {})


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def test_config_dir_honours_driftwatch_home(monkeypatch, tmp_path):
    monkeypatch.setenv("DRIFTWATCH_HOME", str(tmp_path / "x"))
    assert paths.config_dir() == tmp_path / "x"
    monkeypatch.delenv("DRIFTWATCH_HOME")
    assert paths.config_dir().name.lower().startswith("driftwatch")


def test_write_private_is_atomic_and_owner_only(tmp_path):
    target = tmp_path / "d" / "f.json"
    write_private(target, "one")
    write_private(target, "two")
    assert target.read_text() == "two"
    assert [p.name for p in target.parent.iterdir()] == ["f.json"]  # no temp files left behind
    if POSIX:
        assert mode(target) == 0o600
        assert mode(target.parent) == 0o700


def test_save_prefers_the_keychain_and_writes_no_secret_file(tmp_path):
    kr = FakeKeyring()
    s = store(tmp_path, kr)
    assert s.save(PID, KEY) == "keychain"
    assert kr.items[("driftwatch-llm", PID)] == KEY
    for f in (tmp_path / "home").rglob("*"):
        if f.is_file():
            assert KEY not in f.read_text()
    assert s.load(PID) == (KEY, "keychain")
    assert s.source(PID) == "keychain"


def test_falls_back_to_a_private_file_when_the_keychain_is_unavailable(tmp_path):
    s = store(tmp_path, BrokenKeyring())
    assert s.save(PID, KEY) == "file"
    cred = tmp_path / "home" / "credentials.json"
    assert json.loads(cred.read_text())["keys"][PID] == KEY
    if POSIX:
        assert mode(cred) == 0o600
    assert s.load(PID) == (KEY, "file")
    assert s.source(PID) == "file"


def test_lookup_order_is_keychain_then_env_then_file(tmp_path):
    kr = FakeKeyring()
    s = store(tmp_path, kr, env={"DRIFTWATCH_API_KEY": KEY_ENV})
    SecretStore(home=tmp_path / "home", backend=BrokenKeyring(), env={}).save(PID, KEY_FILE)  # file entry
    assert s.load(PID) == (KEY_ENV, "env")  # env beats file
    kr.set_password("driftwatch-llm", PID, KEY)
    assert s.load(PID) == (KEY, "keychain")  # keychain beats env
    assert s.load(PID2) == (KEY_ENV, "env")  # env key applies to any project
    assert store(tmp_path, FakeKeyring()).load(PID2) is None


def test_env_key_is_read_only_and_must_look_like_a_key(tmp_path):
    s = store(tmp_path, FakeKeyring(), env={"DRIFTWATCH_API_KEY": KEY_ENV})
    s.delete(PID)
    assert s.load(PID) == (KEY_ENV, "env")  # delete never touches the environment
    assert store(tmp_path, FakeKeyring(), env={"DRIFTWATCH_API_KEY": "not-a-key"}).load(PID) is None


def test_delete_removes_keychain_and_file_entries(tmp_path):
    kr = FakeKeyring()
    s = store(tmp_path, kr)
    s.save(PID, KEY)
    SecretStore(home=tmp_path / "home", backend=BrokenKeyring(), env={}).save(PID2, KEY_FILE)
    s.delete(PID)
    s.delete(PID2)
    assert s.load(PID) is None and s.load(PID2) is None
    assert kr.items == {}
    s.delete(PID)  # deleting twice is fine


def test_delete_all_removes_every_project_on_this_machine(tmp_path):
    kr = FakeKeyring()
    s = store(tmp_path, kr)
    s.save(PID, KEY)
    s.save(PID2, KEY_FILE)
    s.delete_all()
    assert kr.items == {}
    assert s.load(PID) is None and s.load(PID2) is None
    cred = tmp_path / "home" / "credentials.json"
    assert not cred.exists() or KEY not in cred.read_text()


def test_saving_to_the_keychain_drops_a_stale_file_entry(tmp_path):
    SecretStore(home=tmp_path / "home", backend=BrokenKeyring(), env={}).save(PID, KEY_FILE)
    s = store(tmp_path, FakeKeyring())
    s.save(PID, KEY)
    cred = tmp_path / "home" / "credentials.json"
    assert KEY_FILE not in cred.read_text()


def test_rejects_malformed_keys_and_project_ids_without_echoing_them(tmp_path):
    s = store(tmp_path, FakeKeyring())
    with pytest.raises(SecretError) as bad_key:
        s.save(PID, "hunter2-not-a-key")
    assert "hunter2" not in str(bad_key.value)
    with pytest.raises(SecretError):
        s.save("not-a-uuid", KEY)
    assert s.load("not-a-uuid") is None


def test_keychain_errors_never_leak_the_key(tmp_path, capsys):
    s = store(tmp_path, BrokenKeyring())
    s.save(PID, KEY)  # falls back silently
    s.load(PID)
    s.delete(PID)
    out = capsys.readouterr()
    assert KEY not in out.out + out.err
    for obj in (s, repr(s), str(s)):
        assert KEY not in repr(obj) and KEY not in str(obj)


def test_corrupt_credentials_file_is_treated_as_empty_and_repaired_on_save(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "credentials.json").write_text("{not json")
    s = store(tmp_path, BrokenKeyring())
    assert s.load(PID) is None
    assert s.save(PID, KEY) == "file"
    assert s.load(PID) == (KEY, "file")

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from driftwatch_llm import cli as cli_module
from driftwatch_llm.api import ApiError, DeviceStart, PollResult
from driftwatch_llm.cli import Services, app
from driftwatch_llm.endpoints import Endpoints
from driftwatch_llm.hooks import remove_autostart_hook
from driftwatch_llm.project import read_config, write_config
from driftwatch_llm.secrets import SecretStore
from driftwatch_llm.trust import TrustStore

PID = "11111111-1111-4111-8111-111111111111"
PID_OTHER = "22222222-2222-4222-8222-222222222222"
KEY = "dw_0123456789_" + "a" * 64
KEY_OLD = "dw_1111111111_" + "1" * 64
DEVICE_CODE = "d" * 64
EP = Endpoints(supabase_url="https://example.supabase.co", publishable_key="sb_publishable_test", web_origin="https://web.example")
runner = CliRunner()


class FakeKeyring:
    def __init__(self):
        self.items: dict[tuple[str, str], str] = {}

    def set_password(self, service, user, value):
        self.items[(service, user)] = value

    def get_password(self, service, user):
        return self.items.get((service, user))

    def delete_password(self, service, user):
        self.items.pop((service, user), None)


class FakeApi:
    def __init__(self, polls=None, revoke_error: ApiError | None = None):
        self.polls = list(polls if polls is not None else [PollResult("approved", KEY, PID, "My app")])
        self.revoke_error = revoke_error
        self.start_calls = 0
        self.revoked: list[str] = []

    def start_device_login(self, name, os_name):
        self.start_calls += 1
        self.started_with = (name, os_name)
        return DeviceStart(device_code=DEVICE_CODE, user_code="BCDFGHJK", expires_in=600, interval=5)

    def poll_device_login(self, code):
        item = self.polls.pop(0) if self.polls else PollResult("authorization_pending")
        if isinstance(item, Exception):
            raise item
        return item

    def revoke_api_key(self, key):
        if self.revoke_error:
            raise self.revoke_error
        self.revoked.append(key)


class Env:
    """Everything a command needs, in a temp dir."""

    def __init__(self, tmp_path: Path, api: FakeApi | None = None):
        self.home = tmp_path / "home"
        self.project = tmp_path / "project"
        self.project.mkdir()
        self.keyring = FakeKeyring()
        self.api = api or FakeApi()
        self.opened: list[str] = []
        self.secrets = SecretStore(home=self.home, backend=self.keyring, env={})
        self.trust = TrustStore(home=self.home)
        self.services = Services(
            endpoints=EP, api=self.api, secrets=self.secrets, trust=self.trust, home=self.home,
            cwd=lambda: self.project, open_url=lambda url: self.opened.append(url) or True,
            sleep=lambda s: None, device_name="test-box", device_os="Linux 6.1",
        )

    def run(self, *args, input=None):
        result = runner.invoke(app, list(args), obj=self.services, input=input)
        assert KEY not in result.output and KEY_OLD not in result.output, "a key was printed"
        assert DEVICE_CODE not in result.output, "the device code was printed"
        return result

    def link(self, project_id=PID, trusted=True, key=None):
        write_config(self.project, project_id)
        if trusted:
            self.trust.trust(self.project, project_id)
        if key:
            self.secrets.save(project_id, key)


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


def test_version(env):
    r = env.run("--version")
    assert r.exit_code == 0 and r.output.startswith("driftwatch-llm ")


# ---- init -----------------------------------------------------------------------------------------

def test_init_links_the_folder_stores_the_key_and_trusts_it(env):
    r = env.run("init")
    assert r.exit_code == 0, r.output
    assert "Nothing runs in the background yet." in r.output
    assert 'Linked to project "My app"' in r.output
    cfg = read_config(env.project)
    assert cfg is not None and cfg.project_id == PID
    assert ".driftwatch/" in (env.project / ".gitignore").read_text(encoding="utf-8")
    assert env.secrets.load(PID) == (KEY, "keychain")
    assert env.trust.is_trusted(env.project, PID)
    assert env.api.started_with == ("test-box", "Linux 6.1")
    assert env.opened == ["https://web.example/auth/device?code=BCDF-GHJK"]


def test_init_no_browser_never_opens_one(env):
    r = env.run("init", "--no-browser")
    assert r.exit_code == 0
    assert env.opened == []
    assert "https://web.example/auth/device?code=BCDF-GHJK" in r.output


def test_init_when_already_linked_and_trusted_does_nothing(env):
    env.link(key=KEY)
    r = env.run("init")
    assert r.exit_code == 0 and "Already linked" in r.output
    assert env.api.start_calls == 0


def test_init_in_a_cloned_untrusted_repo_refuses_and_contacts_nobody(env):
    env.link(project_id=PID_OTHER, trusted=False)
    r = env.run("init")
    assert r.exit_code == 1
    assert "driftwatch trust" in r.output and "--force" in r.output
    assert env.api.start_calls == 0
    assert env.secrets.load(PID_OTHER) is None


def test_init_force_replaces_an_untrusted_config(env):
    env.link(project_id=PID_OTHER, trusted=False)
    r = env.run("init", "--force")
    assert r.exit_code == 0, r.output
    cfg = read_config(env.project)
    assert cfg is not None and cfg.project_id == PID
    assert env.trust.is_trusted(env.project, PID)


@pytest.mark.parametrize(
    "poll,expect",
    [
        (PollResult("access_denied"), "denied"),
        (PollResult("expired_token"), "expired"),
        (PollResult("key_limit"), "10 active keys"),
    ],
)
def test_init_failures_write_nothing(tmp_path, poll, expect):
    e = Env(tmp_path, FakeApi(polls=[poll]))
    r = e.run("init")
    assert r.exit_code == 1 and expect in r.output.lower()
    assert not (e.project / ".driftwatch").exists() and not (e.project / ".gitignore").exists()
    assert e.keyring.items == {}


def test_init_api_error_is_reported_without_a_traceback(tmp_path):
    e = Env(tmp_path, FakeApi(polls=[ApiError("Could not reach DriftWatch.")] * 5))
    r = e.run("init")
    assert r.exit_code == 1 and "Could not reach DriftWatch" in r.output
    assert "Traceback" not in r.output


def test_init_revokes_the_new_key_when_a_local_write_fails(env, monkeypatch):
    def boom(root, project_id):
        raise OSError("disk full")

    monkeypatch.setattr(cli_module, "write_config", boom)
    r = env.run("init")
    assert r.exit_code == 1
    assert env.api.revoked == [KEY]
    assert env.keyring.items == {}


def test_init_ctrl_c_exits_130_without_writing(tmp_path):
    e = Env(tmp_path)

    def interrupt(seconds):
        raise KeyboardInterrupt

    e.services.sleep = interrupt
    r = e.run("init")
    assert r.exit_code == 130
    assert not (e.project / ".driftwatch").exists()


def test_init_again_for_the_same_project_revokes_the_old_key(env):
    env.link(key=KEY_OLD, trusted=False)
    r = env.run("init", "--force")
    assert r.exit_code == 0
    assert env.api.revoked == [KEY_OLD]
    assert env.secrets.load(PID) == (KEY, "keychain")


# ---- login ----------------------------------------------------------------------------------------

def test_login_needs_a_project_folder(env):
    r = env.run("login")
    assert r.exit_code == 1 and "driftwatch init" in r.output
    assert env.api.start_calls == 0


def test_login_refuses_an_untrusted_folder(env):
    env.link(trusted=False)
    r = env.run("login")
    assert r.exit_code == 1 and "driftwatch trust" in r.output
    assert env.api.start_calls == 0


def test_login_replaces_the_key_and_revokes_the_old_one(env):
    env.link(key=KEY_OLD)
    r = env.run("login")
    assert r.exit_code == 0, r.output
    assert env.secrets.load(PID) == (KEY, "keychain")
    assert env.api.revoked == [KEY_OLD]


def test_login_for_a_different_project_changes_nothing_and_revokes_the_new_key(tmp_path):
    e = Env(tmp_path, FakeApi(polls=[PollResult("approved", KEY, PID_OTHER, "Other")]))
    e.link(key=KEY_OLD)
    r = e.run("login")
    assert r.exit_code == 1 and "different project" in r.output
    assert e.secrets.load(PID) == (KEY_OLD, "keychain")
    assert e.api.revoked == [KEY]


# ---- logout ---------------------------------------------------------------------------------------

def test_logout_revokes_on_the_server_then_deletes_locally(env):
    env.link(key=KEY)
    r = env.run("logout")
    assert r.exit_code == 0 and "revoked" in r.output.lower()
    assert env.api.revoked == [KEY]
    assert env.secrets.load(PID) is None


def test_logout_still_deletes_locally_when_the_server_call_fails(tmp_path):
    e = Env(tmp_path, FakeApi(revoke_error=ApiError("Could not reach DriftWatch.")))
    e.link(key=KEY)
    r = e.run("logout")
    assert r.exit_code == 0
    assert "keys page" in r.output
    assert e.secrets.load(PID) is None


def test_logout_with_nothing_stored_says_so(env):
    env.link()
    r = env.run("logout")
    assert r.exit_code == 0 and "No key" in r.output
    assert env.api.revoked == []


def test_logout_never_touches_a_key_that_comes_from_the_environment(env):
    env.secrets = SecretStore(home=env.home, backend=env.keyring, env={"DRIFTWATCH_API_KEY": KEY})
    env.services.secrets = env.secrets
    env.link()
    r = env.run("logout")
    assert r.exit_code == 0 and "DRIFTWATCH_API_KEY" in r.output
    assert env.api.revoked == []


# ---- trust ----------------------------------------------------------------------------------------

def test_trust_asks_then_trusts(env):
    env.link(trusted=False)
    declined = env.run("trust", input="n\n")
    assert declined.exit_code == 1 and not env.trust.is_trusted(env.project, PID)
    r = env.run("trust", input="y\n")
    assert r.exit_code == 0 and env.trust.is_trusted(env.project, PID)
    assert str(env.project) in r.output and PID in r.output


def test_trust_yes_skips_the_prompt_and_warns_about_ignored_settings(env):
    env.link(trusted=False)
    cfg = env.project / ".driftwatch" / "config.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + 'endpoint = "https://evil.example"\n', encoding="utf-8")
    r = env.run("trust", "--yes")
    assert r.exit_code == 0 and env.trust.is_trusted(env.project, PID)
    assert "ignored" in r.output.lower() and "endpoint" in r.output
    assert "evil.example" not in r.output  # names only, never values


def test_trust_without_a_project_fails(env):
    r = env.run("trust", "--yes")
    assert r.exit_code == 1


def test_trust_when_already_trusted(env):
    env.link()
    r = env.run("trust", "--yes")
    assert r.exit_code == 0 and "Already trusted" in r.output


# ---- status ---------------------------------------------------------------------------------------

def test_status_outside_a_project(env):
    r = env.run("status")
    assert r.exit_code == 0 and "No DriftWatch project" in r.output


def test_status_reports_trust_and_key_source_but_never_the_key(env):
    env.link(key=KEY)
    r = env.run("status")
    assert r.exit_code == 0
    assert PID in r.output and "trusted: yes" in r.output and "keychain" in r.output
    assert "https://web.example" in r.output
    env.trust.untrust(env.project)
    assert "trusted: no" in env.run("status").output


# ---- uninstall ------------------------------------------------------------------------------------

def test_uninstall_removes_keys_trust_and_config_files(env, monkeypatch):
    calls = []
    monkeypatch.setattr(cli_module, "remove_autostart_hook", lambda: calls.append(1) or [])
    env.link(key=KEY)
    r = env.run("uninstall", "--yes")
    assert r.exit_code == 0, r.output
    assert env.keyring.items == {}
    assert not (env.home / "trust.json").exists() and not (env.home / "credentials.json").exists()
    assert calls == [1]
    assert "pip uninstall driftwatch-llm" in r.output
    assert "revoke" in r.output.lower()  # keys stay valid on the server until revoked on the website
    assert (env.project / ".driftwatch").exists()  # project folders are left alone


def test_uninstall_project_flag_removes_the_project_folder_too(env, monkeypatch):
    monkeypatch.setattr(cli_module, "remove_autostart_hook", lambda: [])
    env.link(key=KEY)
    r = env.run("uninstall", "--yes", "--project")
    assert r.exit_code == 0
    assert not (env.project / ".driftwatch").exists()


def test_uninstall_asks_first_and_stops_on_no(env):
    env.link(key=KEY)
    r = env.run("uninstall", input="n\n")
    assert r.exit_code == 1
    assert env.secrets.load(PID) == (KEY, "keychain")


def test_remove_autostart_hook_deletes_only_its_own_file(tmp_path):
    (tmp_path / "driftwatch_llm_autostart.pth").write_text("import x", encoding="utf-8")
    (tmp_path / "other.pth").write_text("keep", encoding="utf-8")
    removed = remove_autostart_hook([tmp_path])
    assert removed == [tmp_path / "driftwatch_llm_autostart.pth"]
    assert (tmp_path / "other.pth").exists()
    assert remove_autostart_hook([tmp_path]) == []
    assert remove_autostart_hook([tmp_path / "missing"]) == []


# ---- --dev ----------------------------------------------------------------------------------------

def test_dev_endpoints_apply_only_with_the_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTWATCH_HOME", str(tmp_path / "h"))
    monkeypatch.chdir(tmp_path)
    dev_env = {"DRIFTWATCH_DEV_WEB_ORIGIN": "http://127.0.0.1:3100"}
    plain = runner.invoke(app, ["status"], env=dev_env)
    assert "https://drift-watch-rouge.vercel.app" in plain.output
    dev = runner.invoke(app, ["--dev", "status"], env=dev_env)
    assert "http://127.0.0.1:3100" in dev.output


def test_a_bad_dev_override_is_refused_with_a_clear_message(tmp_path, monkeypatch):
    monkeypatch.setenv("DRIFTWATCH_HOME", str(tmp_path / "h"))
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["--dev", "status"], env={"DRIFTWATCH_DEV_SUPABASE_URL": "http://evil.example"})
    assert r.exit_code == 2
    assert "DRIFTWATCH_DEV_SUPABASE_URL" in r.output and "evil.example" not in r.output

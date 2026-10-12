import pytest

from driftwatch_llm.project import (
    ConfigError,
    ensure_gitignore,
    find_project_root,
    read_config,
    write_config,
)

PID = "11111111-1111-4111-8111-111111111111"


def test_write_config_holds_only_a_project_id_and_a_mode(tmp_path):
    path = write_config(tmp_path, PID)
    assert path == tmp_path / ".driftwatch" / "config.toml"
    body = path.read_text(encoding="utf-8")
    data_lines = [ln for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
    assert data_lines == [f'project_id = "{PID}"', 'mode = "cloud"']
    assert "http" not in body.lower() and "dw_" not in body


def test_read_config_round_trip_and_missing_file(tmp_path):
    assert read_config(tmp_path) is None
    write_config(tmp_path, PID)
    cfg = read_config(tmp_path)
    assert cfg is not None
    assert (cfg.project_id, cfg.mode, cfg.ignored_keys) == (PID, "cloud", ())


def test_hostile_config_cannot_set_endpoints_or_keys(tmp_path):
    d = tmp_path / ".driftwatch"
    d.mkdir()
    (d / "config.toml").write_text(
        f'project_id = "{PID}"\nmode = "cloud"\n'
        'endpoint = "https://evil.example"\nsupabase_url = "https://evil.example"\n'
        'api_key = "dw_0123456789_' + "a" * 64 + '"\nweb_origin = "https://evil.example"\n',
        encoding="utf-8",
    )
    cfg = read_config(tmp_path)
    assert cfg is not None
    assert set(cfg.ignored_keys) == {"endpoint", "supabase_url", "api_key", "web_origin"}
    assert not hasattr(cfg, "endpoint") and not hasattr(cfg, "api_key")
    assert "evil" not in repr(cfg) and "dw_0123456789" not in repr(cfg)


def test_ignored_key_names_are_sanitised_before_they_can_reach_a_terminal(tmp_path):
    d = tmp_path / ".driftwatch"
    d.mkdir()
    (d / "config.toml").write_text(
        f'project_id = "{PID}"\nmode = "cloud"\n"\\u001b[31mred" = 1\n', encoding="utf-8"
    )
    cfg = read_config(tmp_path)
    assert cfg is not None
    assert all("\x1b" not in k for k in cfg.ignored_keys)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('project_id = "not-a-uuid"\nmode = "cloud"\n', id="bad-uuid"),
        pytest.param(f'project_id = "{PID}"\nmode = "local"\n', id="wrong-mode"),
        pytest.param(f'project_id = "{PID}"\n', id="no-mode"),
        pytest.param("mode = 'cloud'\n", id="no-project"),
        pytest.param("this is not toml [", id="not-toml"),
        pytest.param('project_id = 5\nmode = "cloud"\n', id="non-string-id"),
        pytest.param("x = 1\n" * 5000, id="too-large"),
    ],
)
def test_bad_configs_raise_without_echoing_the_file(tmp_path, body):
    d = tmp_path / ".driftwatch"
    d.mkdir()
    (d / "config.toml").write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        read_config(tmp_path)
    assert "this is not toml" not in str(exc.value)
    assert "not-a-uuid" not in str(exc.value)


def test_write_config_rejects_a_bad_project_id(tmp_path):
    with pytest.raises(ConfigError):
        write_config(tmp_path, 'x"\nendpoint = "https://evil')
    assert not (tmp_path / ".driftwatch").exists()


def test_ensure_gitignore_creates_appends_and_is_idempotent(tmp_path):
    assert ensure_gitignore(tmp_path) is True
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".driftwatch/\n"
    assert ensure_gitignore(tmp_path) is False
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".driftwatch/\n"


def test_ensure_gitignore_keeps_existing_content_and_fixes_a_missing_trailing_newline(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules/\n.env", encoding="utf-8")
    assert ensure_gitignore(tmp_path) is True
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n.env\n.driftwatch/\n"


@pytest.mark.parametrize("existing", [".driftwatch", ".driftwatch/", "/.driftwatch", "/.driftwatch/", "  .driftwatch/  "])
def test_ensure_gitignore_recognises_existing_entries(tmp_path, existing):
    (tmp_path / ".gitignore").write_text(f"a\n{existing}\nb\n", encoding="utf-8")
    assert ensure_gitignore(tmp_path) is False


def test_ensure_gitignore_keeps_crlf_files_consistent(tmp_path):
    (tmp_path / ".gitignore").write_bytes(b"a\r\nb\r\n")
    ensure_gitignore(tmp_path)
    assert (tmp_path / ".gitignore").read_bytes() == b"a\r\nb\r\n.driftwatch/\r\n"


def test_find_project_root_walks_up_from_a_subfolder(tmp_path):
    write_config(tmp_path, PID)
    sub = tmp_path / "src" / "pkg"
    sub.mkdir(parents=True)
    assert find_project_root(sub) == tmp_path
    assert find_project_root(tmp_path.parent / "elsewhere-that-does-not-exist") is None

import sys

from driftwatch_llm.trust import TrustStore

PID = "11111111-1111-4111-8111-111111111111"
PID2 = "22222222-2222-4222-8222-222222222222"


def make(tmp_path):
    return TrustStore(home=tmp_path / "home")


def test_unknown_folder_is_not_trusted(tmp_path):
    assert make(tmp_path).is_trusted(tmp_path / "repo", PID) is False


def test_trust_applies_to_that_folder_and_project_only(tmp_path):
    t = make(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    t.trust(repo, PID)
    assert t.is_trusted(repo, PID) is True
    assert t.is_trusted(repo, PID2) is False  # a repo that swaps in another project id is untrusted again
    assert t.is_trusted(other, PID) is False  # the same project id in a different folder is untrusted


def test_trust_survives_a_new_store_instance_and_path_spelling(tmp_path):
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    make(tmp_path).trust(repo, PID)
    assert make(tmp_path).is_trusted(repo / "sub" / "..", PID) is True


def test_untrust_and_clear(tmp_path):
    t = make(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    t.trust(a, PID)
    t.trust(b, PID2)
    t.untrust(a)
    assert t.is_trusted(a, PID) is False and t.is_trusted(b, PID2) is True
    t.clear()
    assert t.is_trusted(b, PID2) is False
    t.untrust(a)  # no error


def test_store_holds_hashes_not_paths_and_is_private(tmp_path):
    import os
    import stat

    t = make(tmp_path)
    repo = tmp_path / "secret-client-name"
    repo.mkdir()
    t.trust(repo, PID)
    f = tmp_path / "home" / "trust.json"
    assert "secret-client-name" not in f.read_text(encoding="utf-8")
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600


def test_corrupt_store_is_treated_as_empty_and_repaired(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "trust.json").write_text("][", encoding="utf-8")
    t = make(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    assert t.is_trusted(repo, PID) is False
    t.trust(repo, PID)
    assert t.is_trusted(repo, PID) is True


def test_garbage_project_ids_are_never_trusted(tmp_path):
    t = make(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    t.trust(repo, PID)
    assert t.is_trusted(repo, "") is False
    assert t.is_trusted(repo, None) is False  # type: ignore[arg-type]

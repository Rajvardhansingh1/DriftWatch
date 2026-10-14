import importlib.util
import re
import uuid
from pathlib import Path

from monitor.cloud import seal

spec = importlib.util.spec_from_file_location("make_runner_keys", Path(__file__).resolve().parent.parent / "scripts" / "make_runner_keys.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_the_generated_pair_works_and_the_values_are_fresh_each_time():
    a, b = mod.make(1), mod.make(1)
    assert a["RUNNER_PRIVATE_KEY"] != b["RUNNER_PRIVATE_KEY"] and a["RUNNER_SECRET"] != b["RUNNER_SECRET"]
    box = seal.seal("a-provider-key-12345", str(uuid.uuid4()), 1, a["CONNECT_PUBLIC_KEY"])
    assert box["key_id"] == 1


def test_the_sql_line_stores_only_a_hash_of_the_secret_in_the_right_table():
    v = mod.make(2)
    assert v["CONNECT_KEY_ID"] == "2"
    assert re.fullmatch(r"update private\.runner_policy set runner_secret_hash = extensions\.digest\('[\w-]{40,}', 'sha256'\);", v["SQL"])
    assert v["RUNNER_SECRET"] in v["SQL"]


def test_it_writes_nothing_to_disk(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["make_runner_keys.py"])
    assert mod.main() == 0
    assert list(tmp_path.iterdir()) == [] and "RUNNER_PRIVATE_KEY" in capsys.readouterr().out

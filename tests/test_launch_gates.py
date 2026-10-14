"""The hardening matrix cannot rot: every item has evidence, every reference exists, and the generated page is current."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MATRIX = json.loads((ROOT / "deploy" / "hardening_matrix.json").read_text(encoding="utf-8"))
EXPECTED_IDS = (
    [f"A{i}" for i in range(1, 11)] + [f"B{i}" for i in range(1, 10)] + [f"C{i}" for i in range(1, 15)]
    + [f"D{i}" for i in range(1, 9)] + [f"E{i}" for i in range(1, 8)] + [f"F{i}" for i in range(1, 5)]
)
spec = importlib.util.spec_from_file_location("make_launch_gates", ROOT / "scripts" / "make_launch_gates.py")
gates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gates)


def test_every_hardening_id_is_present_exactly_once():
    ids = [i["id"] for i in MATRIX["items"]]
    assert ids == EXPECTED_IDS


@pytest.mark.parametrize("item", MATRIX["items"], ids=lambda i: i["id"])
def test_each_item_has_the_evidence_its_status_promises(item):
    assert item["status"] in ("tested", "design", "owner") and item["title"]
    if item["status"] in ("tested", "design"):
        assert item["refs"], "a tested or by-design item must cite where the proof is"
    if item["status"] == "owner":
        assert item.get("owner_action"), "an owner item must say what the owner does"
    if item["status"] == "design":
        assert item.get("note") or item["refs"]


def _function_exists(path: Path, name: str) -> bool:
    return re.search(rf"^\s*(?:async\s+)?def {re.escape(name)}\b", path.read_text(encoding="utf-8"), re.M) is not None


def _all_refs():
    return [(i["id"], r) for i in MATRIX["items"] for r in i.get("refs", [])]


@pytest.mark.parametrize("item_id,ref", _all_refs(), ids=lambda v: str(v)[:70])
def test_every_reference_points_at_something_that_exists(item_id, ref):
    if ref.startswith("sql:") or ref.startswith("ts:"):
        path = ROOT / ref.split(":", 1)[1]
        assert path.is_file(), f"{item_id}: {ref} is missing"
    elif "::" in ref:
        file, name = ref.split("::", 1)
        path = ROOT / file
        assert path.is_file(), f"{item_id}: {file} is missing"
        assert _function_exists(path, name), f"{item_id}: {file} has no test named {name}"
    else:
        assert (ROOT / ref).exists(), f"{item_id}: {ref} is missing"


def test_ts_and_sql_references_use_the_right_folders():
    for _, ref in _all_refs():
        if ref.startswith("sql:"):
            assert ref.startswith("sql:supabase/tests/") and ref.endswith(".sql")
        if ref.startswith("ts:"):
            assert ref.startswith("ts:frontend/tests/") and ref.endswith(".test.ts")


def test_the_generated_page_is_current():
    assert gates.render(MATRIX) == (ROOT / "deploy" / "LAUNCH_GATES.md").read_text(encoding="utf-8").replace("\r\n", "\n")

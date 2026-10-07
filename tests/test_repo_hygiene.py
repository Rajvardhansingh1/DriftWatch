import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))

# Functions intentionally callable without signing in. Adding a name here is a
# security decision: it needs a reviewer and a line in the PR description.
ANON_EXECUTABLE_ALLOWLIST = {"public.ingest_event", "public.ping"}


def _git_tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return set(out.stdout.splitlines())


def test_mcp_json_is_not_tracked():
    assert ".mcp.json" not in _git_tracked()


def test_dotenv_is_not_tracked():
    assert not any(p == ".env" or p.endswith("/.env") for p in _git_tracked())


def test_only_allowlisted_functions_are_executable_by_anon():
    granted = set()
    for path in MIGRATIONS:
        sql = path.read_text(encoding="utf-8")
        granted.update(re.findall(r"grant execute on function ([\w.]+)\([^)]*\) to [^;]*\banon\b", sql))
    assert granted <= ANON_EXECUTABLE_ALLOWLIST, granted - ANON_EXECUTABLE_ALLOWLIST


def test_new_definer_functions_pin_empty_search_path():
    for path in MIGRATIONS:
        if int(path.name.split("_", 1)[0]) < 5:
            continue  # 0001-0004 predate this rule; they pin `public` (reviewed in 0002)
        sql = path.read_text(encoding="utf-8")
        for fn in re.findall(r"create function [\w.]+\(.*?\n\$\$;", sql, flags=re.S):
            if "security definer" in fn:
                assert "set search_path = ''" in fn, f"{path.name}: {fn[:70]}"

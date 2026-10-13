import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))

# Functions intentionally callable without signing in. Adding a name here is a
# security decision: it needs a reviewer and a line in the PR description.
ANON_EXECUTABLE_ALLOWLIST = {
    "public.ingest_event",
    "public.ping",
    # Plan 3 (0009): the CLI has no session. Reviewed: each needs a 256-bit secret
    # or only creates a capped pending row.
    "public.start_device_login",
    "public.poll_device_login",
    "public.revoke_api_key_by_secret",
    # Plan 6 (0010): the relay (Render) holds no service key, so it meters with the project key like the agent does.
    # Each call authenticates the key first and fails identically for malformed, unknown and revoked keys.
    "public.reserve_quota",
    "public.settle_quota",
}


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


def test_no_tracked_file_is_covered_by_gitignore():
    # Anything tracked but matching an ignore rule is a build artifact or local file that slipped in.
    out = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert out.stdout.split() == [], out.stdout


def test_gitignore_keeps_secrets_and_local_files_out():
    patterns = {
        line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines() if line.strip()
    }
    for must in (
        ".env", ".env.*", "!.env.example", "*.pem", "*.key", "credentials.json", ".mcp.json", ".claude/",
        ".driftwatch/", "node_modules/", ".next/", "*.tsbuildinfo", ".vercel/", "*.sqlite3", "Docs/",
    ):
        assert must in patterns, f".gitignore lost {must}"


def test_gitleaks_allowlists_are_narrow():
    text = (ROOT / ".gitleaks.toml").read_text(encoding="utf-8")
    blocks = text.split("[[allowlists]]")[1:]
    assert blocks, "expected at least one allowlist"
    for block in blocks:
        # Each entry must need BOTH a path and a value to match, and the path must be anchored.
        assert 'condition = "AND"' in block, block[:80]
        assert "paths = ['''^" in block and "regexes = [" in block, block[:80]


def test_ci_secret_scan_loads_the_allowlist_with_a_pinned_gitleaks():
    import yaml

    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    step = next(s for s in ci["jobs"]["secrets"]["steps"] if str(s.get("uses", "")).startswith("gitleaks/gitleaks-action"))
    env = step["env"]
    # The action only auto-detects `gitleaks.toml`, so the dotted file must be named explicitly,
    # and the plural [[allowlists]] syntax needs gitleaks 8.25+, so the version must be pinned.
    assert env["GITLEAKS_CONFIG"] == ".gitleaks.toml"
    assert (ROOT / env["GITLEAKS_CONFIG"]).is_file()
    major, minor, *_ = (int(x) for x in env["GITLEAKS_VERSION"].split("."))
    assert (major, minor) >= (8, 25), env["GITLEAKS_VERSION"]

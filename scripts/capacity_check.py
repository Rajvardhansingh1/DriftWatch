"""Daily capacity check for the free Supabase plan (run by .github/workflows/supabase-keepalive.yml).

Reads `ops_report` (aggregates only) and exits 1 when the database is above 70% of the free-plan limit, so the owner gets an email
well before the project is read-only. Settings come from the environment: SUPABASE_URL, SUPABASE_ANON_KEY, RUNNER_SECRET.
Prints sizes and counts, never an identifier or a secret.
"""
import json
import os
import sys
import urllib.error
import urllib.request

FREE_PLAN_DATABASE_BYTES = 500 * 1024 * 1024  # the free plan's database size limit
WARN_AT = 0.70


def assess(report: dict, limit: int = FREE_PLAN_DATABASE_BYTES, warn_at: float = WARN_AT) -> tuple[bool, str]:
    used = int(report["database_bytes"])
    share = used / limit
    line = (
        f"database {used / 1024 / 1024:.0f} MB of {limit / 1024 / 1024:.0f} MB ({share:.0%}); "
        f"{report.get('signal_records', '?')} score rows, {report.get('users', '?')} users, {report.get('projects', '?')} projects"
    )
    if share >= warn_at:
        return False, f"PROBLEM {line}. Over {warn_at:.0%}: see deploy/CAPACITY.md (shorten retention, or upgrade the plan)."
    return True, f"ok {line}"


def fetch(env: dict) -> dict:
    request = urllib.request.Request(
        env["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/ops_report",
        data=json.dumps({"p_secret": env["RUNNER_SECRET"]}).encode(),
        headers={"apikey": env["SUPABASE_ANON_KEY"], "content-type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main(env: dict | None = None, fetcher=fetch) -> int:
    env = dict(os.environ) if env is None else env
    if not all(env.get(k) for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "RUNNER_SECRET")):
        print("capacity check skipped: the cloud-runner secrets are not set (set them to turn this alarm on)")
        return 0
    try:
        ok, line = assess(fetcher(env))
    except (urllib.error.URLError, ValueError, KeyError, TypeError):
        print("PROBLEM the capacity report could not be read (is migration 0014 applied and the runner secret current?)")
        return 1
    print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

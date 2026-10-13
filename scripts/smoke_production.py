"""Production smoke test: everything that can be checked WITHOUT an account, a key or a provider quota.

    python scripts/smoke_production.py [--site URL] [--monitor URL] [--pypi]

Read-only except one harmless row: the CLI sign-in start (`start_device_login`) creates a pending sign-in that expires
by itself. It sends no key and no event, and it never spends provider quota. What it cannot do (needs a person): sign
in through the website (CAPTCHA), create a project in the browser, approve a CLI sign-in, delete a throwaway account.
Those are listed at the end. Exit code 1 if any check FAILs.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from driftwatch_llm.endpoints import PINNED  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append(("PASS" if ok else "FAIL", name, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f" -- {detail}" if detail else ""), flush=True)
    return ok


def info(name: str, detail: str) -> None:
    results.append(("INFO", name, detail))
    print(f"INFO  {name} -- {detail}", flush=True)


# -- the website -----------------------------------------------------------------------------------------
def site_checks(site: str) -> None:
    print(f"\n== website {site}")
    with httpx.Client(base_url=site, timeout=30, follow_redirects=False) as c:
        for path, needle in [("/", "DriftWatch"), ("/demo", "DriftWatch"), ("/auth/sign-in", "Sign in"), ("/privacy", "rivacy"), ("/terms", "erms")]:
            r = c.get(path)
            check(f"GET {path} is 200 and looks right", r.status_code == 200 and needle in r.text, f"{r.status_code}")
        r = c.get("/")
        for header in ("strict-transport-security", "x-content-type-options", "referrer-policy", "permissions-policy", "x-frame-options", "content-security-policy"):
            check(f"/ sends {header}", header in r.headers)
        csp = r.headers.get("content-security-policy", "")
        check("the CSP forbids framing and plugins", "frame-ancestors 'none'" in csp and "object-src 'none'" in csp)
        for path in ("/dashboard", "/dashboard/settings", "/admin"):
            r = c.get(path)
            loc = r.headers.get("location", "")
            check(f"{path} without a session redirects to sign-in", r.status_code in (302, 303, 307, 308) and "/auth/sign-in" in loc, f"{r.status_code} -> {loc}")
        for path in ("/robots.txt", "/sitemap.xml", "/llms.txt", "/.well-known/security.txt"):
            check(f"GET {path}", c.get(path).status_code == 200)
        llms = c.get("/llms.txt").text
        check("/llms.txt never names the unrelated `driftwatch` package", re.search(r"pip install driftwatch(?![-\w\[])", llms) is None)
        check("an unknown page is a 404, not a crash", c.get("/definitely-not-a-page").status_code == 404)
        home = c.get("/").text
        info("CLI copy on the landing page", "present" if "driftwatch init" in home else "hidden (NEXT_PUBLIC_FEATURES has no `cli` yet)")


# -- the monitor (Render) -----------------------------------------------------------------------------
def monitor_checks(monitor: str) -> None:
    print(f"\n== monitor {monitor}")
    t0 = time.time()
    try:
        r = httpx.get(f"{monitor}/api/health", timeout=120)  # a free instance sleeps: the first call can take a minute
        check("GET /api/health answers 200", r.status_code == 200, f"{r.status_code} in {time.time() - t0:.0f}s")
        stranger = httpx.get(f"{monitor}/api/health", headers={"Origin": "https://evil.example"}, timeout=60)
        allowed = stranger.headers.get("access-control-allow-origin")
        check("the monitor does not allow a stranger's origin", allowed not in ("*", "https://evil.example"), str(allowed))
    except httpx.HTTPError as exc:
        check("the monitor answers", False, type(exc).__name__)


# -- the database API (Supabase) ------------------------------------------------------------------------
def supabase_checks() -> None:
    base = PINNED.supabase_url
    print(f"\n== supabase {base}")
    headers = {"apikey": PINNED.publishable_key, "content-type": "application/json"}
    with httpx.Client(base_url=base, headers=headers, timeout=30) as c:
        for table in ("projects", "project_api_keys", "signal_records", "profiles", "device_logins"):
            r = c.get(f"/rest/v1/{table}?select=*&limit=1")
            rows = r.json() if r.status_code == 200 else None
            check(f"anonymous read of `{table}` returns no rows", r.status_code in (200, 401, 403, 404) and not rows, f"{r.status_code}")
        for fn in ("create_project", "create_project_api_key", "export_my_data", "delete_my_account", "approve_device_login"):
            r = c.post(f"/rest/v1/rpc/{fn}", json={})
            check(f"anonymous call of `{fn}` is refused", r.status_code >= 400 and r.status_code != 500, f"{r.status_code}")
        bad_key = "dw_" + "0" * 10 + "_" + "0" * 64
        r = c.post("/rest/v1/rpc/ingest_event", json={"p_api_key": bad_key, "p_event": {}})
        check("ingest_event with an unknown key is PT401", r.status_code == 401 and r.json().get("code") == "PT401", f"{r.status_code} {r.json().get('code') if r.headers.get('content-type', '').startswith('application/json') else ''}")
        r = c.post("/rest/v1/rpc/ingest_event", json={"p_api_key": "not-a-key", "p_event": {}})
        check("ingest_event with a malformed key is also refused the same way", r.status_code == 401, f"{r.status_code}")
        r = c.post("/rest/v1/rpc/start_device_login", json={"p_device_name": "smoke-test", "p_device_os": "Smoke 1.0"})
        ok = r.status_code == 200 and isinstance(r.json(), (dict, list))
        check("the CLI sign-in can be started", ok, f"{r.status_code}")
        if ok:
            body = r.json()
            body = body[0] if isinstance(body, list) else body
            code = body.get("device_code")
            check("the sign-in start returns codes for the browser and the CLI", bool(code) and bool(body.get("user_code")), ", ".join(sorted(body)))
            r2 = c.post("/rest/v1/rpc/poll_device_login", json={"p_device_code": code})
            status = (r2.json()[0] if isinstance(r2.json(), list) else r2.json()).get("status") if r2.status_code == 200 else None
            check("polling it says authorization_pending (nobody approved it)", status == "authorization_pending", f"{r2.status_code} {status}")
            check("no key comes back for a pending sign-in", "api_key" not in r2.text or "null" in r2.text)


# -- the published package ---------------------------------------------------------------------------------
def pypi_checks() -> None:
    print("\n== PyPI")
    r = httpx.get("https://pypi.org/pypi/driftwatch-llm/json", timeout=30)
    check("driftwatch-llm is published", r.status_code == 200)
    if r.status_code != 200:
        return
    data = r.json()
    latest = data["info"]["version"]
    info("latest version", latest)
    check("it declares the `agent` extra", "agent" in (data["info"].get("provides_extra") or []) or any("extra == 'agent'" in d or 'extra == "agent"' in d for d in (data["info"].get("requires_dist") or [])))
    check("it is MIT licensed", data["info"].get("license_expression") == "MIT" or "MIT" in (data["info"].get("license") or ""))
    with tempfile.TemporaryDirectory() as tmp:
        venv = Path(tmp) / "v"
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
        exe = venv / ("Scripts" if sys.platform == "win32" else "bin") / ("python.exe" if sys.platform == "win32" else "python")
        done = subprocess.run([str(exe), "-m", "pip", "install", "-q", "--no-cache-dir", f"driftwatch-llm=={latest}"], capture_output=True, text=True, timeout=600)
        check("a clean `pip install driftwatch-llm` works", done.returncode == 0, done.stderr.strip().splitlines()[-1] if done.returncode else "")
        if done.returncode == 0:
            v = subprocess.run([str(exe), "-I", "-m", "driftwatch_llm", "--version"], capture_output=True, text=True, timeout=60, cwd=tmp)
            check("`driftwatch --version` matches", latest in v.stdout, v.stdout.strip())
            files = subprocess.run([str(exe), "-c", "import sysconfig,os;print(any(f.endswith('.pth') and 'driftwatch' in f for f in os.listdir(sysconfig.get_paths()['purelib'])))"], capture_output=True, text=True)
            check("installing adds no .pth file (autostart is opt-in)", files.stdout.strip() == "False")
            h = subprocess.run([str(exe), "-I", "-m", "driftwatch_llm", "doctor"], capture_output=True, text=True, timeout=60, cwd=tmp)
            info("`driftwatch doctor` in a bare folder", "available (exit code %d)" % h.returncode if "ok " in h.stdout else "not in this release yet")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", default=PINNED.web_origin)
    ap.add_argument("--monitor", default="https://driftwatch-monitor.onrender.com")
    ap.add_argument("--pypi", action="store_true", help="also install the published package in a temp venv")
    args = ap.parse_args()
    site_checks(args.site.rstrip("/"))
    monitor_checks(args.monitor.rstrip("/"))
    supabase_checks()
    if args.pypi:
        pypi_checks()
    failed = [r for r in results if r[0] == "FAIL"]
    print(f"\n{sum(1 for r in results if r[0] == 'PASS')} passed, {len(failed)} failed")
    print(
        "\nStill needs a person (cannot be automated: CAPTCHA / a real account):\n"
        "  1. sign in on the website, create a project and a key, send one event with the curl example,\n"
        "     see it on the chart, revoke the key and see 401, export your data (no key_hash), delete a throwaway account\n"
        "  2. `driftwatch init` and approve the link in the browser, then `driftwatch status` and `driftwatch logout`"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

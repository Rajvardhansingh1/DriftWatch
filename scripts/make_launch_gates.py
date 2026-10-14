"""Writes deploy/LAUNCH_GATES.md from deploy/hardening_matrix.json.

    python scripts/make_launch_gates.py          # rewrite the file
    python scripts/make_launch_gates.py --check  # exit 1 if the committed file is out of date

The JSON is the source of truth; tests/test_launch_gates.py checks every reference in it exists and that this file is current.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "deploy" / "hardening_matrix.json"
OUT = ROOT / "deploy" / "LAUNCH_GATES.md"
STATUS_TEXT = {"tested": "tested", "design": "by design", "owner": "owner action"}


def label(ref: str) -> str:
    return ref.split(":", 1)[1] if ref.startswith(("sql:", "ts:")) else ref


def render(doc: dict) -> str:
    items = doc["items"]
    counts = {k: sum(1 for i in items if i["status"] == k) for k in STATUS_TEXT}
    lines = [
        "# Launch gates: hardening evidence",
        "",
        "Generated from `deploy/hardening_matrix.json` by `scripts/make_launch_gates.py`; do not edit by hand.",
        "`tests/test_launch_gates.py` checks that every referenced test or file exists.",
        "",
        f"{len(items)} items: {counts['tested']} tested, {counts['design']} by design, {counts['owner']} need an owner action.",
        "",
        "| ID | Risk | Status | Evidence | Owner action |",
        "|---|---|---|---|---|",
    ]
    for i in items:
        evidence = "<br>".join(f"`{label(r)}`" for r in i.get("refs", []))
        if i.get("note"):
            evidence += ("<br>" if evidence else "") + i["note"]
        lines.append(f"| {i['id']} | {i['title']} | {STATUS_TEXT[i['status']]} | {evidence} | {i.get('owner_action', '')} |")
    lines += [
        "",
        "## Residual risks (cannot be designed away)",
        "",
        "- A compromised user machine can read its own keychain and local data. We limit what the cloud can leak.",
        "- Cloud-connect keys are decryptable by the runner by definition. They are sealed so that only the runner can open them; see `deploy/RUNBOOK_CLOUD_CONNECT.md`. Users who cannot accept this use the local agent with their own key.",
        "- A malicious dependency in a user's own environment can already read their process. The `.pth` hook adds no new privilege and is visible and removable.",
        "- Provider outages and SDK changes will break capture for some versions; the design makes this fail safe, not never.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    text = render(json.loads(SRC.read_text(encoding="utf-8")))
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print("deploy/LAUNCH_GATES.md is out of date: run python scripts/make_launch_gates.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

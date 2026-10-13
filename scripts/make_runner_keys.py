"""Generates the cloud runner's secrets. Run it ON YOUR OWN MACHINE, in a private terminal, and copy each value to the place
named next to it. Nothing is written to disk. Do not paste any of it into chat, an issue or a commit.

    python scripts/make_runner_keys.py [--key-id 1]

Where each value goes:
  RUNNER_PRIVATE_KEY   GitHub: Settings -> Environments -> cloud-runner -> secret.  (With --key-id 2 or more, add it to the
                       JSON map secret RUNNER_PRIVATE_KEYS instead, next to the older keys: see deploy/RUNBOOK_CLOUD_CONNECT.md)
  CONNECT_PUBLIC_KEY   Vercel: environment variable, server only (NOT NEXT_PUBLIC_). It can only seal, never open.
  CONNECT_KEY_ID       Vercel: the number below.
  RUNNER_SECRET        GitHub: the same environment, as a secret.
  the SQL line         Supabase SQL editor: stores only the sha256 of the runner secret.
"""
import argparse
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitor.cloud import seal  # noqa: E402


def make(key_id: int = 1) -> dict[str, str]:
    private, public = seal.generate_keypair()
    runner_secret = secrets.token_urlsafe(32)
    return {
        "RUNNER_PRIVATE_KEY": private,
        "CONNECT_PUBLIC_KEY": public,
        "CONNECT_KEY_ID": str(key_id),
        "RUNNER_SECRET": runner_secret,
        "SQL": f"update private.runner_policy set runner_secret_hash = extensions.digest('{runner_secret}', 'sha256');",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key-id", type=int, default=1, help="1 for the first key pair; 2, 3, ... when rotating")
    args = ap.parse_args()
    if not 1 <= args.key_id <= 1000:
        print("--key-id must be between 1 and 1000")
        return 2
    for name, value in make(args.key_id).items():
        print(f"{name}\n  {value}\n")
    print("Copy each value now. They are not saved anywhere; run this again for new ones.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

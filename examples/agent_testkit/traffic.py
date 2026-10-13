"""A small app that makes LLM calls, so the DriftWatch agent has something to watch.

Run it WITH monitoring on, one of two ways:

    python -m driftwatch_llm run -- python agent_testkit/traffic.py --n 50 --family a
    (or after `driftwatch autostart enable`)  python agent_testkit/traffic.py --n 50 --family a

By default it uses a FAKE OpenAI SDK (no network, no key, no cost) whose answers come from corpus.py. Family "a"
is billing-support text, family "b" is cooking tips: switching from a to b is a big, deliberate drift.
With --sdk groq or --sdk openai it calls the real provider instead (needs the SDK, a key and --model; costs a little).
"""

import argparse
import os
import random
import sys
import time
import uuid
from pathlib import Path

KIT = Path(__file__).resolve().parent
sys.path.insert(0, str(KIT))

import corpus  # noqa: E402


def hook_active() -> bool:
    return any(type(f).__name__ == "_Finder" for f in sys.meta_path)


def capture_client():
    try:
        from driftwatch_llm.capture import wrappers

        return getattr(wrappers._sink, "__self__", None), wrappers
    except Exception:  # noqa: BLE001
        return None, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=50, help="how many LLM calls to make")
    ap.add_argument("--family", choices=["a", "b", "mix"], default="a", help="a = billing support, b = cooking tips")
    ap.add_argument("--delay", type=float, default=0.05, help="seconds between calls")
    ap.add_argument("--sdk", choices=["fake", "groq", "openai"], default="fake")
    ap.add_argument("--model", help="model name, required with --sdk groq or openai")
    ap.add_argument("--marker", default="", help="text planted in every fake response, to prove it is never stored")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    rng = random.Random(args.seed if args.seed is not None else int(time.time() * 1000) % 10_000_000)
    marker = args.marker or f"TESTKIT-MARKER-{uuid.uuid4().hex[:10]}"
    print(f"capture hook: {'ACTIVE' if hook_active() else 'NOT ACTIVE (run via `driftwatch run -- ...` or enable autostart)'}")
    print(f"marker planted in fake responses: {marker}")

    if args.sdk == "fake":
        sys.path.insert(0, str(KIT / "fake_sdk"))  # before the hook sees the import, so it gets patched
        import openai.resources.chat.completions as c

        state = {"family": "a"}
        c.Completions.responder = lambda messages: corpus.make_response(state["family"], rng, marker)
        client = c.Completions()

        def call(family: str):
            state["family"] = family
            return client.create(model="fake-gpt", messages=[{"role": "user", "content": corpus.make_prompt(family, rng)}])

    else:
        if not args.model:
            print("--model is required with a real provider")
            return 2
        if args.sdk == "groq":
            from groq import Groq

            real = Groq()
        else:
            from openai import OpenAI

            real = OpenAI()
        print(f"REAL provider: about {args.n} calls to {args.sdk}/{args.model}. Ctrl+C to stop.")

        def call(family: str):
            return real.chat.completions.create(
                model=args.model, max_tokens=80,
                messages=[{"role": "user", "content": corpus.make_prompt(family, rng)}],
            )

    for i in range(args.n):
        family = args.family if args.family != "mix" else rng.choice(["a", "b"])
        call(family)
        if args.delay:
            time.sleep(args.delay)
    print(f"made {args.n} calls (family {args.family})")

    client_obj, wrappers = capture_client()
    if client_obj is None:
        print("nothing was captured: monitoring is off for this run")
        return 0
    deadline = time.time() + 90  # a cold agent (first model load) can take a while
    while time.time() < deadline:
        stats = client_obj.stats()
        if stats["sent"] + stats["dropped"] + stats["send_failures"] >= stats["captured"] and stats["captured"] > 0:
            break
        time.sleep(0.25)
    stats = client_obj.stats()
    print(
        f"capture: captured {stats['captured']}, delivered to the agent {stats['sent']}, "
        f"dropped {stats['dropped']}, send failures {stats['send_failures']}, errors {stats['errors']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

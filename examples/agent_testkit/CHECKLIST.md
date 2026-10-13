# Real-machine checklist

The automated kit proves the logic. These are the things only a real machine can show. Do them before a release,
on each system you support, and tick what you did. Anything odd: `driftwatch doctor` and `driftwatch agent status`.

## Install and first run
- [ ] Fresh venv: `pip install "driftwatch-llm[agent]"`, then `driftwatch init` in a new folder
- [ ] `driftwatch agent warmup` shows the download, then "The model is ready"
- [ ] `driftwatch doctor` says "No problems found"
- [ ] `python agent_testkit/run_all.py --quick` ends with "All good"

## Everyday life
- [ ] Run an app, close the terminal, run it again later: baseline kept, no duplicate agent (`driftwatch agent status`)
- [ ] Sleep the laptop for 10 minutes while an app runs, wake it: the app is fine, the agent recovers, sync resumes
- [ ] Turn Wi-Fi off for 5 minutes, make LLM calls, turn it on: the events arrive (watch the website)
- [ ] Switch networks / connect a VPN while running: nothing crashes
- [ ] Log out and in as another user on the same machine: the second user's agent is separate and cannot read the first's files

## Hostile environments
- [ ] Antivirus / endpoint protection on: nothing is quarantined, the agent starts
- [ ] A corporate proxy or no internet at first run: `driftwatch agent warmup` explains the model download instead of hanging
- [ ] Python from the Microsoft Store (Windows) / system Python (macOS, Linux): `driftwatch autostart enable` works or says why not
- [ ] A read-only environment: `autostart enable` fails with a clear message and `driftwatch run --` still works

## Safety
- [ ] Open the app's folder in a different trusted-looking project: monitoring does NOT start until `driftwatch trust`
- [ ] `driftwatch autostart disable`, run an app: nothing is captured
- [ ] `driftwatch agent rotate-key`: the old key stops working, the agent keeps syncing with the new one
- [ ] `driftwatch uninstall`: no `.pth` file, no agent process, no leftover files you did not expect

## Long run (once per release)
- [ ] `python -m driftwatch_llm run -- python agent_testkit/soak.py --minutes 120` passes (with `pip install psutil`)

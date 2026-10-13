# DriftWatch agent test kit

Scripts to test the DriftWatch agent on your own machine, end to end, with no API key and no cost.

## Quick start

From a folder you have linked with `driftwatch init` (a scratch project is fine):

```
pip install --upgrade "driftwatch-llm[agent]"
driftwatch --version
python path/to/agent_testkit/run_all.py --quick       # about 1-2 minutes after the model is downloaded
```

In this repository the kit lives in `examples/agent_testkit/`. With `DRIFTWATCH_AGENT_EMBEDDER=hash` it needs no
model download at all (a tiny test embedder; the drift margin is relaxed automatically). CI runs it that way:
`tests/test_agent_testkit.py`.

The first run downloads the embedding model (about 90 MB), so it can take a few minutes. On later runs it is quick.
The last line should be `All good. The agent is monitoring correctly on this machine.`

## What the sequence does

| Step | What it checks |
|---|---|
| 1 | wipes the **local** agent state (history, baselines). Your key and project link stay. |
| 2 | starts the agent and waits for the model to load |
| 3-4 | baseline traffic, then stable traffic (fake billing-support answers) through a fake OpenAI SDK |
| 5 | the agent captured everything, the baseline froze, drift values were produced, nothing was lost |
| 6 | **privacy**: a unique marker planted in every response must appear in NO local file |
| 7 | **security**: wrong key refused, an impostor listener gets nothing, garbage and oversized messages are survived |
| 8-9 | shifted traffic (cooking tips): the drift score must clearly rise above the stable floor |
| 10 | 20 simultaneous starts give one agent; kill the agent hard, a new one starts and the baseline and history survive |

`INFO` lines are not failures. "not logged in: events wait in the local outbox" is expected until you run
`driftwatch login`; after that, the queued events are sent to your project and you can watch the chart on the website.

## More scenarios

| Script | What it proves |
|---|---|
| `offline.py` | cloud down -> events queue; a rejected key parks the project; restart -> every event arrives exactly once (uses `fake_ingest_server.py`) |
| `burst.py --n 2000` | a flood of responses is all answered, nothing vanishes silently, the agent stays responsive |
| `soak.py --minutes 30` | steady load for a long time: flat memory, one agent process, no drops (run via `driftwatch run --`) |
| `compare_windows.py` | prints the drift values over time as a table with bars |
| `fake_ingest_server.py` | a stand-in for the cloud on your machine, with modes down / error / slow / unauth / throttle |
| `CHECKLIST.md` | what to try by hand on a real machine before a release (sleep/wake, VPN, antivirus, a second user...) |

## Files

- `run_all.py` runs everything and prints one summary. Options: `--quick`, `--keep-state`, `--baseline N`, `--sdk groq --model X`.
- `traffic.py` is the app under test. `python agent_testkit\traffic.py --n 50 --family a` after
  `driftwatch run --` (or with autostart on). Family `a` is billing text, `b` is cooking tips.
- `check_agent.py` has the individual checks (`status`, `wait-embedder`, `reset`, `basics`, `privacy`, `security`, `drift`, `resilience`).
- `corpus.py` is the fake answers. `fake_sdk/` is a stand-in OpenAI SDK with the real module path, so the hook patches it.

## Useful single commands

```powershell
python -m driftwatch_llm agent status                       # the agent's own view
python agent_testkit\check_agent.py status                  # the raw JSON
python agent_testkit\check_agent.py security                # just the attack tests
python -m driftwatch_llm run -- python agent_testkit\traffic.py --n 200 --family a
python agent_testkit\check_agent.py reset --yes             # start clean
```

## With a real provider (costs a little)

```powershell
pip install groq              # or: pip install openai
$env:GROQ_API_KEY = "..."
python agent_testkit\run_all.py --sdk groq --model <a-cheap-model-name>    # about 150 calls
```

## If something fails

- `embedder: failed` -> `pip install "driftwatch-llm[agent]"` is missing, or the model could not be downloaded.
- `embedder: loading` for a long time -> the first download is slow. After it is cached, `$env:HF_HUB_OFFLINE = 1` skips the network check.
- `capture hook: NOT ACTIVE` -> run traffic through `python -m driftwatch_llm run -- ...`, and make sure this folder is linked and trusted (`driftwatch status` shows `trusted: yes`).
- `captured 0` -> the same as above, or the app finished before the agent was ready.
- Anything else: `python -m driftwatch_llm agent status` and paste the output.

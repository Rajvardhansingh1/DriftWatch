# driftwatch-llm

Command-line tool and local agent for [DriftWatch](https://drift-watch-rouge.vercel.app), a drift monitor for LLM apps.

```
pip install "driftwatch-llm[agent]"
driftwatch init              # sign in through your browser and link this folder to a project
driftwatch autostart enable  # optional: watch your app's LLM calls whenever it runs from this folder
driftwatch agent warmup      # first run: wait while the model (about 90 MB) downloads
driftwatch dashboard         # your charts, on this machine
driftwatch judge enable      # optional: grade a small, redacted sample of responses (shows what is sent first)
driftwatch doctor            # if nothing shows up: checks the usual causes and says how to fix each
driftwatch agent status      # what the background agent is doing
```

Without the `[agent]` extra the package is just the CLI (`init`, `login`, `logout`, `trust`, `status`,
`uninstall`). Monitoring needs the extra, because the embeddings are computed on your machine.

## What it measures

One signal on real traffic by default: **embedding drift**, how far recent LLM responses have moved from a baseline made of
your app's first 200 responses (`driftwatch baseline freeze` can end the baseline early, with at least 30).
It reports the drift score and a combined score computed from the signals present. It does not raise alerts
yet: the alert threshold was tuned for a five-signal mix, so it is not applied to a single signal. It tells you
that drift happened, not why.

Supported SDKs: OpenAI, Anthropic, Groq and Google GenAI (the Python packages). Streaming responses are captured
as you consume them, and recorded only if the stream ends normally (a stream you stop early, or one that errors,
records nothing). Not covered: Anthropic's `client.messages.stream()` helper (use `create(stream=True)`).

## The judge (optional, off by default)

`driftwatch judge enable` turns on a second signal: about one response in 25 (at most 40 a day) is graded 0-10 by a
language model, and the scores become a trend line next to embedding drift. Because that means a response sample
leaves your machine, it is off until you say yes, and `enable` shows exactly what is sent first:

- the sample is **redacted** on your machine (emails, API keys, tokens, card and phone numbers become `[email]`,
  `[secret]`, `[number]`) and cut to 1500 characters; **prompts are never read or sent**
- with the **free allowance** (50 graded samples) it goes through the DriftWatch relay, which keeps nothing; with
  `driftwatch judge enable --own` it goes straight to your provider with **your key** (`driftwatch key set groq`),
  which is stored in your OS keychain and never printed
- when the allowance is used up the judge stops and says so; it never switches to another key by itself
- the grader sees one response on its own, so it measures how a response reads, not whether it answers the question
  asked: a trend signal, not proof. It does not raise alerts.

`driftwatch judge status` shows what it is doing; `driftwatch judge disable` turns it off.

## The local dashboard

`driftwatch dashboard` opens a page served by the agent on `127.0.0.1` (this machine only). The link carries a
one-time token in the part after `#`, which a browser never sends anywhere; the page trades it for an
`HttpOnly`, `SameSite=Strict` cookie. Requests with another `Host` or `Origin` are refused and there are no CORS
headers, so no other website can read it. It shows the same charts as the website, plus whether your numbers have
synced (synced, N pending, paused or offline). Only numbers exist locally, so it shows no response text.

## What leaves your machine

- Only numbers: a drift score and a few counts, sent to your own DriftWatch project with your project key.
- The text of responses goes only to a small agent running on your machine. It is held in memory, turned into
  an embedding and dropped; it is never written to disk and never sent anywhere.
- Prompts are never read.

## Keys

`driftwatch agent rotate-key` gets a fresh project key through your browser and revokes the old one; the running
agent picks it up on its next sync. `driftwatch logout` revokes this machine's key and removes it.

## What it stores and changes

- A project key in your OS keychain (or a private file if there is none), a trust record, and
  `.driftwatch/config.toml` in your project folder (a project id, nothing else).
- With `driftwatch autostart enable`, one file in your Python environment, `driftwatch_llm_autostart.pth`. It acts
  only in folders you trusted. `driftwatch autostart disable` removes it. `driftwatch run -- python app.py`
  monitors a single run without installing anything.
- Installing the package changes nothing; only the commands above do.

MIT licensed.

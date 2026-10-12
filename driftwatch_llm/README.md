# driftwatch-llm

Command-line tool for [DriftWatch](https://drift-watch-rouge.vercel.app), a drift monitor for LLM apps.

**Status: early.** This release only links a project folder to your DriftWatch account:

```
pip install driftwatch-llm
driftwatch init      # sign in through your browser and link this folder to a project
driftwatch status
driftwatch logout
```

It does not monitor anything yet. The background agent and the local dashboard come in later releases.

What it stores on your machine: one project API key in your OS keychain (or a private file if no
keychain exists), a trust record, and `.driftwatch/config.toml` in your project folder, which holds a
project id and nothing else. Installing the package changes nothing; only the commands above do.

MIT licensed.

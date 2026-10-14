# DriftWatch

DriftWatch is a quality-drift monitor for production LLM applications. It watches how an app's responses change over time and tells you
when they have quietly moved away from normal: a model swap, prompt rot, a shift in what users ask. It is purely observational. It
never blocks or modifies traffic.

- **Website and console:** https://drift-watch-rouge.vercel.app (live demo, sign-in, projects, charts)
- **CLI and local agent:** `pip install "driftwatch-llm[agent]"` ([PyPI](https://pypi.org/project/driftwatch-llm/), details in [driftwatch_llm/README.md](driftwatch_llm/README.md))

**Limitation:** DriftWatch can tell you something changed, not always *why*. A model swap, prompt rot and input shift can look alike.

## Two ways to use it

| | What you do | Where the measuring happens |
|---|---|---|
| **Your own app** | `pip install "driftwatch-llm[agent]"`, `driftwatch init`, run your app. The agent captures responses from the OpenAI, Anthropic, Groq and Google GenAI SDKs | On your machine. Only numbers (scores and counts) go to your DriftWatch project; response text never leaves, prompts are never read |
| **The live demo** | Open the site and trigger a controlled degradation (weaker model, prompt-injection creep, off-topic traffic) | On the demo server, with a simulated or free-tier model |

An optional **cloud connect** feature (built, shipped switched off) lets DriftWatch probe a model with a stored, sealed provider key on a schedule.
See [deploy/RUNBOOK_CLOUD_CONNECT.md](deploy/RUNBOOK_CLOUD_CONNECT.md).

## What it detects

Up to five signals feed a combined drift score:

| Signal | What it measures |
| --- | --- |
| Embedding-space drift | How far recent outputs have moved from a baseline (an app's first responses) |
| Self-consistency | Answer disagreement across repeated samples of the same query |
| Canary probes | Accuracy on a fixed, known-answer prompt set run on a schedule |
| LLM-as-judge trend | Rubric-scored sampled outputs, tracked as a trend (opt-in; samples are redacted first) |
| Hallucination score | A heuristic risk proxy (token overlap with grounding context, or self-consistency); not verified factual entailment |

On real traffic through the local agent, embedding drift is the default signal and the judge is opt-in; the others run in the demo and in cloud connect.

## Repository layout

```
driftwatch_llm/  the published CLI + local agent (capture wrappers, IPC, dashboard, sync)
monitor/         FastAPI service: signal analyzers, scoring, demo pipeline, free-allowance relay, cloud runner
demo_bot/        controllable Q&A bot with scenario hooks for the demo degradations
frontend/        Next.js site and console (Vercel)
supabase/        migrations, rollbacks, SQL tests, runbooks (Postgres, auth, RLS)
tests/           backend, CLI, agent and workflow tests
examples/        agent test kit: end-to-end scenarios against a fake SDK
scripts/         evaluation, smoke tests, local SQL test runners
schemas/         event schema and API contract
deploy/          deploy guide and cloud-connect runbook; render.yaml (root) is the Render blueprint
.github/         CI, release (PyPI trusted publishing), scheduled keep-alive and runner workflows
```

## Running locally

```bash
conda env create -f environment.yml
conda activate driftwatch
cp .env.example .env        # optional: GROQ_API_KEY / GOOGLE_API_KEY (without keys a simulated client is used)

uvicorn monitor.main:app --reload --port 8000

cd frontend
npm install
npm run dev
```

The website needs Supabase settings for sign-in and the console; see `.env.example` and [deploy/README.md](deploy/README.md).

## Testing

```bash
pytest                                  # backend, CLI, agent, workflows
cd frontend && npm test && npx tsc --noEmit
python scripts/run_sql_tests_local.py   # SQL tests on a throwaway local Postgres (needs pgserver)
```

CI runs all of this on every pull request, plus the agent suite on Linux and Windows (macOS on `main`), a dependency audit, and a secret scan.

## Security

Row-level security, SECURITY DEFINER functions with fixed search paths, deny-by-default privileges, write-only project API keys, and
sealed provider keys (X25519 + HKDF + AES-256-GCM). Report vulnerabilities as described in [SECURITY.md](SECURITY.md).

## Deployment

| Component | Host |
| --- | --- |
| Website and console (Next.js) | Vercel |
| Database, auth, realtime | Supabase |
| Demo and free-allowance relay (FastAPI) | Render, free web service |
| CLI | PyPI package `driftwatch-llm` |
| Scheduled jobs (keep-alive, cloud runner) | GitHub Actions |

## Evaluation

```bash
python scripts/run_detection_eval.py
```

Runs labeled synthetic-degradation scenarios against the detector (evaluation only: the live detector never sees labels) and writes
detection latency, false-positive rate and per-signal contribution to `eval_reports/` (not committed).

## License

MIT. See [LICENSE](LICENSE).

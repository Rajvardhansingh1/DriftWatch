# DriftWatch

DriftWatch is an unsupervised quality-drift monitor for production LLM applications. It watches a live system's behavior across many requests over time and flags silent degradation — it does not make a per-request enforcement decision, and it never blocks or modifies traffic.

## What it detects

Five signals feed a combined drift score:

| Signal | What it measures |
| --- | --- |
| Embedding-space drift | How far the current output distribution has moved from a stable baseline |
| Self-consistency | Answer disagreement across repeated samples of the same query at temperature > 0 |
| Canary probes | Accuracy on a fixed, known-answer prompt set run on a schedule |
| LLM-as-judge trend | Rubric-scored sampled outputs, tracked as a trend rather than a single score |
| Hallucination score | Claim-level entailment / self-consistency fallback, shared with Project 1 (SentinelAI) |

The five signals are combined into one weighted score; crossing a configurable threshold fires an alert naming the triggering signal(s).

**Limitation:** DriftWatch can tell you something changed, but not always *why* — model swap, prompt rot, and input distribution shift can produce similar-looking drift.

## Live demo

A visitor triggers a controlled, reversible degradation and watches the dashboard react within seconds:

- **Simulate model downgrade** — swaps the bot to a deliberately weaker model
- **Simulate prompt injection creep** — gradually corrupts the system prompt
- **Simulate distribution shift** — feeds a stream of off-topic queries

A free-text box lets visitors add their own queries into the rolling window directly. A quota badge and cold-start overlay keep the demo's free-tier limits honest.

## Architecture

```
demo_bot/  → controllable Q&A bot (scenario hooks for the 3 degradations)
monitor/   → FastAPI service: signal analyzers, combined scoring, SQLite rolling store
frontend/  → Next.js dashboard: live charts, alert banner, scenario controls
scripts/   → synthetic-degradation evaluation (detection latency, false-positive rate)
deploy/    → Render (monitor) + Hugging Face Spaces (dashboard) configs
```

The monitor is purely observational: it sits alongside the demo bot's traffic, never in front of it.

## Running locally

```bash
conda env create -f environment.yml
conda activate driftwatch
cp .env.example .env   # fill in GROQ_API_KEY / GOOGLE_API_KEY

uvicorn monitor.main:app --reload --port 8000

cd frontend
npm install
npm run dev
```

Without an API key configured, the monitor falls back to a simulated LLM client so the pipeline still runs end to end.

## Testing

```bash
pytest
```

Test suite covers the signal analyzers, combined scoring, ingest pipeline, rate limiting/quota, canary scheduling, and the demo bot's scenario contracts.

## Evaluation

```bash
python scripts/run_detection_eval.py
```

Runs labeled synthetic-degradation scenarios against the detector (evaluation-only — the live detector never sees labels) and reports detection latency, false-positive rate, per-signal contribution, and canary accuracy baseline into `eval_reports/`.

## Deployment

| Component | Host |
| --- | --- |
| Monitor (FastAPI) | Render, free web service |
| Dashboard (Next.js) | Hugging Face Spaces |
| Rolling store | SQLite, ephemeral on Render's free tier |
| LLM calls | Groq (primary), Gemini (backup) |

Runs at $0 at demo traffic levels with per-session rate limiting and canary result caching.

## Relationship to Project 1 (SentinelAI)

Project 1 protects a single request synchronously, in the moment. DriftWatch watches system health statistically, across thousands of requests, over time. They share one component: the Hallucination Score module.

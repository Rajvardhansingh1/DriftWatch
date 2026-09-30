# DriftWatch

DriftWatch is an unsupervised quality-drift monitor for production LLM applications. It watches system behavior across many requests over time rather than making a per-request enforcement decision.

## What it detects
Five signals are combined:
1. Embedding-space drift
2. Self-consistency disagreement
3. Canary accuracy trend
4. LLM-as-judge trend
5. Shared hallucination score

The result is a combined drift score and an alert when the configured threshold is crossed.

## What makes the demo useful
A visitor can trigger controlled degradation scenarios:
- simulate model downgrade
- simulate prompt injection creep
- simulate distribution shift

The dashboard should make the resulting drift visible within seconds.

## Important limitation
DriftWatch can detect that behavior changed, but a drift signal does not always prove why it changed. Model changes, prompt degradation, and input distribution shifts can overlap.

## Development
Read these files in order when working on the project:
1. `CLAUDE.md`
2. `state.md`
3. relevant phase in `spec.md`
4. `testing.md`
5. `decision.md` when making architectural choices

Update project memory after meaningful work.

## Project phases
0. Foundation  
1. Demo bot  
2. Rolling store + core signals  
3. Canary + judge tracking  
4. Shared hallucination scoring  
5. Combined scoring + alerting  
6. Dashboard + scenario controls  
7. Synthetic degradation evaluation  
8. Deployment + hardening

## Evaluation
The project must report measured detection latency, false-positive rate, per-signal contribution, and canary accuracy baseline. These are evaluation results, not claims made before measurement.

## Status
Documentation foundation initialized. Implementation has not yet started.

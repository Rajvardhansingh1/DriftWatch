# monitor/ — agent instructions

Owns: FastAPI monitor service, the five signal analyzers, combined scoring, rolling-window persistence.

## Contracts
- Every signal module in `signals/` exposes a pure-ish function/class that takes recent traffic + baseline and returns a numeric signal value plus metadata — no side effects beyond writing to `db/`.
- Signals never block or modify the request/response they observe (see root `CLAUDE.md` cross-phase invariant).
- `scoring/combined_score.py` reads persisted signal rows, never recomputes a signal itself.
- `db/models.py` is the only place table schemas are defined; `db/session.py` is the only place engine/session setup happens.
- Config comes only from `config.py` (`Settings`, sourced from `.env`) — no ad-hoc `os.environ` reads elsewhere.

## Do not
- Implement a phase's signal before its phase starts (see root `state.md`).
- Reimplement the hallucination scorer — Phase 4 vendors/imports Project 1's module.

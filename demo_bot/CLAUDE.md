# demo_bot/ — agent instructions

Owns: the controllable Q&A bot and its three scenario hooks.

## Contracts
- `bot.py` exposes a baseline answer function returning response + metadata (model id, prompt version, latency) the monitor needs.
- `scenarios.py` exposes exactly three reversible functions: `simulate_model_downgrade`, `simulate_injection_creep`, `simulate_distribution_shift`. Each has a matching reset.
- Scenario state lives only inside `demo_bot/` — never mutates monitor state directly.
- This bot never touches real production traffic; it exists to be safely degraded.

## Do not
- Add a fourth scenario without an explicit spec/decision update.
- Make scenario effects irreversible.

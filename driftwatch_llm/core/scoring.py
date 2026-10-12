"""Combined Drift Score Engine: weighted combination of all five signals
into one score, with a configurable alert threshold and a list of which
signal(s) triggered it.

Important limitation (D-007, cross-phase invariant): a high score or a
named triggering signal means drift was detected, not why it happened —
model swap, prompt rot, and input distribution shift can all produce a
similar-looking signal pattern. Nothing here infers root cause."""
from __future__ import annotations

from dataclasses import dataclass, field

# Tuned in decision D-021 for the five-signal mix. The server overrides it from settings.
DEFAULT_ALERT_THRESHOLD = 0.17

# Signals where a HIGHER raw value means BETTER quality, not more drift —
# these are inverted before combining so every contribution is "higher = worse".
_HIGHER_IS_BETTER = {"canary_accuracy", "judge_trend"}

ALL_SIGNALS = (
    "embedding_drift",
    "self_consistency",
    "canary_accuracy",
    "judge_trend",
    "hallucination_score",
)


_DEFAULT_WEIGHTS = {
    # Not equal weights: embedding_drift's raw MMD magnitude runs
    # structurally smaller than the other four signals (see D-020), so
    # equal weighting under-represents genuine embedding-space drift
    # (spec's named primary signal for distribution-shift) in the
    # combined score. Weights still sum to 1.0.
    "embedding_drift": 0.45,
    "self_consistency": 0.15,
    "canary_accuracy": 0.15,
    "judge_trend": 0.125,
    "hallucination_score": 0.125,
}


@dataclass
class ScoringConfig:
    weights: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    alert_threshold: float = DEFAULT_ALERT_THRESHOLD
    signal_alert_threshold: float = 0.5


@dataclass
class CombinedScoreResult:
    score: float
    contributions: dict[str, float]
    triggering_signals: list[str]
    alert: bool


def normalize_signal(name: str, value: float) -> float:
    """Map a raw signal value to a 0..1 drift contribution, higher = worse."""
    v = value
    if name in _HIGHER_IS_BETTER:
        v = 1.0 - v
    return max(0.0, min(1.0, v))


def combine_signals(
    latest_values: dict[str, float], config: ScoringConfig | None = None
) -> CombinedScoreResult:
    config = config or ScoringConfig()
    contributions = {name: normalize_signal(name, value) for name, value in latest_values.items()}
    total_weight = sum(config.weights.get(name, 0.0) for name in contributions)
    if total_weight == 0:
        score = 0.0
    else:
        score = (
            sum(contributions[name] * config.weights.get(name, 0.0) for name in contributions)
            / total_weight
        )
    triggering = sorted(
        name for name, c in contributions.items() if c >= config.signal_alert_threshold
    )
    return CombinedScoreResult(
        score=score,
        contributions=contributions,
        triggering_signals=triggering,
        alert=score >= config.alert_threshold,
    )

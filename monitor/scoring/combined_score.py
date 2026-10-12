"""Combined Drift Score Engine: weighted combination of all five signals
into one score, with a configurable alert threshold and a list of which
signal(s) triggered it.

Important limitation (D-007, cross-phase invariant): a high score or a
named triggering signal means drift was detected, not why it happened —
model swap, prompt rot, and input distribution shift can all produce a
similar-looking signal pattern. Nothing here infers root cause."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from driftwatch_llm.core.scoring import (  # noqa: F401
    ALL_SIGNALS,
    CombinedScoreResult,
    _DEFAULT_WEIGHTS,
    _HIGHER_IS_BETTER,
    normalize_signal,
)
from driftwatch_llm.core.scoring import ScoringConfig as _CoreScoringConfig
from driftwatch_llm.core.scoring import combine_signals as _core_combine_signals
from monitor.config import settings
from monitor.db.writer import read_signal_window, write_signal


@dataclass
class ScoringConfig(_CoreScoringConfig):
    # The server's threshold comes from settings (env DRIFTWATCH_ALERT_THRESHOLD).
    alert_threshold: float = field(default_factory=lambda: settings.alert_threshold)


def combine_signals(
    latest_values: dict[str, float], config: ScoringConfig | None = None
) -> CombinedScoreResult:
    return _core_combine_signals(latest_values, config=config or ScoringConfig())


def compute_combined_score(
    session: Session, config: ScoringConfig | None = None
) -> CombinedScoreResult:
    """Reads the most recent value of each of the five signals from the
    rolling store, combines them, and persists the combined score as its
    own signal row so the dashboard can chart it over time."""
    latest_values: dict[str, float] = {}
    for name in ALL_SIGNALS:
        rows = read_signal_window(session, name, limit=1)
        if rows:
            latest_values[name] = rows[0].value

    result = combine_signals(latest_values, config=config)
    write_signal(
        session,
        "combined_score",
        result.score,
        meta={"triggering_signals": result.triggering_signals, "alert": result.alert},
    )
    return result

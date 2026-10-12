"""Vendored hallucination scorer (algorithm copy of Project 1, decision D-005). The code now lives in
driftwatch_llm.core.hallucination, unchanged; this module re-exports it."""
from driftwatch_llm.core.hallucination import (  # noqa: F401
    SUPPORT_THRESHOLD,
    HallucinationResult,
    _jaccard,
    _overlap_ratio,
    _split_claims,
    _tokens,
    score_grounded,
    score_ungrounded,
)

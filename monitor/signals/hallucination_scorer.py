"""Vendored, verbatim algorithm copy of Project 1's hallucination scorer
(P1-SentinelaiFraudCopilotProject/proxy/eval/hallucination_scorer.py) —
not reimplemented, per spec D-005 / decision D-005. Only the result type
is decoupled from P1's `proxy.schemas.HallucinationResult` so DriftWatch
doesn't need P1's full dependency tree (presidio, chromadb, ...) installed
just to share this one module. Scoring logic is byte-for-byte identical."""
from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import combinations
from typing import Literal

SUPPORT_THRESHOLD = 0.5


@dataclass
class HallucinationResult:
    score: float = 0.0
    mode: Literal["grounded", "ungrounded"] = "ungrounded"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _split_claims(text: str) -> list[str]:
    return [c.strip() for c in re.split(r"[.!?]+", text) if c.strip()]


def _overlap_ratio(claim_tokens: set[str], context_tokens: set[str]) -> float:
    if not claim_tokens:
        return 0.0
    return len(claim_tokens & context_tokens) / len(claim_tokens)


def score_grounded(response_text: str, grounding_context: str) -> HallucinationResult:
    """Claim-level entailment against grounding context (token-overlap heuristic)."""
    claims = _split_claims(response_text)
    if not claims:
        return HallucinationResult(score=0.0, mode="grounded")
    context_tokens = _tokens(grounding_context)
    unsupported = sum(
        1 for c in claims if _overlap_ratio(_tokens(c), context_tokens) < SUPPORT_THRESHOLD
    )
    return HallucinationResult(score=unsupported / len(claims), mode="grounded")


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def score_ungrounded(samples: list[str]) -> HallucinationResult:
    """Self-consistency fallback when no grounding context is available."""
    if len(samples) < 2:
        return HallucinationResult(score=0.0, mode="ungrounded")
    token_sets = [_tokens(s) for s in samples]
    pairs = list(combinations(token_sets, 2))
    mean_similarity = sum(_jaccard(a, b) for a, b in pairs) / len(pairs)
    return HallucinationResult(score=1 - mean_similarity, mode="ungrounded")

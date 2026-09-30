"""Deterministic-but-varying offline LLM client used when no
GROQ_API_KEY/GOOGLE_API_KEY is configured, so the live demo (dashboard,
scenarios, evaluation) works end-to-end without external API access.

At temperature 0 the same input always produces the same output
(matching real greedy decoding). At temperature > 0, repeated calls with
identical arguments vary — matching real sampling — via an internal call
counter folded into the hash; this is what makes the self-consistency
signal able to detect disagreement at all. See decision.md D-013."""
from __future__ import annotations

import hashlib

from demo_bot.scenarios import INJECTION_FRAGMENTS

KNOWLEDGE_BASE: dict[str, str] = {
    "capital of france": "Paris is the capital of France.",
    "capital of japan": "Tokyo is the capital of Japan.",
    "12 + 7": "12 + 7 is 19.",
    "boil": "Water boils at 100 degrees Celsius at sea level.",
    "largest planet": "Jupiter is the largest planet in our solar system.",
    # Off-topic (distribution_shift.OFF_TOPIC_QUERIES) — deliberately
    # thematically distinct from the factual Q&A answers above, so
    # embedding_drift actually has something to detect. Generic filler
    # text (FALLBACK_ANSWERS) doesn't embed distinctly enough from short
    # factual sentences to demonstrate the distribution-shift scenario.
    "pizza topping": "Pepperoni and mushroom is a classic, reliable pizza combination.",
    "sci-fi movie": "Terminator 2 and The Matrix are standout 90s sci-fi picks.",
    "paper airplane": "Fold the paper in half, then angle the wings back for a dart shape.",
    "favorite color": "Blue is a common favorite, often associated with calm and depth.",
}

FALLBACK_ANSWERS = [
    "Based on available information, that appears to be accurate.",
    "The most relevant answer here relates to established facts on the topic.",
    "That's a reasonable question — the commonly cited answer applies here.",
]

FABRICATED_DETAILS = [
    " Notably, this was independently confirmed by three separate studies in 2024.",
    " This has been the consensus view since at least the early 2000s.",
    " Industry experts widely agree this is the definitive answer.",
]

WEAK_MODEL_ERRORS = [
    "I'm not entirely sure, but it might be related to something else entirely.",
    "That's a bit unclear to me — could be a few different things.",
    "Hard to say for certain without more context.",
]

JUDGE_MARKER = "number from 0 to 10"


def _stable_hash(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _lookup_answer(query: str) -> str | None:
    q = query.lower()
    for key, answer in KNOWLEDGE_BASE.items():
        if key in q:
            return answer
    return None


def _extract_judged_answer(rubric_prompt: str) -> str:
    marker = "Answer: "
    idx = rubric_prompt.find(marker)
    if idx == -1:
        return rubric_prompt
    rest = rubric_prompt[idx + len(marker) :]
    end = rest.find("\n")
    return rest if end == -1 else rest[:end]


class SimulatedLLMClient:
    """Implements demo_bot.bot.LLMClient. Also doubles as the judge client:
    rubric-scoring prompts (which ask for 'a single number from 0 to 10')
    are detected by content, not by the judge's model/system_prompt call
    arguments (which real callers set to a fixed grader identity - see
    judge_trend.py - and so carry no signal about the answer's quality
    either way). The score comes from inspecting the actual answer text
    embedded in the prompt."""

    def __init__(self):
        self._call_index = 0

    def complete(self, system_prompt: str, query: str, model: str, temperature: float = 0.0) -> str:
        self._call_index += 1
        # Deterministic at temperature 0 (greedy decoding); folds in the
        # call index only when sampling, so repeated calls at the same
        # temperature diverge like real stochastic sampling would.
        seed_parts = [query, model, system_prompt[:40], str(round(temperature, 2))]
        if temperature > 0:
            seed_parts.append(str(self._call_index))
        seed = _stable_hash(*seed_parts)

        if JUDGE_MARKER in query:
            return self._judge_score(query, seed)

        injected = any(frag.strip() in system_prompt for frag in INJECTION_FRAGMENTS)
        is_weak_model = model.endswith("gpt-oss-20b")

        base = _lookup_answer(query)
        if base is None:
            base = FALLBACK_ANSWERS[seed % len(FALLBACK_ANSWERS)]

        if is_weak_model and seed % 100 < 40:
            return WEAK_MODEL_ERRORS[seed % len(WEAK_MODEL_ERRORS)]

        if injected:
            base += FABRICATED_DETAILS[seed % len(FABRICATED_DETAILS)]

        if temperature > 0:
            variants = [base, base + " (in short.)", "In other words: " + base]
            base = variants[seed % len(variants)]

        return base

    def _judge_score(self, rubric_prompt: str, seed: int) -> str:
        answer = _extract_judged_answer(rubric_prompt)
        degraded = answer in WEAK_MODEL_ERRORS or any(
            frag in answer for frag in FABRICATED_DETAILS
        )
        base_score = 3 if degraded else 9
        jitter = seed % 2
        return str(max(0, base_score - jitter))

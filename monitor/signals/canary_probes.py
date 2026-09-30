"""Fixed known-answer canary prompts, run on a schedule (see scheduler.py),
giving a small continuous accuracy signal essentially for free."""
from __future__ import annotations

import difflib
from dataclasses import dataclass

import yaml


@dataclass
class Probe:
    id: str
    prompt: str
    expected_answer: str
    match_type: str = "contains"  # exact | contains | fuzzy


def load_probes(path: str) -> list[Probe]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return [Probe(**p) for p in data.get("probes", [])]


def score_answer(actual: str, expected: str, match_type: str = "contains") -> bool:
    actual_n = actual.strip().lower()
    expected_n = expected.strip().lower()
    if match_type == "exact":
        return actual_n == expected_n
    if match_type == "contains":
        return expected_n in actual_n
    if match_type == "fuzzy":
        return difflib.SequenceMatcher(None, actual_n, expected_n).ratio() >= 0.6
    raise ValueError(f"unknown match_type: {match_type}")


class CanaryCache:
    """Caches (answer, correct) per (probe_id, model_id, prompt_version) so
    repeated scenario runs against unchanged bot state don't spend API quota."""

    def __init__(self):
        self._cache: dict[tuple, tuple[str, bool]] = {}

    def get(self, key: tuple):
        return self._cache.get(key)

    def set(self, key: tuple, value: tuple[str, bool]) -> None:
        self._cache[key] = value


def run_canary_batch(bot, probes: list[Probe], cache: CanaryCache | None = None) -> dict:
    results = []
    for probe in probes:
        cache_key = (probe.id, bot.model_id, bot.prompt_version)
        cached = cache.get(cache_key) if cache else None
        if cached is not None:
            answer, correct = cached
        else:
            answer = bot.ask(probe.prompt).text
            correct = score_answer(answer, probe.expected_answer, probe.match_type)
            if cache is not None:
                cache.set(cache_key, (answer, correct))
        results.append({"probe_id": probe.id, "answer": answer, "correct": correct})
    accuracy = sum(1 for r in results if r["correct"]) / len(results) if results else 1.0
    return {"accuracy": accuracy, "results": results}

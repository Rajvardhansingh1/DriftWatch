import pytest

from pathlib import Path

from demo_bot.bot import QABot
from monitor.signals.canary_probes import (
    CanaryCache,
    Probe,
    load_probes,
    run_canary_batch,
    score_answer,
)

PROBES_YAML = Path(__file__).resolve().parent.parent / "data" / "canary_probes.yaml"


class FakeLLMClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.call_count = 0

    def complete(self, system_prompt, query, model, temperature=0.0):
        reply = self.replies[self.call_count % len(self.replies)]
        self.call_count += 1
        return reply


def test_score_answer_exact():
    assert score_answer("Paris", "Paris", "exact") is True
    assert score_answer("paris", "Paris", "exact") is True
    assert score_answer("Paris, France", "Paris", "exact") is False


def test_score_answer_contains():
    assert score_answer("The capital is Paris.", "Paris", "contains") is True
    assert score_answer("The capital is Berlin.", "Paris", "contains") is False


def test_score_answer_fuzzy():
    assert score_answer("Pariss", "Paris", "fuzzy") is True
    assert score_answer("Antarctica", "Paris", "fuzzy") is False


def test_score_answer_unknown_match_type_raises():
    with pytest.raises(ValueError):
        score_answer("x", "y", "not-a-type")


def test_run_canary_batch_computes_accuracy():
    bot = QABot(client=FakeLLMClient(["Paris", "Wrong"]))
    probes = [
        Probe(id="p1", prompt="capital of France?", expected_answer="Paris"),
        Probe(id="p2", prompt="capital of Japan?", expected_answer="Tokyo"),
    ]
    result = run_canary_batch(bot, probes)
    assert result["accuracy"] == 0.5
    assert len(result["results"]) == 2


def test_run_canary_batch_empty_probes_is_full_accuracy():
    bot = QABot(client=FakeLLMClient(["anything"]))
    result = run_canary_batch(bot, [])
    assert result["accuracy"] == 1.0
    assert result["results"] == []


def test_canary_cache_avoids_repeat_llm_calls():
    client = FakeLLMClient(["Paris"])
    bot = QABot(client=client)
    probes = [Probe(id="p1", prompt="capital of France?", expected_answer="Paris")]
    cache = CanaryCache()

    run_canary_batch(bot, probes, cache=cache)
    assert client.call_count == 1

    run_canary_batch(bot, probes, cache=cache)
    assert client.call_count == 1, "second run with same bot state should hit cache, not the LLM"


def test_canary_cache_misses_after_bot_state_changes():
    client = FakeLLMClient(["Paris", "Wrong"])
    bot = QABot(client=client)
    probes = [Probe(id="p1", prompt="capital of France?", expected_answer="Paris")]
    cache = CanaryCache()

    run_canary_batch(bot, probes, cache=cache)
    assert client.call_count == 1

    bot.model_id = "some-other-model"
    run_canary_batch(bot, probes, cache=cache)
    assert client.call_count == 2, "changed model_id must not reuse a stale cached answer"


def test_real_canary_probes_yaml_loads_and_all_probes_pass_with_correct_answers():
    probes = load_probes(str(PROBES_YAML))
    assert len(probes) >= 3
    replies = [p.expected_answer for p in probes]
    bot = QABot(client=FakeLLMClient(replies))
    result = run_canary_batch(bot, probes)
    assert result["accuracy"] == 1.0

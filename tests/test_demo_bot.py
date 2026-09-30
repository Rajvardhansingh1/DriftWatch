from demo_bot.bot import QABot, DEFAULT_SYSTEM_PROMPT, STRONG_MODEL, WEAK_MODEL
from demo_bot import scenarios
from demo_bot.llm_client import get_default_client


class FakeLLMClient:
    def __init__(self, reply: str = "42"):
        self.reply = reply
        self.calls = []

    def complete(self, system_prompt: str, query: str, model: str, temperature: float = 0.0) -> str:
        self.calls.append((system_prompt, query, model, temperature))
        return self.reply


def make_bot(reply="42"):
    return QABot(client=FakeLLMClient(reply))


def test_baseline_ask_returns_response_and_metadata():
    bot = make_bot("Paris")
    resp = bot.ask("What is the capital of France?")
    assert resp.text == "Paris"
    assert resp.model_id == STRONG_MODEL
    assert resp.prompt_version == 0
    assert resp.latency_ms >= 0
    assert resp.timestamp > 0


def test_model_downgrade_scenario_activates_and_resets():
    bot = make_bot()
    assert bot.model_id == STRONG_MODEL
    scenarios.simulate_model_downgrade(bot)
    assert bot.model_id == WEAK_MODEL
    resp = bot.ask("hi")
    assert resp.model_id == WEAK_MODEL
    scenarios.reset_model_downgrade(bot)
    assert bot.model_id == STRONG_MODEL


def test_model_downgrade_actually_reaches_the_llm_client():
    bot = make_bot()
    scenarios.simulate_model_downgrade(bot)
    bot.ask("hi")
    system_prompt, query, model, temperature = bot.client.calls[-1]
    assert model == WEAK_MODEL


def test_injection_creep_scenario_is_gradual_and_reversible():
    bot = make_bot()
    assert bot.system_prompt == DEFAULT_SYSTEM_PROMPT
    scenarios.simulate_injection_creep(bot)
    first_len = len(bot.system_prompt)
    assert first_len > len(DEFAULT_SYSTEM_PROMPT)
    assert bot.prompt_version == 1
    scenarios.simulate_injection_creep(bot)
    assert len(bot.system_prompt) > first_len
    assert bot.prompt_version == 2
    scenarios.reset_injection_creep(bot)
    assert bot.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert bot.prompt_version == 0


def test_injection_creep_does_not_grow_past_defined_fragments():
    bot = make_bot()
    for _ in range(10):
        scenarios.simulate_injection_creep(bot)
    assert bot.prompt_version == len(scenarios.INJECTION_FRAGMENTS)


def test_distribution_shift_scenario_swaps_traffic_and_resets():
    bot = make_bot()
    on_topic = "What is the capital of France?"
    assert scenarios.next_query(bot, on_topic, cycle_index=0) == on_topic
    scenarios.simulate_distribution_shift(bot)
    off_topic = scenarios.next_query(bot, on_topic, cycle_index=0)
    assert off_topic in scenarios.OFF_TOPIC_QUERIES
    assert off_topic != on_topic
    scenarios.reset_distribution_shift(bot)
    assert scenarios.next_query(bot, on_topic, cycle_index=0) == on_topic


def test_scenarios_do_not_affect_a_second_bot_instance():
    bot_a = make_bot()
    bot_b = make_bot()
    scenarios.simulate_model_downgrade(bot_a)
    scenarios.simulate_injection_creep(bot_a)
    scenarios.simulate_distribution_shift(bot_a)
    assert bot_b.model_id == STRONG_MODEL
    assert bot_b.system_prompt == DEFAULT_SYSTEM_PROMPT
    assert scenarios.next_query(bot_b, "q", 0) == "q"


def test_get_default_client_raises_without_provider_keys(monkeypatch):
    import monitor.config as config_module

    monkeypatch.setattr(config_module.settings, "groq_api_key", "")
    monkeypatch.setattr(config_module.settings, "google_api_key", "")
    try:
        get_default_client()
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "GROQ_API_KEY" in str(e) or "GOOGLE_API_KEY" in str(e)

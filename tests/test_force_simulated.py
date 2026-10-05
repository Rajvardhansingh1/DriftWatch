from demo_bot.simulated_client import SimulatedLLMClient
from monitor import main as main_module
from monitor.config import settings


def test_force_simulated_overrides_provider_keys(monkeypatch):
    monkeypatch.setattr(settings, "force_simulated", True)
    monkeypatch.setattr(settings, "groq_api_key", "gsk_fake_key_for_test_only")

    def must_not_be_called():
        raise AssertionError("real provider client constructed while force_simulated is set")

    monkeypatch.setattr(main_module, "get_default_client", must_not_be_called)
    assert isinstance(main_module.get_llm_client(), SimulatedLLMClient)

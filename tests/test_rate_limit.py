import pytest

from demo_bot.bot import QABot
from monitor.rate_limit import RateLimitExceeded, SharedRateLimiter
from monitor.signals.judge_trend import score_with_judge


class FakeLLMClient:
    def complete(self, system_prompt, query, model, temperature=0.0):
        return "5"


def test_shared_limiter_caps_bot_asks():
    limiter = SharedRateLimiter(max_calls=2, period_seconds=60)
    bot = QABot(client=FakeLLMClient(), rate_limiter=limiter)
    bot.ask("q1")
    bot.ask("q2")
    with pytest.raises(RateLimitExceeded):
        bot.ask("q3")


def test_shared_limiter_is_shared_across_bot_and_judge():
    limiter = SharedRateLimiter(max_calls=2, period_seconds=60)
    bot = QABot(client=FakeLLMClient(), rate_limiter=limiter)
    bot.ask("q1")
    score_with_judge(FakeLLMClient(), "q", "a", rate_limiter=limiter)
    with pytest.raises(RateLimitExceeded):
        bot.ask("q2")

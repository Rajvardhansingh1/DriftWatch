from demo_bot.bot import DEFAULT_SYSTEM_PROMPT, STRONG_MODEL, WEAK_MODEL
from demo_bot.scenarios import INJECTION_FRAGMENTS
from demo_bot.simulated_client import SimulatedLLMClient


def test_temperature_zero_is_deterministic_across_calls():
    client = SimulatedLLMClient()
    a = client.complete(DEFAULT_SYSTEM_PROMPT, "What is the capital of France?", STRONG_MODEL, 0.0)
    b = client.complete(DEFAULT_SYSTEM_PROMPT, "What is the capital of France?", STRONG_MODEL, 0.0)
    assert a == b


def test_temperature_above_zero_varies_across_repeated_calls():
    client = SimulatedLLMClient()
    samples = {
        client.complete(DEFAULT_SYSTEM_PROMPT, "Tell me something interesting.", STRONG_MODEL, 0.7)
        for _ in range(6)
    }
    assert len(samples) > 1


def test_weak_model_sometimes_produces_a_degraded_answer():
    client = SimulatedLLMClient()
    answers = {
        client.complete(DEFAULT_SYSTEM_PROMPT, f"query number {i}", WEAK_MODEL, 0.0) for i in range(30)
    }
    from demo_bot.simulated_client import WEAK_MODEL_ERRORS

    assert any(a in WEAK_MODEL_ERRORS for a in answers)


def test_injected_system_prompt_appends_fabricated_detail():
    client = SimulatedLLMClient()
    corrupted_prompt = DEFAULT_SYSTEM_PROMPT + INJECTION_FRAGMENTS[0]
    answer = client.complete(corrupted_prompt, "What is the capital of France?", STRONG_MODEL, 0.0)
    from demo_bot.simulated_client import FABRICATED_DETAILS

    assert any(frag in answer for frag in FABRICATED_DETAILS)


def test_judge_scores_a_known_degraded_answer_low():
    client = SimulatedLLMClient()
    from demo_bot.simulated_client import WEAK_MODEL_ERRORS

    rubric_prompt = (
        "Query: what is it?\n"
        f"Answer: {WEAK_MODEL_ERRORS[0]}\n"
        "Respond with only a single number from 0 to 10."
    )
    score = client.complete("You are a strict grader.", rubric_prompt, "judge", 0.0)
    assert int(score) <= 4


def test_judge_scores_a_clean_answer_high():
    client = SimulatedLLMClient()
    rubric_prompt = (
        "Query: what is the capital of France?\n"
        "Answer: Paris is the capital of France.\n"
        "Respond with only a single number from 0 to 10."
    )
    score = client.complete("You are a strict grader.", rubric_prompt, "judge", 0.0)
    assert int(score) >= 7


def test_judge_scoring_is_unaffected_by_the_judges_own_call_arguments():
    # The judge is invoked with a fixed grading system prompt regardless
    # of the bot's actual (possibly degraded) model/system_prompt -
    # neither call argument carries any signal about the answer's
    # quality, so the score must come from the embedded answer text.
    client = SimulatedLLMClient()
    rubric_prompt = (
        "Query: q\nAnswer: Paris is the capital of France.\n"
        "Respond with only a single number from 0 to 10."
    )
    score_a = client.complete("You are a strict grader.", rubric_prompt, "judge", 0.0)
    score_b = client.complete(
        DEFAULT_SYSTEM_PROMPT + INJECTION_FRAGMENTS[0], rubric_prompt, WEAK_MODEL, 0.0
    )
    assert int(score_a) >= 7
    assert int(score_b) >= 7

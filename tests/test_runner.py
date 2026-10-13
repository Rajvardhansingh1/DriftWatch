"""The scheduled runner: claims jobs, opens the sealed key in memory, asks fixed probes, writes numbers only."""

import base64
import json
import logging
import uuid

import numpy as np
import pytest

from driftwatch_llm.core.embedding import make_embedder
from monitor.cloud import runner as runner_mod
from monitor.cloud import seal
from monitor.cloud.providers import BadReply, ProviderAuthError, ProviderError
from monitor.cloud.runner import Runner

PROVIDER_KEY = "gsk_" + "u" * 40
PRIVATE, PUBLIC = seal.generate_keypair()
MARKER = "ANSWER-TEXT-THAT-MUST-NOT-BE-STORED-4417"
PROBES = [
    {"position": 1, "prompt": "What is 2+2? Answer with just the number.", "expected": "4", "match_type": "contains"},
    {"position": 2, "prompt": "Capital of France? One word.", "expected": "Paris", "match_type": "exact"},
    {"position": 3, "prompt": "Say OK.", "expected": "OK", "match_type": "contains"},
]
GOOD = {PROBES[0]["prompt"]: "The answer is 4.", PROBES[1]["prompt"]: "Paris", PROBES[2]["prompt"]: "OK"}


class FakeApi:
    """The runner's view of the database: the same calls, kept in memory."""

    def __init__(self, probes=PROBES, model_id=None, key=PROVIDER_KEY, private=PRIVATE):
        self.model_id = model_id or str(uuid.uuid4())
        self.box = seal.seal(key, self.model_id, 1, PUBLIC)
        self.probes = probes
        self.vectors = {"baseline": None, "recent": None, "runs": 0}
        self.written: list[dict] = []
        self.finished: list[tuple[str, int]] = []
        self.jobs_left = 1
        self.lease = str(uuid.uuid4())

    def claim(self):
        if not self.jobs_left:
            return []
        self.jobs_left -= 1
        return [{"model_id": self.model_id, "provider": "groq", "model": "m", "lease": self.lease, "max_calls": len(self.probes) + 2, "probes": self.probes}]

    def get_secret(self, model_id, lease):
        assert (model_id, lease) == (self.model_id, self.lease)
        return self.box

    def get_vectors(self, model_id, lease):
        return dict(self.vectors)

    def save_vectors(self, model_id, lease, baseline, recent, runs):
        self.vectors = {"baseline": baseline, "recent": recent, "runs": runs}

    def write_signals(self, model_id, lease, events):
        self.written.extend(events)
        return len(events)

    def finish(self, model_id, lease, outcome, calls):
        self.finished.append((outcome, calls))
        self.jobs_left = 1  # the next pass finds it due again


def provider(answers=GOOD, calls=None, sampled=("alpha beta", "gamma delta")):
    seen = calls if calls is not None else []

    def complete(prov, key, model, system, prompt, temperature=0.0, **_):
        seen.append((prov, model, system, prompt, temperature, key))
        if temperature > 0:
            return sampled[(len([c for c in seen if c[4] > 0]) - 1) % len(sampled)]
        return answers[prompt]

    return complete


def make(api, complete=None, **kw):
    return Runner(api, PRIVATE, embedder=make_embedder("hash"), complete=complete or provider(), **kw)


def one(api, runner):
    summary = runner.run_once()
    return summary


def test_a_good_run_writes_the_signals_and_saves_vectors_without_any_text():
    api = FakeApi()
    calls = []
    summary = make(api, provider(calls=calls)).run_once()
    assert summary == {"jobs": 1, "ok": 1, "failed": 0}
    signals = {e["signal"]: e for e in api.written}
    assert set(signals) == {"canary_accuracy", "self_consistency", "combined_score"}  # no drift yet: the baseline is building
    assert signals["canary_accuracy"]["value"] == 1.0
    assert 0.0 <= signals["self_consistency"]["value"] <= 1.0 and 0.0 <= signals["combined_score"]["value"] <= 1.0
    assert api.finished == [("ok", 5)] and len(calls) == 5
    assert api.vectors["runs"] == 1 and base64.b64decode(api.vectors["baseline"])
    blob = json.dumps(api.written) + json.dumps(api.vectors)
    assert "The answer is 4" not in blob and "Paris" not in blob  # numbers only


def test_the_provider_gets_the_opened_key_the_fixed_system_prompt_and_the_right_temperatures():
    api = FakeApi()
    calls = []
    make(api, provider(calls=calls)).run_once()
    assert {c[5] for c in calls} == {PROVIDER_KEY} and {c[0] for c in calls} == {"groq"}
    assert {c[2] for c in calls} == {runner_mod.SYSTEM_PROMPT}
    assert [c[4] for c in calls] == [0.0, 0.0, 0.0, 0.7, 0.7]
    assert calls[3][3] == calls[4][3] == PROBES[0]["prompt"]  # the two extra samples re-ask the first probe


def test_canary_accuracy_is_the_share_of_probes_answered_as_expected():
    api = FakeApi()
    wrong = dict(GOOD)
    wrong[PROBES[1]["prompt"]] = "Lyon"
    make(api, provider(wrong)).run_once()
    assert next(e for e in api.written if e["signal"] == "canary_accuracy")["value"] == pytest.approx(2 / 3)


def test_embedding_drift_starts_after_the_baseline_runs_and_rises_when_the_answers_change():
    api = FakeApi()
    runner = make(api, provider())
    for _ in range(3):
        runner.run_once()
    assert not any(e["signal"] == "embedding_drift" for e in api.written)
    runner.run_once()  # the fourth run is the first measured one
    drift_same = [e["value"] for e in api.written if e["signal"] == "embedding_drift"]
    assert len(drift_same) == 1
    changed = {PROBES[0]["prompt"]: "Honestly the sum of those two small numbers is four, as everyone knows from school",
               PROBES[1]["prompt"]: "That would be the beautiful city of Paris on the river Seine",
               PROBES[2]["prompt"]: "Okay, sure, I will say that for you right now: OK"}
    changer = make(api, provider(changed))
    for _ in range(3):
        changer.run_once()
    drift_changed = [e["value"] for e in api.written if e["signal"] == "embedding_drift"]
    assert max(drift_changed) > drift_same[0] + 0.05
    assert api.vectors["runs"] == 7


def test_every_signal_event_follows_the_contract():
    api = FakeApi()
    runner = make(api)
    for _ in range(5):
        runner.run_once()
    from driftwatch_llm.core.events import validate_event

    for e in api.written:
        event = {"schema_version": 1, "source": "cloud_runner", "content_capture": False, **e}
        validate_event(event)
        assert e["signal"] in {"canary_accuracy", "self_consistency", "embedding_drift", "combined_score"}
        assert len(e["meta"]) <= 8 and e["meta"]["provider"] == "groq"
        assert uuid.UUID(e["event_id"])


@pytest.mark.parametrize(
    "exc,outcome",
    [(ProviderAuthError("x"), "provider_auth"), (ProviderError("x"), "provider_error"), (BadReply("x"), "bad_reply"), (RuntimeError("boom " + PROVIDER_KEY), "runner_error")],
)
def test_failures_become_a_fixed_outcome_and_write_nothing(exc, outcome):
    api = FakeApi()

    def failing(*a, **k):
        raise exc

    summary = make(api, failing).run_once()
    assert summary == {"jobs": 1, "ok": 0, "failed": 1}
    assert api.finished == [(outcome, 0)] and api.written == [] and api.vectors["runs"] == 0


def test_a_failure_in_the_middle_counts_the_calls_made_and_writes_no_partial_signals():
    api = FakeApi()
    state = {"n": 0}

    def flaky(prov, key, model, system, prompt, temperature=0.0, **_):
        state["n"] += 1
        if state["n"] == 3:
            raise ProviderError("down")
        return GOOD[prompt]

    make(api, flaky).run_once()
    assert api.finished == [("provider_error", 2)] and api.written == []


def test_a_sealed_key_that_cannot_be_opened_is_a_runner_error_and_no_provider_call_is_made():
    api = FakeApi()
    wrong_private, _ = seal.generate_keypair()
    calls = []
    Runner(api, wrong_private, embedder=make_embedder("hash"), complete=provider(calls=calls)).run_once()
    assert api.finished == [("runner_error", 0)] and calls == []


def test_the_runner_never_exceeds_the_calls_the_database_allowed():
    api = FakeApi()
    api.claim = lambda: [{"model_id": api.model_id, "provider": "groq", "model": "m", "lease": api.lease, "max_calls": 4, "probes": PROBES}]
    calls = []
    make(api, provider(calls=calls)).run_once()
    assert len(calls) <= 4 and api.finished[0][0] == "runner_error"


def test_a_probe_list_that_is_empty_or_malformed_is_a_runner_error_not_a_crash():
    for probes in ([], [{"position": 1}], [{"position": 1, "prompt": "p", "expected": "e", "match_type": "regex"}]):
        api = FakeApi(probes=probes)
        make(api).run_once()
        assert api.finished[0][0] == "runner_error" and api.written == []


def test_one_bad_job_does_not_stop_the_next(capsys):
    good, bad = FakeApi(), FakeApi()

    class Both:
        sent = False

        def claim(self):
            if self.sent:
                return []
            self.sent = True
            return [
                {"model_id": bad.model_id, "provider": "groq", "model": "m", "lease": bad.lease, "max_calls": 5, "probes": PROBES},
                {"model_id": good.model_id, "provider": "groq", "model": "m", "lease": good.lease, "max_calls": 5, "probes": PROBES},
            ]

        def __getattr__(self, name):
            return lambda model_id, *args: getattr(good if model_id == good.model_id else bad, name)(model_id, *args)

    def complete(prov, key, model, system, prompt, temperature=0.0, **_):
        return GOOD[prompt]

    bad.box = seal.seal(PROVIDER_KEY, str(uuid.uuid4()), 1, PUBLIC)  # sealed for another row: cannot be opened
    summary = Runner(Both(), PRIVATE, embedder=make_embedder("hash"), complete=complete).run_once()
    assert summary == {"jobs": 2, "ok": 1, "failed": 1} and good.finished[0][0] == "ok" and bad.finished[0][0] == "runner_error"


# -- nothing secret reaches output -------------------------------------------------------------------------------
def test_no_key_answer_or_private_key_reaches_stdout_stderr_or_logs(capsys, caplog):
    caplog.set_level(logging.DEBUG)
    api = FakeApi()
    answers = {k: f"{v} {MARKER}" for k, v in GOOD.items()}
    runner = make(api, provider(answers))
    runner.run_once()
    api2 = FakeApi()

    def boom(*a, **k):
        raise RuntimeError(f"provider said {PROVIDER_KEY} {MARKER} {PRIVATE}")

    make(api2, boom).run_once()
    out = capsys.readouterr()
    everything = out.out + out.err + "\n".join(r.getMessage() for r in caplog.records) + json.dumps(api.written) + json.dumps(api2.written)
    for secret in (PROVIDER_KEY, PRIVATE, MARKER):
        assert secret not in everything
    assert "outcome=ok" in everything and "outcome=runner_error" in everything  # it did say something useful


def test_on_github_the_key_is_registered_for_masking_and_appears_nowhere_else(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    api = FakeApi()
    make(api).run_once()
    out = capsys.readouterr().out
    assert f"::add-mask::{PROVIDER_KEY}" in out
    assert out.replace(f"::add-mask::{PROVIDER_KEY}", "").count(PROVIDER_KEY) == 0
    assert out.index("::add-mask::") < out.index("outcome=")  # masked before anything else is printed for the job


def test_the_module_has_no_way_to_print_text_it_was_given():
    src = open(runner_mod.__file__, encoding="utf-8").read()
    assert src.count("print(") <= 6  # the mask, job and summary lines and the two fixed error lines: all fixed words and counts


# -- the real API client -----------------------------------------------------------------------------------------
def test_the_api_client_calls_the_runner_functions_with_the_secret_and_maps_errors():
    import httpx

    seen = []

    def handler(request):
        seen.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("runner_claim_jobs"):
            return httpx.Response(200, json=[])
        return httpx.Response(401, json={"code": "PT401", "message": f"no {PROVIDER_KEY}"})

    api = runner_mod.RunnerApi("https://x.supabase.co", "anon", "the-runner-secret", transport=httpx.MockTransport(handler))
    assert api.claim() == []
    assert seen[0] == ("/rest/v1/rpc/runner_claim_jobs", {"p_secret": "the-runner-secret"})
    with pytest.raises(runner_mod.RunnerApiError) as e:
        api.get_secret("m", "l")
    assert PROVIDER_KEY not in str(e.value) and "the-runner-secret" not in str(e.value)
    api.claim()  # still works after an error


def test_main_exits_non_zero_when_a_job_failed_and_zero_otherwise(monkeypatch, capsys):
    api = FakeApi()
    monkeypatch.setattr(runner_mod, "RunnerApi", lambda *a, **k: api)
    monkeypatch.setattr(runner_mod, "make_embedder", lambda kind: make_embedder("hash"))
    monkeypatch.setattr(runner_mod, "provider_complete", provider())
    env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "anon", "RUNNER_SECRET": "s", "RUNNER_PRIVATE_KEY": PRIVATE}
    assert runner_mod.main(env) == 0
    monkeypatch.setattr(runner_mod, "provider_complete", lambda *a, **k: (_ for _ in ()).throw(ProviderError("x")))
    assert runner_mod.main(env) == 1
    assert runner_mod.main({}) == 2  # missing settings: a clear, quiet failure
    assert PRIVATE not in capsys.readouterr().out


# -- key rotation: the runner can hold several private keys, chosen by the key id sealed into each row ----------
def test_rows_sealed_under_either_key_id_open_while_both_keys_are_held():
    priv2, pub2 = seal.generate_keypair()
    old, new = FakeApi(), FakeApi()
    new.box = seal.seal(PROVIDER_KEY, new.model_id, 2, pub2)
    for api in (old, new):
        Runner(api, {1: PRIVATE, 2: priv2}, embedder=make_embedder("hash"), complete=provider()).run_once()
        assert api.finished == [("ok", 5)]


def test_a_retired_key_id_is_a_clear_runner_error_not_a_crash():
    priv2, pub2 = seal.generate_keypair()
    api = FakeApi()
    api.box = seal.seal(PROVIDER_KEY, api.model_id, 2, pub2)
    calls = []
    Runner(api, {1: PRIVATE}, embedder=make_embedder("hash"), complete=provider(calls=calls)).run_once()  # key 2 is not held
    assert api.finished == [("runner_error", 0)] and calls == []


def test_main_reads_one_key_or_a_map_of_keys(monkeypatch):
    priv2, pub2 = seal.generate_keypair()
    api = FakeApi()
    api.box = seal.seal(PROVIDER_KEY, api.model_id, 2, pub2)
    monkeypatch.setattr(runner_mod, "RunnerApi", lambda *a, **k: api)
    monkeypatch.setattr(runner_mod, "make_embedder", lambda kind: make_embedder("hash"))
    monkeypatch.setattr(runner_mod, "provider_complete", provider())
    base = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_ANON_KEY": "anon", "RUNNER_SECRET": "s"}
    assert runner_mod.main({**base, "RUNNER_PRIVATE_KEYS": json.dumps({"1": PRIVATE, "2": priv2})}) == 0
    api2 = FakeApi()
    monkeypatch.setattr(runner_mod, "RunnerApi", lambda *a, **k: api2)
    assert runner_mod.main({**base, "RUNNER_PRIVATE_KEY": PRIVATE}) == 0  # a single key is key id 1
    assert runner_mod.main({**base, "RUNNER_PRIVATE_KEYS": "not json"}) == 2

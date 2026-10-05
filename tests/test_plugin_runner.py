import pytest

from monitor.plugins.runner import EvaluatorError, run_evaluator, scrubbed_env


def write(tmp_path, body: str):
    p = tmp_path / "evaluator.py"
    p.write_text(body, encoding="utf-8")
    return p


GOOD = (
    "import json, sys\n"
    "payload = json.load(sys.stdin)\n"
    "print(json.dumps({'score': 0.5, 'echo': payload['x']}))\n"
)


def test_valid_evaluator_returns_score(tmp_path):
    result = run_evaluator(write(tmp_path, GOOD), {"x": 7})
    assert result.output == {"score": 0.5, "echo": 7}


def test_timeout_is_controlled_error(tmp_path):
    script = write(tmp_path, "import time\ntime.sleep(30)\n")
    with pytest.raises(EvaluatorError, match="time limit"):
        run_evaluator(script, {}, timeout=1.0)


def test_nonzero_exit_is_controlled_error(tmp_path):
    with pytest.raises(EvaluatorError, match="exited with status"):
        run_evaluator(write(tmp_path, "import sys\nsys.exit(3)\n"), {})


def test_non_json_output_rejected(tmp_path):
    with pytest.raises(EvaluatorError, match="not valid JSON"):
        run_evaluator(write(tmp_path, "print('hello')\n"), {})


def test_score_out_of_range_rejected(tmp_path):
    with pytest.raises(EvaluatorError, match="in \\[0, 1\\]"):
        run_evaluator(write(tmp_path, "import json\nprint(json.dumps({'score': 9}))\n"), {})


def test_output_size_cap_enforced(tmp_path):
    body = "import json\nprint(json.dumps({'score': 0.1, 'pad': 'x' * 100000}))\n"
    with pytest.raises(EvaluatorError, match="size limit"):
        run_evaluator(write(tmp_path, body), {})


def test_secrets_are_not_passed_to_child():
    env = scrubbed_env(
        {
            "PATH": "/bin",
            "GROQ_API_KEY": "gsk_x",
            "SUPABASE_JWT_SECRET": "s",
            "MY_SERVICE_TOKEN": "t",
            "DB_PASSWORD": "p",
            "HOME": "/h",
        }
    )
    assert env == {"PATH": "/bin", "HOME": "/h"}


def test_missing_script_is_controlled_error(tmp_path):
    with pytest.raises(EvaluatorError, match="not found"):
        run_evaluator(tmp_path / "nope.py", {})

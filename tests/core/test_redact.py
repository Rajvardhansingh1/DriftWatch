"""Everything that leaves the machine for grading goes through redact() first. A planted secret must not survive it."""

import pytest

from driftwatch_llm.core.redact import MAX_CHARS, prepare_for_judge, redact

SECRETS = [
    "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2",
    "sk-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4",
    "gsk_" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4",
    "AIza" + "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p",
    "dw_" + "a1b2c3d4e5" + "_" + "0123456789abcdef" * 4,
    "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8",
    "xox" + "b-1234567890-0987654321-AbCdEfGhIjKlMnOpQrStUvWx",  # built in two pieces so no secret scanner mistakes the test data for a real token
    "AKIA" + "ABCDEFGHIJKLMNOP",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
    "Bearer abcDEF123456.token-value_here",
    "postgresql://admin:hunter2pass@db.example.com:5432/app",
    "https://user:s3cret@internal.example.com/path",
]


@pytest.mark.parametrize("secret", SECRETS)
def test_secret_shaped_strings_do_not_survive(secret):
    out = redact(f"Here you go: {secret} and that is all.")
    assert secret not in out
    for fragment in ("hunter2pass", "s3cret", "A1b2C3d4E5f6", "abcDEF123456", "a1b2c3d4e5f6"):
        assert fragment not in out
    assert "Here you go:" in out and "and that is all." in out  # the rest of the text is untouched


@pytest.mark.parametrize(
    "pii",
    [
        "jane.doe+billing@example.co.uk",
        "4111 1111 1111 1111",
        "4111-1111-1111-1111",
        "5500000000000004",
        "+1 (415) 555-0132",
        "415-555-0132",
        "+44 20 7946 0958",
        "123-45-6789",
    ],
)
def test_personal_data_shapes_do_not_survive(pii):
    out = redact(f"Contact {pii} about the invoice.")
    digits = "".join(ch for ch in pii if ch.isdigit())
    assert pii not in out and (len(digits) < 7 or digits not in "".join(ch for ch in out if ch.isdigit()))
    assert "about the invoice." in out


def test_ordinary_text_with_small_numbers_is_left_alone():
    text = "The Team plan costs $49 a month, renews on the 5th and refunds take 7 business days (order #12345)."
    assert redact(text) == text


def test_redaction_marks_what_it_removed_without_keeping_a_hint_of_the_value():
    out = redact("mail bob@example.com key sk-" + "x" * 24)
    assert "[email]" in out and "[secret]" in out and "bob" not in out and "xxxx" not in out


def test_prepare_for_judge_redacts_then_cuts_to_the_limit():
    secret = "sk-" + "Z9y8X7w6V5u4T3s2R1q0P9o8"
    long_text = ("lorem ipsum " * 400) + secret
    out = prepare_for_judge(long_text)
    assert len(out) <= MAX_CHARS and secret not in out
    near_the_cut = "word " * 296 + "sk-" + "Z9y8X7w6V5u4T3s2R1q0P9o8"  # a secret straddling the cut must not leak its head
    assert "sk-Z9y8" not in prepare_for_judge(near_the_cut)


def test_prepare_for_judge_handles_odd_input():
    assert prepare_for_judge("") == "" and prepare_for_judge("   ") == ""
    assert prepare_for_judge(None) == "" and prepare_for_judge(5) == ""  # type: ignore[arg-type]


def test_the_module_needs_only_the_standard_library():
    import ast
    from pathlib import Path

    import driftwatch_llm.core.redact as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    roots = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    assert roots <= {"re", "__future__"}

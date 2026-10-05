import logging

from monitor.logging_redaction import RedactingFilter, redact


def test_bearer_token_redacted():
    assert "abc.def" not in redact("Authorization: Bearer abc.def.ghi")


def test_groq_and_google_keys_redacted():
    out = redact("keys gsk_abcdefghijklmnop AIzaSyD1234567890abcdefghijk")
    assert "gsk_abcdefghijklmnop" not in out
    assert "AIzaSyD" not in out


def test_postgres_password_redacted():
    out = redact("connect postgresql://user:hunter2@db.example.com/x")
    assert "hunter2" not in out


def test_plain_text_untouched():
    assert redact("signal embedding_drift value=0.2") == "signal embedding_drift value=0.2"


def test_filter_redacts_emitted_record(caplog):
    logger = logging.getLogger("redaction-test")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="redaction-test"):
        logger.info("provider error: key=gsk_abcdefghijklmnop")
    assert "gsk_abcdefghijklmnop" not in caplog.text


def test_global_install_redacts_records_from_any_logger(caplog):
    from monitor.logging_redaction import install

    install()
    with caplog.at_level(logging.INFO):
        logging.getLogger("some.library").info("auth header Bearer abc.def.ghi leaked")
    assert "abc.def.ghi" not in caplog.text

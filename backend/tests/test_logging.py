from __future__ import annotations

import logging

from postmortem.logging import log_event


def test_request_logging_includes_request_id(client, auth_headers, caplog):
    caplog.set_level(logging.INFO, logger="postmortem.app")

    response = client.get(
        "/healthz",
        headers={**auth_headers, "X-Request-ID": "test-request-1"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-1"
    assert "http_request_started" in caplog.text
    assert "http_request_completed" in caplog.text
    assert "request_id=test-request-1" in caplog.text
    assert "path=/healthz" in caplog.text


def test_log_event_quotes_safe_key_value_fields(caplog):
    logger = logging.getLogger("postmortem.test")
    caplog.set_level(logging.INFO, logger="postmortem.test")

    log_event(logger, logging.INFO, "test_event", simple="ok", spaced="two words")

    assert "test_event" in caplog.text
    assert "simple=ok" in caplog.text
    assert 'spaced="two words"' in caplog.text

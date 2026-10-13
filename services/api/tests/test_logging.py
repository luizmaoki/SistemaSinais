import json
import logging
from uuid import uuid4

from app.logging_config import SafeJsonFormatter, application_logger


def test_logging_drops_payload_credentials_urls_and_exception_details():
    secret = "SENSITIVE_SENTINEL"
    message = {"event": "request", "correlation_id": str(uuid4()), "method": "GET", "status": 200,
               "latency_ms": 3, "url": "https://example.test/?token=" + secret,
               "body": secret, "authorization": secret, "email": secret}
    record = logging.LogRecord("capital.api", logging.INFO, "", 1, message, (), (ValueError, ValueError(secret), None))
    rendered = SafeJsonFormatter().format(record)
    assert secret not in rendered
    assert json.loads(rendered)["correlation_id"] == message["correlation_id"]
    record.msg = secret
    assert secret not in SafeJsonFormatter().format(record)


def test_application_logger_emits_info_with_single_safe_handler():
    logger = application_logger("capital.test")
    application_logger("capital.test")
    assert logger.isEnabledFor(logging.INFO)
    assert not logger.propagate
    assert sum(isinstance(handler.formatter, SafeJsonFormatter) for handler in logger.handlers) == 1

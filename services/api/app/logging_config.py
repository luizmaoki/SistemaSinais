"""Structured application logs with an explicit metadata allowlist."""
from datetime import datetime, timezone
import json
import logging
import re
import sys


class SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        message = record.msg if isinstance(record.msg, dict) else {}
        result = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "event": message.get("event") if message.get("event") in {
                "request", "request_failed", "task_completed", "task_skipped"
            } else "unstructured_log",
        }
        correlation = message.get("correlation_id")
        if isinstance(correlation, str) and re.fullmatch(r"[0-9a-f-]{36}", correlation):
            result["correlation_id"] = correlation
        if message.get("method") in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
            result["method"] = message["method"]
        if message.get("task") in {"capital.ingest", "capital.alerts"}:
            result["task"] = message["task"]
        if message.get("provider") in {"sec_edgar", "coinbase"}:
            result["provider"] = message["provider"]
        for key in ("status", "latency_ms", "created"):
            value = message.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                result[key] = value
        return json.dumps(result)


def application_logger(name):
    logger = logging.getLogger(name)
    if not any(isinstance(handler.formatter, SafeJsonFormatter) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(SafeJsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger

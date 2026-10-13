from celery import Celery
from redis import Redis
from app.config import get_settings
from app.database import SessionLocal
from app.ingestion import evaluate_alerts, sync
from app.logging_config import application_logger
logger = application_logger("capital.worker")

settings = get_settings()
settings.assert_auth_ready()
celery_app = Celery("capital_intelligence", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "ingest-sec": {
            "task": "capital.ingest",
            "schedule": settings.ingestion_interval_seconds,
            "args": ["sec_edgar"],
        },
        "evaluate-alerts": {"task": "capital.alerts", "schedule": 60.0},
    },
)


@celery_app.task(name="capital.ingest")
def ingest(provider="sec_edgar"):
    if provider not in {"sec_edgar", "coinbase"}:
        return {"status": "INVALID_PROVIDER"}
    redis = Redis.from_url(settings.redis_url)
    lock = redis.lock("capital:ingestion:" + provider, timeout=600, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"status": "ALREADY_RUNNING"}
    try:
        result = sync(provider, use_lock=False)
        logger.info({"event": "task_completed", "task": "capital.ingest", "provider": provider})
        return result
    finally:
        if lock.owned():
            lock.release()


@celery_app.task(name="capital.alerts")
def alerts():
    redis = Redis.from_url(settings.redis_url)
    lock = redis.lock("capital:alerts", timeout=120, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return {"status": "ALREADY_RUNNING"}
    try:
        with SessionLocal() as session:
            created = evaluate_alerts(session)
            logger.info({"event": "task_completed", "task": "capital.alerts", "created": created})
            return {"created": created}
    finally:
        if lock.owned():
            lock.release()


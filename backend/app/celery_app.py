from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery = Celery("jobops", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.timezone,
    task_default_queue="default",
    task_routes={"app.tasks.discover_source": {"queue": "discovery"}},
    beat_schedule={
        "discover-all-sources": {
            "task": "app.tasks.discover_all",
            "schedule": settings.poll_interval_minutes * 60,
        },
        "generate-daily-report": {
            "task": "app.tasks.generate_daily_report",
            "schedule": crontab(hour=settings.report_generation_hour_local, minute=0),
        },
        "email-daily-report": {
            "task": "app.tasks.email_daily_report",
            "schedule": crontab(hour=settings.report_generation_hour_local, minute=20),
        },
    },
)
celery.autodiscover_tasks(["app"])

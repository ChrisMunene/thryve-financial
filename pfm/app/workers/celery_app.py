from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "pfm",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.categorization_tasks",
        "app.workers.aggregation_tasks",
        "app.workers.recap_tasks",
        "app.workers.training_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

celery_app.conf.beat_schedule = {
    "hourly-correction-aggregation": {
        "task": "app.workers.aggregation_tasks.aggregate_corrections",
        "schedule": crontab(minute=0),  # every hour
    },
    "weekly-recap-generation": {
        "task": "app.workers.recap_tasks.generate_recaps",
        "schedule": crontab(hour=8, minute=0, day_of_week="monday"),
    },
    "weekly-training-export": {
        "task": "app.workers.training_tasks.export_training_data",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
    },
}

#!/bin/sh
set -e
if [ "$1" = "api" ]; then
    python -m app.bootstrap
    alembic upgrade head
    python -m app.seeds
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000
elif [ "$1" = "worker" ]; then
    exec celery -A app.celery_app.celery worker --loglevel=INFO -Q default,discovery --concurrency=4
elif [ "$1" = "scheduler" ]; then
    exec celery -A app.celery_app.celery beat --loglevel=INFO
else
    exec "$@"
fi

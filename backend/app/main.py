from fastapi import FastAPI

from app.api import (
    routes_health, routes_jobs, routes_panic, routes_policy, routes_reports,
    routes_review, routes_sources,
)
from app.config import get_settings
from app.logging import configure_logging

configure_logging(get_settings().log_level)

app = FastAPI(title="JobOps", version="0.1.0")
app.include_router(routes_health.router)
app.include_router(routes_sources.router)
app.include_router(routes_policy.router)
app.include_router(routes_jobs.router)
app.include_router(routes_panic.router)
app.include_router(routes_reports.router)
app.include_router(routes_review.router)

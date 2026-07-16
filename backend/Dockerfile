FROM python:3.12-slim AS base
WORKDIR /srv/jobops
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e . 2>/dev/null || true
COPY . .
RUN pip install -e .
# entrypoint: migrations run once from the api container via entrypoint.sh
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

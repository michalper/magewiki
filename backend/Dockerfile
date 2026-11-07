FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false

RUN pip install "poetry==1.8.3"

WORKDIR /app

COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root

# litellm pins filelock<4.0, blocking poetry from resolving the fix for 13 real
# filelock CVEs (3.32.7 -> 4.2.1) — but litellm only imports filelock from its own
# CLI/proxy-client tooling (litellm/proxy/client/cli/commands/*.py), which this app
# never invokes (we only call litellm.acompletion/aembedding). Forcing the upgrade
# out-of-band of poetry's lock is safe in practice; revisit once litellm relaxes its
# own pin and this can go back through poetry update normally.
RUN pip install --no-deps "filelock>=4.0.9,<5"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

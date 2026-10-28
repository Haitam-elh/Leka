# The LEKA backend, as one image.
#
# ONE IMAGE, TWO PROCESSES. The API and the worker are the same code — the
# modular monolith of docs/adr/002 — so they are the same image, started with
# different commands. Two images built from one repository drift: the worker
# gets deployed a week late and runs jobs whose code no longer matches the
# rows they touch.
#
# MULTI-STAGE, because the compiler is not needed to serve a request. The
# builder stage may install gcc to build any wheel that is missing for the
# target platform; the runtime stage never sees it. That is not only about
# size: a container that cannot compile is a container in which an attacker
# who lands cannot compile either.
#
# NON-ROOT, because a process that does not need to write to / should not be
# able to. The venv is owned by the unprivileged user, and nothing in the
# image is writable by it apart from /tmp.

# ── builder ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Pinned to the minor: 3.13 is excluded by requires-python, and "slim" alone
# would follow a major upgrade on the next rebuild.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Dependencies before source, so that editing a Python file does not reinstall
# asyncpg. pyproject.toml is the whole dependency declaration here — there is
# no requirements.txt to fall out of step with it.
COPY pyproject.toml README.md* ./
RUN mkdir -p leka && touch leka/__init__.py && pip install --no-cache-dir .

COPY leka ./leka
COPY alembic ./alembic
COPY alembic.ini ./
# Installed again, now with the real package, so the venv holds the code
# rather than a stub.
RUN pip install --no-cache-dir --no-deps .

# ── runtime ──────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# curl is the healthcheck. It is the one thing worth 2 MB here: without it the
# container reports healthy as long as the process exists, which is exactly
# the failure /api/v1/health was written to catch.
# Tesseract (French, English) reads an image or a scanned page joined to an
# intention, and poppler's pdftoppm draws that page for it (2026-10-28): on
# the box, nothing sent out, nothing paid — about 40 MB.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
       tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 leka

COPY --from=builder --chown=leka:leka /opt/venv /opt/venv
WORKDIR /app
COPY --chown=leka:leka alembic ./alembic
COPY --chown=leka:leka alembic.ini ./
# The agents: content, not code (ADR 004), kept at the repository's root —
# outside this build's context — and given to it by name: cd.yml passes
# `build-contexts: agents=agents`; by hand,
#   docker buildx build --build-context agents=agents api
# Without them the capability catalogue (LEKA-393) would hold no agent.
COPY --from=agents --chown=leka:leka . ./agents
ENV LEKA_AGENTS_DIR=/app/agents

USER leka
EXPOSE 8000

# Honest about what it measures: the API's own report, which probes
# PostgreSQL and Redis and answers 503 when either is unreachable.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

# The API. The other processes of the same image override it — see
# deploy/docker-compose.production.yml:
#   python -m leka.db.migrate           once, before anything starts
#   python -m leka.platform.worker      runs the jobs
#   python -m leka.platform.scheduler   puts the tick and the sweeps on the queue
CMD ["uvicorn", "leka.main:app", "--host", "0.0.0.0", "--port", "8000"]

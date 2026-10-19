# Backend image WITH the agent's browser (Chromium via Playwright).
#
# Why a Dockerfile at all: Render's plain Python runtime can `pip install` the Playwright package but cannot install the
# system libraries Chromium needs (that takes root). A Docker build runs as root, so `playwright install --with-deps`
# works here. Everything else about the backend is unchanged. See docs/BROWSER_SETUP.md.
#
# Python matches backend/.python-version (3.12). The base is pinned to Debian 12 ("bookworm") on purpose: Playwright's
# `install --with-deps` installs system packages by name for the Debian/Ubuntu releases it knows, and a newer Debian
# default would make that step fail or install the wrong libraries.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Dependencies first so code-only changes reuse this (slow) layer.
COPY requirements.txt requirements-browser.txt ./
RUN pip install -r requirements.txt -r requirements-browser.txt \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Render sets $PORT; 10000 is its default.
EXPOSE 10000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]

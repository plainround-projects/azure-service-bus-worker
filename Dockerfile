# Two stages: the first installs the hash-pinned dependencies and the package into a virtual environment, the second
# copies only that environment and the SQL scripts onto a clean base. The base is pinned by version and digest
# (read on 2026-10-26); update both together.
FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6 AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.lock ./
RUN /opt/venv/bin/pip install --require-hashes -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN /opt/venv/bin/pip install --no-deps .

FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    SQL_DIR=/app/sql LEDGER_PATH=/data/orders.db HEALTH_PORT=8080
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin worker \
    && mkdir /data && chown 10001 /data
COPY --from=build /opt/venv /opt/venv
COPY sql /app/sql
USER 10001
VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/live', timeout=2)"]
# SIGTERM finishes the message in hand, settles it, closes the receiver and exits 0.
CMD ["order-worker"]

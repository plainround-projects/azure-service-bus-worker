# Docker and the Dockerfile

*Packages the worker as a small non-root image. Pinned here: Docker Engine 24 (author's machine); base image python:3.13.12-slim-bookworm.*

## What it is

Docker packages a program and everything it needs (the language runtime, libraries, files) into an **image**, and runs the image as a **container**: an isolated process with its own view of the file system. A **Dockerfile** is the text recipe that builds the image, one instruction at a time.

## Why this repository uses it

The deployed worker runs in Azure Container Apps, which runs images. The image also carries the SQL scripts and the offline simulation so it can be smoke-tested without Azure.

## Where it appears

| File | What it does with it |
|---|---|
| `Dockerfile` | The two-stage build. |
| `.dockerignore` | What is not sent to the build. |
| `scripts/docker-smoke.sh` | Runs and checks the image. |
| `Makefile` | `make docker-build`, `make docker-smoke`. |

## How it works underneath

An image is a stack of read-only **layers**. Each Dockerfile instruction (`RUN`, `COPY`) adds a layer. Docker caches layers: if an instruction and everything above it are unchanged, the layer is reused, which is why files that change rarely (the lock file) are copied before files that change often (the source).

A **multi-stage build** has several `FROM` lines. Early stages can use heavy tools to build; the final stage copies only the results (`COPY --from=build`), so the shipped image stays small. `FROM image@sha256:...` pins the base image by its content hash, so the base cannot change under you.

A container runs one main process (`CMD`). Docker stops it by sending `SIGTERM` and, after a timeout, `SIGKILL`. `USER` sets who the process runs as; running as a non-root user limits the damage of a break-in. `HEALTHCHECK` runs a command from time to time to report whether the container is healthy. A `.dockerignore` file lists what must not be sent to the build.

## Walkthrough of this repository's use

### The build stage

```dockerfile
FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6 AS build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN python -m venv /opt/venv
COPY requirements.lock ./
RUN /opt/venv/bin/pip install --require-hashes -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
RUN /opt/venv/bin/pip install --no-deps .
```

The first `FROM` (pinned by version and digest) starts the build stage. The virtual environment `/opt/venv` is created, the hash-pinned dependencies are installed from `requirements.lock` (copied first so this layer is cached), then the source is copied and the package installed with `--no-deps`.

### The final stage

```dockerfile
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
```

The second `FROM` starts clean and copies only the environment and the `sql/` folder (`COPY sql /app/sql`). `ENV SQL_DIR=/app/sql LEDGER_PATH=/data/orders.db HEALTH_PORT=8080` sets defaults the program reads. `useradd --system --uid 10001 ...` creates a user that cannot log in, `mkdir /data && chown 10001 /data` makes the ledger folder writable by that user, and `USER 10001` switches to it. `VOLUME /data` marks the ledger folder as data that may be mounted. `HEALTHCHECK` calls `/live` on the health port every 30 seconds. `CMD ["order-worker"]` is the program the container runs; the comment above it says `SIGTERM` finishes the message in hand and exits 0.

## Try it yourself

See the two stages and the pinned base.

```bash
grep -n '^FROM' Dockerfile
```

You should see something like this:

```text
4:FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6 AS build
14:FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6
```

Find who runs the container, the port, the health check and the command.

```bash
grep -nE '^(USER|EXPOSE|HEALTHCHECK|CMD|VOLUME)' Dockerfile
```

You should see something like this:

```text
21:USER 10001
22:VOLUME /data
23:EXPOSE 8080
24:HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
27:CMD ["order-worker"]
```

Count the ignore rules.

```bash
wc -l .dockerignore
```

You should see something like this:

```text
19 .dockerignore
```

## Mistakes people make

- Running as root. Both images create a user with a fixed numeric id and switch to it.
- Using `latest` or a bare tag as the base. The base here is pinned by version and digest.
- Copying the source before installing dependencies, which defeats layer caching.
- Baking secrets into an image. There are none: the app learns addresses from the environment.
- Shell-form `CMD` without `exec`: the shell receives the stop signal and the app does not. The first image uses `exec gunicorn` for this reason.

## Check yourself

1. **What is the difference between an image and a container?**
   Answer: An image is the packaged recipe result; a container is a running process started from it.

2. **What is a multi-stage build for?**
   Answer: To build with heavy tools in one stage and ship only the result in a small final stage.

3. **Why copy the lock file before the source?**
   Answer: So the slow install layer is reused when only the source changed.

4. **What does `USER 10001` do?**
   Answer: Runs the container's process as a non-root user with that numeric id.

5. **What signal asks a container to stop?**
   Answer: `SIGTERM`, followed by `SIGKILL` after a timeout.

## Further reading

- Dockerfile reference: https://docs.docker.com/reference/dockerfile/
- Multi-stage builds: https://docs.docker.com/build/building/multi-stage/
- Docker Engine 24 is the version on the author's machine.

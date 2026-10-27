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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `.dockerignore`

19 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 19**

```text
.git
.venv
.env
.github
.mypy_cache
.pytest_cache
.ruff_cache
.import_linter_cache
.coverage
**/__pycache__
**/.terraform
**/terraform.tfstate*
**/*.tfvars
infra
tests
docs
scripts
data
logs
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** A **virtual environment** is a private folder holding a copy of the Python interpreter and the libraries installed for one project. It keeps the project's libraries separate from the rest of the machine, so two projects can use different versions of the same library.

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

**New idea.** Terraform's **state** is a file in which it records the real resources it created and their ids. Each run compares the code, the state and reality to decide what to change. It may contain sensitive values, so it is never committed; a *backend* is the place where the state is stored.

**New idea.** **Code coverage** measures which lines (and branches) of the program were run while the tests ran. A line the tests never reach is untested, so the project requires a high percentage for its core layers.

**New idea.** **git** is the version-control system that records every change to the project's files as a numbered commit, so any earlier state can be recovered and changes can be reviewed. Files listed in `.gitignore` are never recorded.

- `.git`: A `.dockerignore` file lists what Docker must leave out when it sends the project folder (the **build context**) to the image builder. Leaving things out makes the build faster and keeps secrets and caches out of the image. It uses the same pattern ideas as `.gitignore`. The git history (large, and the image does not need it).
- `.venv`: The local virtual environment.
- `.env`: Local settings that may hold secrets must never be copied into an image.
- `.github`: The CI workflow files.
- `.mypy_cache`: mypy's cache.
- `.pytest_cache`: pytest's cache.
- `.ruff_cache`: ruff's cache.
- `.import_linter_cache`: import-linter's cache.
- `.coverage`: Coverage data.
- `**/__pycache__`: Compiled Python files anywhere in the tree; `**` matches any number of folders.
- `**/.terraform`: Downloaded Terraform plug-ins anywhere in the tree.
- `**/terraform.tfstate*`: Terraform state files anywhere in the tree; they may contain secrets.
- `**/*.tfvars`: Terraform variable files anywhere in the tree; they hold personal ids.
- `infra`: The Terraform code is not needed inside the image.
- `tests`: The tests are not needed inside the image.
- `docs`: The documentation is not needed inside the image.
- `scripts`: The runbook scripts are not needed inside the image.
- `data`: Local database files.
- `logs`: Local log files.

#### `Dockerfile`

26 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 3**

```dockerfile
# Two stages: the first installs the hash-pinned dependencies and the package into a virtual environment, the second
# copies only that environment and the SQL scripts onto a clean base. The base is pinned by version and digest
# (read on 2026-10-26); update both together.
```

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

**New idea.** A **hash** (or *digest*) is a fixed-length fingerprint calculated from some data. The same data always gives the same hash and any change gives a different one, so comparing hashes shows whether a file or an image is exactly the one that was reviewed.

Comments. A **container image** is a packed, read-only file system plus a start command; a **Dockerfile** is the recipe that builds one, instruction by instruction. This recipe has two *stages*: the first installs the dependencies and the package into a virtual environment; the second copies only that environment (and the SQL scripts) onto a clean base, so the final image holds no build tools. The base image is pinned by version *and* by digest, a cryptographic fingerprint, so the same bytes are used every time; update both together.

**Line 4**

```dockerfile
FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6 AS build
```

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

`FROM image AS name` starts a stage from a base image. `python:3.13.12-slim-bookworm` is the official Python image, version 3.13.12, in its "slim" variant on Debian 12 ("bookworm"). `@sha256:...` pins the exact image by digest. `AS build` names this stage so a later stage can copy files from it.

**Line 5**

```dockerfile
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
```

`ENV` sets environment variables in the image. `PIP_DISABLE_PIP_VERSION_CHECK=1` stops pip from checking the internet for a newer pip, and `PIP_NO_CACHE_DIR=1` stops it from keeping a download cache, which would only make the layer bigger.

**Line 6**

```dockerfile
WORKDIR /build
```

`WORKDIR /build` sets the folder in which the following instructions run (and creates it).

**Line 7**

```dockerfile
RUN python -m venv /opt/venv
```

`RUN python -m venv /opt/venv` runs a command while building the image: it creates a **virtual environment** (a private Python with its own libraries) in `/opt/venv`. Only this folder will be copied to the final image.

**Line 8**

```dockerfile
COPY requirements.lock ./
```

**New idea.** A **lock file** records the exact versions (and often the hashes) of every package a project uses, including packages that those packages need. Installing from it gives the same result on every machine and on every day.

`COPY requirements.lock ./` copies the lock file from the build context (the project folder, minus what `.dockerignore` excludes) into the current folder of the image. It is copied before the source so that the dependency layer is reused from the cache when only the code changes.

**Line 9**

```dockerfile
RUN /opt/venv/bin/pip install --require-hashes -r requirements.lock
```

**New idea.** With **peek-lock**, a receiver takes a message but the broker only hides it under a *lock* for a limited time (30 seconds here). If the receiver *completes* the message it is deleted; if it *abandons* it or the lock expires, the message becomes visible again and is delivered once more, which is why processing must tolerate duplicates.

Installs the locked dependencies. `--require-hashes` makes pip accept only files whose hashes are written in the lock file, so the image contains exactly the reviewed packages.

**Line 10**

```dockerfile
COPY pyproject.toml README.md ./
```

`COPY pyproject.toml README.md ./` copies the package description and the readme that `pyproject.toml` refers to.

**Line 11**

```dockerfile
COPY src ./src
```

`COPY src ./src` copies the source code.

**Line 12**

```dockerfile
RUN /opt/venv/bin/pip install --no-deps .
```

Installs the project itself. `--no-deps` means pip installs only this package; its dependencies are already there from the lock file.

**Line 14**

```dockerfile
FROM python:3.13.12-slim-bookworm@sha256:a58daefb915e1e03ad48f3ca4df8832065412c5c35cacb9d39f4229184de12b6
```

The second stage starts. A new `FROM` begins a fresh image from the same pinned base; nothing of the first stage is present except what is copied explicitly.

**Lines 15 to 16**

```dockerfile
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    SQL_DIR=/app/sql LEDGER_PATH=/data/orders.db HEALTH_PORT=8080
```

**New idea.** A **port** is a number between 1 and 65535 that tells the computer which program on it should receive a network connection. An address such as `127.0.0.1:8000` means "this computer, port 8000"; `127.0.0.1` is the address a computer uses to talk to itself.

`ENV` sets: `PATH` with `/opt/venv/bin` in front, so the commands installed there (`order-worker`) are found; `PYTHONUNBUFFERED=1`, which makes Python write output at once so logs appear immediately; `PYTHONDONTWRITEBYTECODE=1`, which stops it writing compiled `.pyc` files into the image; and the program's own settings: `SQL_DIR` (where the SQL scripts are), `LEDGER_PATH` (the database file, under the volume) and `HEALTH_PORT` (the port of the health endpoint). The trailing backslash continues the instruction on the next line.

**Lines 17 to 18**

```dockerfile
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin worker \
    && mkdir /data && chown 10001 /data
```

Creates the user the worker runs as. `useradd --system` makes a system account, `--uid 10001` fixes its number, `--no-create-home` gives it no home folder and `--shell /usr/sbin/nologin` forbids signing in as it. Then (`&&` runs the next command only if the first succeeded) it creates the folder `/data` and hands it to that user, so the worker can write its database there. Running as a normal user instead of `root` limits what a bug or an attacker could do inside the container.

**Line 19**

```dockerfile
COPY --from=build /opt/venv /opt/venv
```

`COPY --from=build /opt/venv /opt/venv` copies the finished virtual environment out of the first stage.

**Line 20**

```dockerfile
COPY sql /app/sql
```

Copies the SQL scripts to `/app/sql`, where `SQL_DIR` points.

**Line 21**

```dockerfile
USER 10001
```

`USER 10001` makes the following instructions, and the running container, use that account.

**Line 22**

```dockerfile
VOLUME /data
```

`VOLUME /data` declares that `/data` is meant to be mounted storage; data written there survives container restarts when a volume is attached.

**Line 23**

```dockerfile
EXPOSE 8080
```

`EXPOSE 8080` documents the port the container listens on (the health endpoint). It does not publish the port by itself.

**Lines 24 to 25**

```dockerfile
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/live', timeout=2)"]
```

**New idea.** **HTTP** is the protocol of the web. A client sends a *request* (a method such as GET or POST, a path, headers and sometimes a body) and the server sends back a *response* with a three-digit **status code**: 200 means success, 201 created, 400 the request was bad, 403 forbidden, 404 not found, 413 too large, 502 a server behind this one failed.

**New idea.** A **URL** is the full address of something on the web, such as `https://example.com:8443/path?x=1`: the protocol, the host name, an optional port, the path and an optional query.

**New idea.** An **IP address** such as `10.10.2.4` identifies a computer on a network. A **CIDR range** such as `10.10.2.0/24` names a block of addresses: the number after the slash says how many leading bits are fixed, so `/24` fixes the first three numbers and leaves 256 addresses. Ranges starting `10.`, `172.16.` to `172.31.` and `192.168.` are *private*: they are not reachable from the public internet.

**New idea.** A **timeout** is the longest a program waits for something before giving up. Without one, a call to a service that never answers would make the program wait forever.

**New idea.** A **retry** repeats an operation that failed, usually after a pause. It helps with failures that go away by themselves, such as a new permission that takes a few minutes to spread; it must be limited, so a permanent failure is reported and not repeated forever.

**New idea.** A **health check** is a small request that a platform sends to a running program to ask whether it is working. A *liveness* check that keeps failing makes the platform restart the program; a *readiness* check that fails keeps traffic away from it.

`HEALTHCHECK` tells Docker how to test that the container is healthy. Every 30 seconds (`--interval`) it runs the command; the command may take at most 3 seconds (`--timeout`); failures in the first 15 seconds are ignored (`--start-period`); three failures in a row (`--retries`) mark the container unhealthy. The command is a one-line Python program that requests `http://127.0.0.1:8080/live` and fails if the request fails. The square-bracket form runs the program directly, not through a shell.

**Line 26**

```dockerfile
# SIGTERM finishes the message in hand, settles it, closes the receiver and exits 0.
```

**New idea.** A **signal** is a short message the operating system sends to a process. `SIGTERM` asks it to stop politely (a program should finish its current work and exit), `SIGINT` is what Ctrl+C sends, and `SIGKILL` cannot be caught. Container platforms send `SIGTERM` when they stop a container.

A comment: on SIGTERM (the signal that asks a program to stop) the worker finishes the message in hand, settles it, closes the receiver and exits with code 0.

**Line 27**

```dockerfile
CMD ["order-worker"]
```

`CMD ["order-worker"]` is the command the container runs when it starts: the worker program installed in the virtual environment.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `scripts/docker-smoke.sh` | 4, 7 to 11, 15 to 16, 19 | [bash.md](bash.md) |
| `Makefile` | 16, 110, 115 to 119 | [make.md](make.md) |
| `scripts/build-and-deploy.sh` | 4, 16, 19 to 20 | [bash.md](bash.md) |
| `.checkov.yaml` | 1, 8 | [checkov.md](checkov.md) |
| `.github/workflows/ci.yml` | 32, 47 | [github-actions.md](github-actions.md) |

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

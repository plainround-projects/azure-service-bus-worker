# Bash

*The scripts under `scripts/` that run the lesson against Azure. Pinned here: Bash 3.2 and newer (macOS ships 3.2).*

## What it is

Bash is a **shell**: a program that reads commands you type (or that are written in a file) and runs them. A file of commands is a **shell script**. Scripts are the glue between tools: they call `terraform`, `az` and `curl` in the right order and stop if one fails.

## Why this repository uses it

The lesson's steps are commands you type in order. The scripts are those commands written down once, with the retries and checks a person forgets.

## Where it appears

| File | What it does with it |
|---|---|
| `scripts/lib.sh` | Shared helpers. |
| `scripts/provision.sh` | Registers providers, writes variables, applies Terraform. |
| `scripts/env.sh` | Prints `export` lines from the Terraform outputs. |
| `scripts/show-queues.sh` | Prints queue properties and message counts. |
| `scripts/build-and-deploy.sh` | Builds the worker image and adds the container app. |
| `scripts/run-workers.sh` | Runs several workers in parallel on the session queue. |
| `scripts/teardown.sh` | Destroys everything. |
| `scripts/docker-smoke.sh` | Checks the image without Azure. |

## How it works underneath

A command line is split into words. The first word is the program, the rest are **arguments**. The shell starts the program as a new process and waits. When the process ends it leaves an **exit code**: `0` means success, anything else means failure. `&&` runs the next command only if the last one succeeded; `||` only if it failed; `|` (a **pipe**) sends the output of one command to the input of the next.

A **variable** is set with `NAME=value` and read with `$NAME`. Always put it in double quotes (`"$NAME"`) so spaces in the value do not split it into several words. `$(command)` runs a command and substitutes its output. `source file` runs another script's lines in the current shell, so its functions and variables become available.

`set -euo pipefail` makes a script strict: `-e` stops at the first failing command, `-u` treats an unset variable as an error, `-o pipefail` makes a pipe fail if any command in it fails. `trap 'command' EXIT` runs a command when the script ends, even after an error, which is how temporary files get cleaned up.

macOS ships Bash 3.2. Scripts here avoid newer features (such as negative array indexes and `${var^^}`) so they run there.

## Walkthrough of this repository's use

### The shared helpers

```bash
#!/usr/bin/env bash
# Shared helpers for the runbook scripts. Source it; do not run it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra/environments/dev"
APP_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
export APP_VERSION
```

The shebang line chooses Bash. `set -euo pipefail` makes the script strict (stop at the first error, treat unset variables as errors, fail a pipe if any part fails). `ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"` finds the repository root from the script's own path. The `sed -n 's/^version = "\(.*\)"/\1/p'` command prints the project version from `pyproject.toml`.

```bash
retry() {
  local attempts=$1 pause=$2 attempt=1
  shift 2
  until "$@"; do
    if ((attempt >= attempts)); then return 1; fi
    log "attempt $attempt of $attempts failed; waiting ${pause}s for the role assignment to take effect"
    sleep "$pause"
    attempt=$((attempt + 1))
  done
}
```

`retry 12 30 command...` runs the command up to 12 times with 30 seconds between attempts; `local` keeps variables private to the function; `shift 2` removes the two numbers from `"$@"`. It is used because role assignments take minutes to take effect.

### env.sh: exporting settings for local runs

```bash
need terraform

echo "export SB_NAMESPACE=$(tf_out servicebus_namespace)"
echo "export LEDGER_PATH=$ROOT/data/orders.db"
# AZURE_CLIENT_ID is deliberately not exported: on a laptop the programs use your az login session.
```

`echo "export SB_NAMESPACE=$(tf_out servicebus_namespace)"` prints a line that you `eval` in your shell (`eval "$(scripts/env.sh)"`), which sets the variable for later commands. The comment explains the deliberate absence of `AZURE_CLIENT_ID`: on a laptop the programs use your own login.

### show-queues.sh

```bash
for queue in orders orders-sessions; do
  log "queue $queue"
  az servicebus queue show --resource-group "$RG" --namespace-name "$NAMESPACE" --name "$queue" \
    --query '{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount, requiresSession:requiresSession, active:countDetails.activeMessageCount, deadLetter:countDetails.deadLetterMessageCount}' \
    --output table
done
```

Loops over the two queues and shows their lock duration, maximum delivery count, whether they require sessions, and the counts of active and dead-lettered messages. `--query '{lockDuration:lockDuration, ...}'` builds a small JSON object (JMESPath) and `--output table` prints it as a table.

### run-workers.sh: processes in parallel

```bash
pids=()
cleanup() { kill -TERM "${pids[@]}" 2>/dev/null || true; }
trap cleanup INT TERM

for n in $(seq 1 "$COUNT"); do
  "$ROOT/.venv/bin/order-worker" --until-idle "$IDLE" >"$ROOT/logs/worker-$n.log" 2>&1 &
  pids+=("$!")
  log "worker $n started (pid $!), log: logs/worker-$n.log"
done

status=0
for pid in "${pids[@]}"; do wait "$pid" || status=$?; done
```

`pids=()` is an array. `cleanup() { kill -TERM "${pids[@]}" ...}` sends the polite stop signal to every worker; `trap cleanup INT TERM` runs it on Ctrl+C. Each worker starts with `&` (in the background), its output goes to `logs/worker-N.log`, and `$!` is the process id of the last background command. `wait "$pid"` waits for one to finish and `|| status=$?` records a failure without stopping the loop.

### docker-smoke.sh

```bash
user_id="$(docker run --rm --entrypoint id "$IMAGE" -u)"
[[ "$user_id" != "0" ]] || die "the container runs as root"
log "container user id: $user_id"

docker run --rm --entrypoint order-simulate "$IMAGE" --expect dirty duplicates --mode naive | tail -3
docker run --rm --entrypoint order-simulate "$IMAGE" --expect clean poison | tail -3

set +e
output="$(docker run --rm "$IMAGE" 2>&1)"
code=$?
set -e
[[ "$code" == "2" ]] || die "expected exit code 2 without configuration, got $code"
```

`docker run --rm --entrypoint id "$IMAGE" -u` runs one command in a throwaway container to print the numeric user id; the script fails if it is 0 (root). It then runs the offline simulation inside the image and finally runs the worker with no configuration to check that it exits with code 2 and names `SB_NAMESPACE`.

## Try it yourself

Ask Bash to parse a script without running it.

```bash
bash -n scripts/lib.sh && echo 'syntax ok'
```

You should see something like this:

```text
syntax ok
```

Check the system Bash (3.2) can parse a script.

```bash
/bin/bash -n scripts/run-workers.sh && echo 'syntax ok on the Bash that macOS ships'
```

You should see something like this:

```text
syntax ok on the Bash that macOS ships
```

Use the helpers.

```bash
bash -c 'source scripts/lib.sh; log hello; need bash && echo found; need no-such-tool; echo "exit: $?"'
```

You should see something like this:

```text
11:46:22 hello
found
error: no-such-tool is not installed
```

Watch `retry` call a flaky command until it works.

```bash
bash -c 'source scripts/lib.sh; n=0; flaky() { n=$((n+1)); [ $n -ge 3 ]; }; retry 5 0 flaky && echo "succeeded after $n tries"'
```

You should see something like this:

```text
11:46:22 attempt 1 of 5 failed; waiting 0s for the role assignment to take effect
11:46:23 attempt 2 of 5 failed; waiting 0s for the role assignment to take effect
succeeded after 3 tries
```

## Mistakes people make

- Leaving variables unquoted. A path with a space becomes two words.
- Forgetting `set -euo pipefail`, so a failed step is ignored and the script carries on.
- Parsing `ls` output. Use globs (`for f in dir/*.sh`).
- Using Bash 4 features on a Mac with Bash 3.2. Here `shellcheck` and `/bin/bash -n` are run to catch that.
- Putting a secret in a command line, where other users can see it with `ps`. Scripts here read secrets from the environment and never print them.

## Check yourself

1. **What does an exit code of 0 mean?**
   Answer: The command succeeded.

2. **What does `set -euo pipefail` do?**
   Answer: Stops on the first error, treats unset variables as errors, and makes a pipe fail if any part fails.

3. **Why quote `"$VAR"`?**
   Answer: So spaces in the value do not split it into several arguments.

4. **What does `$(...)` do?**
   Answer: Runs the command inside and replaces itself with its output.

5. **What does `trap '...' EXIT` do?**
   Answer: Runs the given command when the script ends, success or failure.

## Further reading

- Bash reference manual (the shell scripts are written for Bash 3.2 and newer): https://www.gnu.org/software/bash/manual/bash.html
- Shell parameter expansion: https://www.gnu.org/software/bash/manual/html_node/Shell-Parameter-Expansion.html

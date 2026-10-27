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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `scripts/build-and-deploy.sh`

27 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```bash
#!/usr/bin/env bash
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** A **terminal** is a window in which you type commands and read the answers. The program that reads what you type is the **shell**; this project uses **bash**, the most common one. A command is a program name followed by arguments separated by spaces, such as `ls -l docs`; options usually start with `-` or `--`.

**New idea.** A **shell script** is a text file of commands that bash runs from top to bottom, as if you had typed them one after another. Putting them in a file makes a routine repeatable and reviewable.

**New idea.** The first line `#!/usr/bin/env bash` is called a **shebang**. When the file is run directly, the operating system reads this line to learn which program should interpret the file: `env bash` finds `bash` wherever it is installed on this machine.



**Lines 2 to 5**

```bash
# Phase 2 (the managed-identity path): build the worker image inside the registry, then add the container app.
#   scripts/build-and-deploy.sh                    az acr build (ACR Tasks)
#   BUILD_MODE=local scripts/build-and-deploy.sh   docker build and push, for subscriptions where ACR Tasks is not allowed
#   TF_VAR_worker_queue=orders-sessions TF_VAR_worker_use_sessions=true scripts/build-and-deploy.sh   (the session queue)
```

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

**New idea.** A **container registry** is a server that stores container images under names and version tags. **Azure Container Registry (ACR)** is Azure's; a service pulls an image from it using an identity that holds the `AcrPull` role.

**New idea.** An Azure **subscription** is the billing container for resources: everything created in it is charged to it, and its settings and access control apply to it. A *tenant* (the organization's identity directory) can hold several subscriptions.

**New idea.** In a shell script a `#` starts a **comment**: everything to the end of the line is ignored by bash and is there for the reader.

**New idea.** An **environment variable** is a variable that is passed on to every program the script starts. `export NAME` marks a variable that way. Programs use them as settings, for example to find a namespace name or a port.

A comment block explaining phase 2, which uses the managed-identity path: build the worker image inside the registry, then add the container app. Three usages are listed: the default `az acr build` (the registry builds the image, a feature called ACR Tasks); `BUILD_MODE=local` to build with Docker on this machine and push, for subscriptions where ACR Tasks is not allowed; and variables named `TF_VAR_...` that set Terraform input variables (any environment variable named `TF_VAR_<name>` becomes the Terraform variable `<name>`) to deploy the session queue.

**Line 6**

```bash
set -euo pipefail
```

**New idea.** `set` changes how bash behaves for the rest of the script. `-e` stops the script at the first command that fails (a command *fails* when it ends with a non-zero **exit status**; zero means success). `-u` makes using a variable that was never set an error instead of silently giving an empty text. `-o pipefail` makes a pipeline (commands joined with `|`) fail if *any* of its commands fails, not only the last. Together they turn silent mistakes into immediate, visible stops.

**New idea.** Every command ends with a number, its **exit status**: `0` means it worked and anything else means it failed. `$?` holds the status of the last command. `&&` runs the next command only if the previous one succeeded, `||` only if it failed.



**Line 7**

```bash
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
```

**New idea.** A **retry** repeats an operation that failed, usually after a pause. It helps with failures that go away by themselves, such as a new permission that takes a few minutes to spread; it must be limited, so a permanent failure is reported and not repeated forever.

**New idea.** `source file` (or `. file`) runs the commands of another script *inside the current script*, so the functions and variables it defines become available here. It is used for shared helper code; a script that is run normally would start a separate process and its definitions would be lost.

**New idea.** `${BASH_SOURCE[0]}` is the path of the script file being run (or sourced) right now. `dirname` cuts off the file name and leaves the folder, so `$(dirname "${BASH_SOURCE[0]}")` is the folder the script lives in, and the script finds its neighbors no matter where it is started from.

`source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"` loads the shared helpers (`log`, `die`, `need`, `require_login`, `tf_out`, `retry`, and the variables `ROOT` and `TF_DIR`) from `lib.sh`, which sits in the same folder as this script.

**Lines 8 to 9**

```bash
need az terraform
require_login
```

Requires `az` and `terraform` to be installed and an Azure sign-in.

**Lines 11 to 13**

```bash
REGISTRY="$(tf_out registry_name)"
LOGIN_SERVER="$(tf_out registry_login_server)"
IMAGE="$LOGIN_SERVER/azure-service-bus-worker:$APP_VERSION"
```

**New idea.** **Tags** are name/value labels attached to Azure resources. They change no behavior; they record the owner, project and environment and make cost reports and clean-up possible.

**New idea.** `$(command)` is **command substitution**: bash runs the command and puts its output in place of the `$(...)`. For example `"$(date)"` becomes the current date as text.

**New idea.** A **Terraform output** is a named value the code publishes after `apply`, such as a resource name. The scripts read them with `terraform output -raw NAME` instead of repeating names by hand.

Three variables. `REGISTRY` is the registry's name and `LOGIN_SERVER` its host name, both read from Terraform outputs. `IMAGE` is the full image name: `<login server>/azure-service-bus-worker:<version>`, using `APP_VERSION` from `lib.sh` as the tag.

**Line 15**

```bash
if [[ "${BUILD_MODE:-acr}" == "local" ]]; then
```

**New idea.** `[[ condition ]]` tests a condition and succeeds or fails like a command. Common tests: `-f path` (a regular file exists), `-n text` (the text is not empty), `-z text` (the text is empty), `a == b` and `a != b` (text equality). `!` negates a test.

**New idea.** `if command; then ... elif ...; else ...; fi` runs the first block whose condition command succeeds. The word `fi` (`if` reversed) ends it.

**New idea.** `${NAME:-default}` is the value of the variable, or `default` if it is unset or empty. `${NAME:?message}` stops the script with the message if it is unset or empty. `${1:-}` reads the first argument or an empty text, which also avoids an error under `set -u`.

Starts the local-build branch when `BUILD_MODE` is `local`; `${BUILD_MODE:-acr}` means "the variable, or `acr` if it is not set".

**Lines 16 to 20**

```bash
  need docker
  log "building $IMAGE locally and pushing it"
  az acr login --name "$REGISTRY"
  docker build --platform linux/amd64 --tag "$IMAGE" "$ROOT"
  docker push "$IMAGE"
```

**New idea.** **`docker`** is the command-line program for containers. `docker build` builds an image from a Dockerfile, `docker run` starts a container from an image (`--rm` deletes the container afterwards, `--entrypoint` replaces its start command), and `docker push` uploads an image to a registry.

The local branch: `need docker` requires Docker, `az acr login --name "$REGISTRY"` signs Docker in to the registry using the Azure identity, `docker build --platform linux/amd64 --tag "$IMAGE" "$ROOT"` builds the image for the 64-bit Intel/AMD architecture that Azure runs (important on a Mac with an Arm processor) from the repository folder, and `docker push "$IMAGE"` uploads it to the registry.

**Lines 21 to 24**

```bash
else
  log "building $IMAGE in $REGISTRY"
  az acr build --registry "$REGISTRY" --image "azure-service-bus-worker:$APP_VERSION" "$ROOT"
fi
```

The default branch (`else`): `az acr build --registry "$REGISTRY" --image "azure-service-bus-worker:$APP_VERSION" "$ROOT"` sends the folder to the registry, which builds the image there and stores it. `fi` ends the `if`.

**Line 26**

```bash
terraform -chdir="$TF_DIR" apply -input=false -auto-approve -var "deploy_worker=true" -var "image=$IMAGE"
```

**New idea.** **`terraform`** is the command-line program of Terraform. `terraform -chdir=DIR <command>` runs the command in another folder; `init` downloads the plug-ins; `apply` creates or changes real resources to match the code; `destroy` deletes them; `output -raw NAME` prints one output value with no quotes. `-input=false` means "never stop to ask a question", and `-auto-approve` skips the confirmation question before changes.

Runs Terraform's `apply` with `-var "deploy_worker=true"` and `-var "image=$IMAGE"`, which set two input variables for this run. Phase 1 left `deploy_worker` false; now the container app is added, running the image just built.

**Lines 28 to 31**

```bash
APP="$(tf_out worker_app_name)"
RG="$(tf_out resource_group_name)"
log "worker deployed. Logs: az containerapp logs show --resource-group $RG --name $APP --follow"
log "Ledger check inside the replica: az containerapp exec --resource-group $RG --name $APP --command 'order-check'"
```

**New idea.** An Azure **resource group** is a folder-like container for the resources of one project. Resources in a group share a life cycle: deleting the group deletes everything in it.

Reads the app name and the resource group from Terraform outputs and prints two ready-to-use commands: how to follow the worker's logs (`az containerapp logs show ... --follow`) and how to run the ledger check inside a running replica (`az containerapp exec ... --command 'order-check'`).

#### `scripts/docker-smoke.sh`

20 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```bash
#!/usr/bin/env bash
```



**Lines 2 to 4**

```bash
# Check the image without Azure: it runs as a non-root user, the simulation (which needs the packaged sql/ scripts)
# reproduces the lesson's failures, and the worker refuses to start without a namespace.
#   scripts/docker-smoke.sh <image>
```

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

A comment block. The script checks the built image without needing Azure: it runs as a non-root user, the simulation (which needs the SQL scripts packaged inside the image) reproduces the lesson's failures, and the worker refuses to start without a namespace. Usage: `scripts/docker-smoke.sh <image>`.

**Lines 5 to 7**

```bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need docker
```

`source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"` loads the shared helpers (`log`, `die`, `need`, `require_login`, `tf_out`, `retry`, and the variables `ROOT` and `TF_DIR`) from `lib.sh`, which sits in the same folder as this script.
`need docker` requires the Docker program.

**Line 9**

```bash
IMAGE="${1:?usage: docker-smoke.sh <image>}"
```

`IMAGE="${1:?usage: docker-smoke.sh <image>}"` takes the first argument as the image name. The `:?` form stops the script with the usage message if no argument was given.

**Lines 11 to 13**

```bash
user_id="$(docker run --rm --entrypoint id "$IMAGE" -u)"
[[ "$user_id" != "0" ]] || die "the container runs as root"
log "container user id: $user_id"
```

`docker run --rm --entrypoint id "$IMAGE" -u` starts a container from the image, replacing its normal start command with `id` and passing `-u`, which prints the numeric user id the process runs as; `--rm` deletes the container afterwards. The next line fails the script (`die`) if the id is `0`, which is `root`, the all-powerful account. The third line logs the id.

**Lines 15 to 16**

```bash
docker run --rm --entrypoint order-simulate "$IMAGE" --expect dirty duplicates --mode naive | tail -3
docker run --rm --entrypoint order-simulate "$IMAGE" --expect clean poison | tail -3
```

**New idea.** A **fake** (or *test double*) is a simple stand-in object used in tests in place of a real service. It behaves like the real one in the ways the test needs, with no network, no account and no cost.

**New idea.** A **pipe** `a | b` connects the output of command `a` to the input of command `b`, so `b` processes what `a` printed.

Runs the image's `order-simulate` program twice, for two scenarios, and `| tail -3` shows only the last three lines of each output. `--expect dirty` means the command succeeds only if the simulated duplicates actually appear; `--expect clean` only if the ledger ends up exactly right.

**Lines 18 to 22**

```bash
set +e
output="$(docker run --rm "$IMAGE" 2>&1)"
code=$?
set -e
[[ "$code" == "2" ]] || die "expected exit code 2 without configuration, got $code"
```

**New idea.** Every program has **standard output** (its normal results) and **standard error** (its problem reports), two separate streams. Keeping them apart lets a caller capture the results while still seeing the errors.

`set +e` switches off "stop at the first failure", because the next command is expected to fail. `output="$(docker run --rm "$IMAGE" 2>&1)"` starts the image with its normal command and no configuration, capturing everything it prints (both streams: `2>&1`). `code=$?` saves its exit status. `set -e` switches the stop-on-failure rule back on. Then the script requires that the status was exactly `2`, the code the worker uses for a configuration error.

**Line 23**

```bash
grep -q "SB_NAMESPACE" <<<"$output" || die "the configuration error does not name SB_NAMESPACE: $output"
```

**New idea.** `grep pattern` prints the lines that contain the pattern; `-q` prints nothing and only sets the exit status; `-c` prints how many lines matched; `-E` allows extended regular expressions.

`grep -q "SB_NAMESPACE" <<<"$output"` searches the captured text for the name of the missing setting (`<<<` feeds a variable's text as the command's input; `-q` prints nothing and only sets the status). It checks that the error message names the setting the user must supply.

**Line 24**

```bash
log "OK: non-root, packaged SQL works, and the worker fails fast on missing configuration"
```

Logs the success message.

#### `scripts/env.sh`

8 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```bash
#!/usr/bin/env bash
```

The first line of the file.

**Line 2**

```bash
# Print the settings the local programs need, from the Terraform outputs. Use: eval "$(scripts/env.sh)"
```

The comment says what the script does: it **prints** the settings the local programs need, taken from the Terraform outputs, and shows how to use it: `eval "$(scripts/env.sh)"`. `eval` runs the text it is given as commands, in the current shell, so the `export` lines this script prints take effect in your terminal; a script run normally could not change the environment of the shell that started it.

**Line 3**

```bash
set -euo pipefail
```



**Line 4**

```bash
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
```

`source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"` loads the shared helpers (`log`, `die`, `need`, `require_login`, `tf_out`, `retry`, and the variables `ROOT` and `TF_DIR`) from `lib.sh`, which sits in the same folder as this script.

**Line 5**

```bash
need terraform
```

`need terraform` stops the script with a clear message if the `terraform` program is not installed (the `need` helper is defined in `lib.sh`).

**Line 7**

```bash
echo "export SB_NAMESPACE=$(tf_out servicebus_namespace)"
```

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

`echo` prints its text. The text is `export SB_NAMESPACE=<value>`, where the value is filled in by `$(tf_out servicebus_namespace)`: the helper `tf_out` reads the Terraform output `servicebus_namespace` (the host name of the namespace). `SB_NAMESPACE` is the environment variable the worker and the producer read to know which namespace to talk to. The script only prints the command; the `eval` in the caller runs it.

**Line 8**

```bash
echo "export LEDGER_PATH=$ROOT/data/orders.db"
```

Prints `export LEDGER_PATH=<repository>/data/orders.db`, the file the local programs keep their ledger in. `$ROOT` is the repository root from `lib.sh`.

**Line 9**

```bash
# AZURE_CLIENT_ID is deliberately not exported: on a laptop the programs use your az login session.
```

**New idea.** A **managed identity** is an identity that Azure creates and looks after for a workload, with no password to store or rotate. When the workload runs, it asks a local Azure endpoint for a token for that identity. A *user-assigned* identity exists on its own and can be attached to several resources; its *client id* names it when a program asks for a token and its *principal id* names it when roles are granted.

A comment explaining a deliberate omission: `AZURE_CLIENT_ID` is not exported, because on a laptop the programs use your own `az login` session. In Azure the container app sets it so that the right managed identity is used.

#### `scripts/lib.sh`

31 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```bash
#!/usr/bin/env bash
```

This script is a **library**: it defines helpers and is not meant to be run on its own.

**Line 2**

```bash
# Shared helpers for the runbook scripts. Source it; do not run it.
```

The comment says what the file is for: shared helpers for the runbook scripts. It is `source`d by them, not run.

**Line 3**

```bash
set -euo pipefail
```



**Line 5**

```bash
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
```

**New idea.** A **variable** is a named piece of text: `NAME=value` sets it (no spaces around `=`) and `$NAME` or `${NAME}` reads it. Always write the read in double quotes, `"$NAME"`, so that spaces in the value are not treated as separators between arguments.

Reading the line from the inside out: `dirname "${BASH_SOURCE[0]}"` is the folder of this file (`scripts/`); adding `/..` means "one folder up", the repository root; `cd <there> && pwd` goes to that folder and prints its full path (`pwd`, "print working directory"), and the outer `$(...)` captures that text into the variable `ROOT`. Every script can then find files relative to the repository root, whatever folder it was started from.

**Line 6**

```bash
TF_DIR="$ROOT/infra/environments/dev"
```

`TF_DIR` is the Terraform environment folder, built from `ROOT`. Scripts use it with `terraform -chdir=` to run Terraform commands there without changing folder.

**Line 7**

```bash
APP_VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$ROOT/pyproject.toml" | head -1)"
```

**New idea.** `sed` edits text as it flows through. `sed -n 's/pattern/replacement/p'` prints (`p`) only the lines where the substitution `s` matched, after replacing the matched part; `\(...\)` marks a group that `\1` in the replacement puts back.

This line reads the project's version out of `pyproject.toml`. `sed -n 's/^version = "\(.*\)"/\1/p'` looks for the line that starts with `version = "`, keeps only the text between the quotes, and prints just that line; `| head -1` keeps the first match only. The version is used as the image tag, so the tag always equals the package version.

**Line 8**

```bash
export APP_VERSION
```

`export APP_VERSION` makes the variable visible to programs the scripts start.

**Line 10**

```bash
log() { printf '%s %s\n' "$(date -u +%H:%M:%S)" "$*"; }
```

**New idea.** `name() { ... }` defines a **function**: a named group of commands that is run by writing its name like a command. Inside, `$1`, `$2`, ... are the arguments it was called with, `"$@"` is all of them as separate words, and `"$*"` is all of them joined into one text. `return N` leaves the function with status N.

**New idea.** `printf 'format' args` prints text. In the format, `%s` is replaced by the next argument as text and `\n` is a new line; unlike `echo`, `printf` behaves the same on every system.

`log` prints a message with a time stamp in front. `"$(date -u +%H:%M:%S)"` is the current time in UTC; `"$*"` is all the arguments joined into one text. It is used for progress lines such as `12:01:07 registering Microsoft.App`.

**Line 11**

```bash
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
```

**New idea.** A program has two output streams: **standard output** (the normal result) and **standard error** (messages about problems). `>&2` sends a command's output to standard error, so that error messages do not get mixed into the result a caller might capture.

`die` prints `error: <message>` on standard error and then ends the script with status 1 (`exit 1`). Every failed check in the scripts calls it, which gives one uniform error format.

**Lines 13 to 17**

```bash
need() {
  for tool in "$@"; do
    command -v "$tool" >/dev/null || die "$tool is not installed"
  done
}
```

**New idea.** An Azure **region** (such as `westeurope`) is a group of data centers in one geographic area. Where a resource is created decides its latency, its price and which legal rules apply.

**New idea.** `command -v name` prints where the program `name` is installed and succeeds if it exists, fails if it does not. It is the portable way to test whether a tool is available.

**New idea.** `for name in list; do ...; done` runs the commands between `do` and `done` once for each word of the list, with the variable `name` set to that word.

`need` checks that tools are installed. `for tool in "$@"; do ... done` repeats the line for each argument (`"$@"` is every argument as a separate word). `>/dev/null` hides the printed location, and `|| die "... is not installed"` stops the script with a clear message when the tool is missing. Usage: `need az terraform`.

**Lines 19 to 22**

```bash
require_login() {
  need az
  az account show >/dev/null 2>&1 || die "not signed in: run 'az login' first"
}
```

**New idea.** **Redirection** changes where a command reads from or writes to: `> file` writes its output into a file (replacing it), `>> file` appends, `< file` reads input from a file, `2>&1` sends the error stream to the same place as the normal output, and `>/dev/null` throws the output away (`/dev/null` is a special file that discards everything written to it).

`require_login` checks that the Azure command-line program is installed (`need az`) and that someone is signed in. `az account show` prints the signed-in account and fails when nobody is; `>/dev/null 2>&1` throws away both normal output and error output, because only the success or failure matters here. The message tells the user the fix: `az login`.

**Lines 24 to 25**

```bash
# tf_out <name>: one raw output of the dev environment.
tf_out() { terraform -chdir="$TF_DIR" output -raw "$1"; }
```

A comment line documents the function, then `tf_out` prints one Terraform output of the dev environment. `terraform -chdir="$TF_DIR" output -raw "$1"` runs `terraform output` in the environment folder; `-raw` prints the value without quotes, and `$1` is the name passed to the function (for example `tf_out registry_name`).

**Lines 27 to 37**

```bash
# retry <attempts> <sleep seconds> <command...>: role assignments take minutes to apply, so data-plane calls retry.
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

**New idea.** **Azure role-based access control (RBAC)** decides who may do what. A *role* is a named bundle of permissions (for example "Key Vault Secrets User" may read secrets), a *scope* is where the grant applies (one resource, a resource group, a whole subscription), and a *role assignment* connects an identity, a role and a scope. The smaller the scope, the less a leaked identity can do.

**New idea.** `local name=value` declares a variable that exists only inside the function, so it cannot clash with a variable of the same name elsewhere.

**New idea.** `until command; do ...; done` repeats the block until the command succeeds. `while` is the same with the test reversed.

**New idea.** `$(( expression ))` calculates with whole numbers and gives the result as text; `(( expression ))` as a command succeeds when the expression is not zero, so `((attempt >= attempts))` is a comparison.

**New idea.** `sleep N` pauses the script for N seconds.

`retry <attempts> <seconds> <command...>` runs a command until it succeeds, up to a maximum. It exists because a new Azure role assignment can take several minutes to take effect, so the first data calls may be refused with a permission error that disappears by itself.

- `local attempts=$1 pause=$2 attempt=1` sets three variables: the maximum number of attempts (first argument), the pause (second argument) and the attempt counter, starting at 1. 
- `shift 2` removes the first two arguments from the list, so that `"$@"` is now only the command to run.
- `until "$@"; do ... done` runs the command and repeats the block as long as it fails. 
- `if ((attempt >= attempts)); then return 1; fi` gives up (leaves the function with status 1) when the last attempt has failed. 
- `log "attempt ... failed; waiting ${pause}s ..."` tells the user what is happening.
- `sleep "$pause"` waits.
- `attempt=$((attempt + 1))` adds one to the counter.

#### `scripts/provision.sh`

34 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```bash
#!/usr/bin/env bash
```



**Lines 2 to 5**

```bash
# Phase 1: resource group, workspace, identities, Service Bus namespace and queues, registry, role assignments, alert,
# budget. The worker's container app comes in phase 2 (build-and-deploy.sh) because its image must exist first.
#
#   ALERT_EMAIL=you@example.com scripts/provision.sh [--yes]
```

**New idea.** An Azure **budget** watches the spending of a subscription and e-mails people when it passes a threshold such as 80 or 100 percent. It alerts; it does not stop anything from running.

A comment block. It names the first of two phases: phase 1 creates the resource group, workspace, identities, Service Bus namespace and queues, registry, role assignments, alert and budget. The worker's container app comes in phase 2 (`build-and-deploy.sh`), because its image must exist before the app can start. The last comment line shows the command: `ALERT_EMAIL=you@example.com scripts/provision.sh [--yes]`. A variable written before the command, `NAME=value command`, is set only for that one command. `[--yes]` in square brackets means the argument is optional.

**Line 6**

```bash
set -euo pipefail
```



**Line 7**

```bash
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
```

`source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"` loads the shared helpers (`log`, `die`, `need`, `require_login`, `tf_out`, `retry`, and the variables `ROOT` and `TF_DIR`) from `lib.sh`, which sits in the same folder as this script.

**Lines 8 to 9**

```bash
need az terraform
require_login
```

`need az terraform` stops with a message if either program is missing, and `require_login` stops if nobody is signed in to Azure (both are helpers from `lib.sh`).

**Lines 11 to 12**

```bash
AUTO_APPROVE=""
[[ "${1:-}" == "--yes" ]] && AUTO_APPROVE="-auto-approve"
```

`AUTO_APPROVE=""` creates the variable with an empty value. The next line is a test followed by `&&`: `[[ "${1:-}" == "--yes" ]]` is true when the first argument of the script is exactly `--yes` (`${1:-}` reads the first argument or an empty text, which is safe under `set -u`), and only then does `AUTO_APPROVE="-auto-approve"` run. So the variable holds either nothing or the Terraform option that skips the confirmation question.

**Lines 14 to 19**

```bash
# Register the resource providers once, so the Terraform plan never changes subscription-wide settings itself.
for provider in Microsoft.App Microsoft.ContainerRegistry Microsoft.Consumption Microsoft.Insights \
  Microsoft.ManagedIdentity Microsoft.OperationalInsights Microsoft.ServiceBus; do
  log "registering $provider"
  az provider register --namespace "$provider" --wait >/dev/null
done
```

A comment says why this block exists: the Azure **resource providers** are registered once, here, so that the Terraform plan never changes subscription-wide settings by itself. A resource provider is the part of Azure that owns one kind of resource (for example `Microsoft.ServiceBus`); a subscription must have it registered before resources of that kind can be created.

The `for provider in ...; do ... done` loop takes each of the seven provider names in turn (the backslash at the end of the first line continues the list on the next line). For each one `log` prints what is happening, and `az provider register --namespace "$provider" --wait` registers it and waits until Azure has finished; `>/dev/null` hides the output.

**Line 21**

```bash
TFVARS="$TF_DIR/terraform.tfvars"
```

`TFVARS` holds the path of the file `terraform.tfvars` in the environment folder. A `.tfvars` file assigns values to Terraform's input variables.

**Lines 22 to 24**

```bash
if [[ ! -f "$TFVARS" ]]; then
  [[ -n "${ALERT_EMAIL:-}" ]] || die "set ALERT_EMAIL=you@example.com (budget and dead-letter alerts go there), or write $TFVARS yourself"
  log "writing $TFVARS from your az session (it holds ids, so it is git-ignored)"
```

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

**New idea.** **git** is the version-control system that records every change to the project's files as a numbered commit, so any earlier state can be recovered and changes can be reviewed. Files listed in `.gitignore` are never recorded.

`if [[ ! -f "$TFVARS" ]]; then` runs the block only when the file does **not** exist (`-f` tests for a regular file, `!` negates). Inside it, line 23 `[[ -n "${ALERT_EMAIL:-}" ]] || die "..."` requires that `ALERT_EMAIL` is set and not empty (`-n`), and stops with an explanation if not. Line 24 logs that the file is about to be written from the Azure session, and that it is excluded from git because it holds ids.

**Lines 25 to 32**

```bash
  cat >"$TFVARS" <<TFVARS_EOF
subscription_id       = "$(az account show --query id --output tsv)"
tenant_id             = "$(az account show --query tenantId --output tsv)"
operator_object_id    = "$(az ad signed-in-user show --query id --output tsv)"
alert_email_addresses = ["$ALERT_EMAIL"]
budget_contact_emails = ["$ALERT_EMAIL"]
budget_start_date     = "$(date -u +%Y-%m-01T00:00:00Z)"
TFVARS_EOF
```

**New idea.** **Microsoft Entra ID** (formerly Azure Active Directory) is the identity service of Azure. A **tenant** is one organization's directory in it. Every identity in the directory (a person, a group, an application, a managed identity) has an *object id*, and the party that receives permissions is called the *principal*.

**New idea.** A **here document** `<<MARKER ... MARKER` feeds the lines between the marker words to a command as its input, with variables and `$(...)` expanded inside. `cat >file <<MARKER` therefore writes those lines into the file.

`cat >"$TFVARS" <<TFVARS_EOF` writes everything up to the line `TFVARS_EOF` into the file. The lines in between are Terraform variable assignments in which `$(...)` is replaced before writing: `az account show --query id --output tsv` prints the subscription id, `--query tenantId` the tenant id, and `az ad signed-in-user show --query id` the object id of the signed-in person (who becomes the operator allowed to send and receive messages). The alert address goes into `alert_email_addresses` and `budget_contact_emails`, and `date -u +%Y-%m-01T00:00:00Z` gives the first day of the current month as the budget start date. These values are personal, so the file is created at run time and never committed.

**Line 33**

```bash
fi
```

`fi` ends the `if` block.

**Lines 35 to 36**

```bash
terraform -chdir="$TF_DIR" init -input=false
terraform -chdir="$TF_DIR" apply -input=false $AUTO_APPROVE
```

Two Terraform commands, both run in the environment folder: `init` downloads the provider plug-ins, and `apply` creates the resources. `$AUTO_APPROVE` is left unquoted on purpose, so that when it is empty it disappears and when it holds `-auto-approve` it becomes that option.

**Lines 38 to 39**

```bash
"$ROOT/scripts/show-queues.sh"
log "phase 1 done. Export the settings with: eval \"\$(scripts/env.sh)\"   then: make produce, make worker"
```

Runs `show-queues.sh` to print the queue settings, then logs that phase 1 is done and shows what to do next: load the settings into the shell with `eval "$(scripts/env.sh)"` (the backslash in `\$(` keeps the dollar sign from being evaluated inside the message), then `make produce` and `make worker`.

#### `scripts/run-workers.sh`

25 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```bash
#!/usr/bin/env bash
```



**Lines 2 to 4**

```bash
# Lesson step 4: run N workers in parallel on the session queue, from this laptop (az login identity), sharing one ledger.
#   scripts/run-workers.sh 3
# Each worker's log goes to logs/worker-<n>.log, so `grep "out of order" logs/worker-*.log` is the lesson's check.
```

**New idea.** A word with `*` such as `scripts/*.sh` is a **glob**: bash replaces it with the list of file names that match.

A comment block. Lesson step 4: run N workers in parallel on the session queue, from this laptop using your `az login` identity, all sharing one ledger. Each worker's log goes to `logs/worker-<n>.log`, so that `grep "out of order" logs/worker-*.log` is the lesson's check (the `*` in the pattern matches any worker number).

**Lines 5 to 6**

```bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
```

`source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"` loads the shared helpers (`log`, `die`, `need`, `require_login`, `tf_out`, `retry`, and the variables `ROOT` and `TF_DIR`) from `lib.sh`, which sits in the same folder as this script.

**Lines 8 to 12**

```bash
COUNT="${1:-3}"
IDLE="${UNTIL_IDLE:-60}"
mkdir -p "$ROOT/logs" "$ROOT/data"
export USE_SESSIONS=1
: "${SB_NAMESPACE:?run: eval \"\$(scripts/env.sh)\"}"
```

- `COUNT="${1:-3}"` is how many workers to start: the first argument, or 3.
- `IDLE="${UNTIL_IDLE:-60}"` is how many seconds a worker may wait without receiving anything before it stops: the environment variable `UNTIL_IDLE`, or 60.
- `mkdir -p "$ROOT/logs" "$ROOT/data"` creates the two folders if needed (`-p` means no error if they exist).
- `export USE_SESSIONS=1` tells every worker started from here to use the session queue.
- `: "${SB_NAMESPACE:?run: eval \"\$(scripts/env.sh)\"}"` is a check written with the no-op command `:`. The `:?` form stops the script with the given message if `SB_NAMESPACE` is not set, which tells the user to run the `eval` line from `env.sh` first.

**Lines 14 to 16**

```bash
pids=()
cleanup() { kill -TERM "${pids[@]}" 2>/dev/null || true; }
trap cleanup INT TERM
```

**New idea.** An **array** holds a list of values: `pids=()` creates an empty one, `pids+=("$x")` appends an element, and `"${pids[@]}"` expands to all elements as separate words.

**New idea.** `trap command SIGNAL` registers a command to run when the script receives that **signal**. A signal is a message the operating system sends to a process: `INT` is sent by Ctrl+C and `TERM` by the request to stop. It is used to clean up when the script is interrupted.

**New idea.** A **process** is one running program, with its own memory and a number (its **pid**). Starting a command starts a process.

`pids=()` creates an empty array that will hold the process ids of the workers. `cleanup()` is a function that sends the `TERM` signal to all of them (`kill -TERM`), hiding errors (`2>/dev/null`) and never failing (`|| true`) in case some already ended. `trap cleanup INT TERM` makes bash call `cleanup` when the script itself receives Ctrl+C (`INT`) or a stop request (`TERM`), so the workers are stopped and not left running.

**Lines 18 to 22**

```bash
for n in $(seq 1 "$COUNT"); do
  "$ROOT/.venv/bin/order-worker" --until-idle "$IDLE" >"$ROOT/logs/worker-$n.log" 2>&1 &
  pids+=("$!")
  log "worker $n started (pid $!), log: logs/worker-$n.log"
done
```

**New idea.** A **virtual environment** is a private folder holding a copy of the Python interpreter and the libraries installed for one project. It keeps the project's libraries separate from the rest of the machine, so two projects can use different versions of the same library.

**New idea.** A command followed by `&` runs in the **background**: the script continues at once without waiting for it. `$!` is the process id (pid) of the most recently started background command, and `wait pid` waits for that process to finish and returns its status.

`for n in $(seq 1 "$COUNT")` loops over the numbers 1 to COUNT (`seq` prints a sequence). Each round starts one worker: `"$ROOT/.venv/bin/order-worker" --until-idle "$IDLE" >"$ROOT/logs/worker-$n.log" 2>&1 &` runs the worker program with the idle limit, writes all its output to its own log file, and the final `&` puts it in the background. `pids+=("$!")` appends its process id (`$!`) to the array, and `log` reports it.

**Lines 24 to 26**

```bash
status=0
for pid in "${pids[@]}"; do wait "$pid" || status=$?; done
log "all workers finished (exit status $status)"
```

`status=0`, then for each recorded pid `wait "$pid" || status=$?` waits for that worker to finish; if it fails, its exit status is remembered in `status`. After all have finished the script logs the combined status.

**Lines 27 to 28**

```bash
violations="$(cat "$ROOT"/logs/worker-*.log | grep -c 'out of order' || true)"
log "lines containing 'out of order' in the logs: $violations"
```

`cat "$ROOT"/logs/worker-*.log | grep -c 'out of order' || true` joins all worker logs and counts the lines that contain `out of order` (`grep -c` prints a count); `|| true` keeps the script going if the count is zero, because `grep` exits with failure when it finds nothing. The next line logs the number, the lesson's measure of ordering violations.

**Line 29**

```bash
"$ROOT/.venv/bin/order-check"
```

Finally runs `order-check`, which compares the ledger with the lesson's correct end state.

#### `scripts/show-queues.sh`

14 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```bash
#!/usr/bin/env bash
```



**Line 2**

```bash
# The queue properties the lesson sets (30 s lock, 10 deliveries) and the message counts that are the runbook's signals.
```

A comment: the script prints the queue properties the lesson sets (a 30-second lock and ten deliveries) and the message counts that serve as the runbook's signals.

**Lines 3 to 6**

```bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need az terraform
require_login
```

`source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"` loads the shared helpers (`log`, `die`, `need`, `require_login`, `tf_out`, `retry`, and the variables `ROOT` and `TF_DIR`) from `lib.sh`, which sits in the same folder as this script.
Requires `az` and `terraform` and an Azure sign-in.

**Lines 8 to 9**

```bash
RG="$(tf_out resource_group_name)"
NAMESPACE="$(tf_out namespace_name)"
```

Reads the resource group name and the Service Bus namespace name from Terraform outputs.

**Lines 10 to 15**

```bash
for queue in orders orders-sessions; do
  log "queue $queue"
  az servicebus queue show --resource-group "$RG" --namespace-name "$NAMESPACE" --name "$queue" \
    --query '{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount, requiresSession:requiresSession, active:countDetails.activeMessageCount, deadLetter:countDetails.deadLetterMessageCount}' \
    --output table
done
```

**New idea.** **`az`** is the Azure command-line program. `az <group> <command> --option value` calls the Azure management service; `--output tsv` prints plain values, `--output table` prints a table, and `--query '<expression>'` picks parts of the JSON answer using a query language called JMESPath.

Loops over the two queues. For each one, `log` prints its name and `az servicebus queue show` fetches its properties: `--resource-group`, `--namespace-name` and `--name` identify the queue, and `--output table` prints a table. The `--query` argument keeps only five fields, renamed in a small object: `lockDuration`, `maxDeliveryCount`, `requiresSession`, and the two message counts `countDetails.activeMessageCount` (waiting to be processed) and `countDetails.deadLetterMessageCount` (moved to the dead-letter sub-queue). The two lines ending in a backslash continue the command on the next line. `done` ends the loop.

#### `scripts/teardown.sh`

13 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```bash
#!/usr/bin/env bash
```



**Lines 2 to 3**

```bash
# Destroy everything this project created, including the subscription-scoped budget.
#   scripts/teardown.sh [--yes]
```

A comment: destroy everything this project created, including the subscription-scoped budget. Usage: `scripts/teardown.sh [--yes]`.

**Lines 4 to 7**

```bash
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need az terraform
require_login
```

`source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"` loads the shared helpers (`log`, `die`, `need`, `require_login`, `tf_out`, `retry`, and the variables `ROOT` and `TF_DIR`) from `lib.sh`, which sits in the same folder as this script.
Requires `az` and `terraform` and an Azure sign-in.

**Lines 9 to 10**

```bash
AUTO_APPROVE=""
[[ "${1:-}" == "--yes" ]] && AUTO_APPROVE="-auto-approve"
```

Sets `AUTO_APPROVE` to `-auto-approve` only when the first argument is `--yes`; otherwise Terraform will ask for confirmation before destroying.

**Lines 12 to 13**

```bash
RG="$(tf_out resource_group_name)"
terraform -chdir="$TF_DIR" destroy -input=false $AUTO_APPROVE
```

Reads the resource group name first (it will not exist in the outputs afterwards), then runs `terraform destroy` in the environment folder, which deletes every resource Terraform created.

**Lines 14 to 15**

```bash
log "resource group $RG exists? -> $(az group exists --name "$RG")"
log "a Service Bus namespace is deleted at once (it has no soft delete); the Standard tier bills by the hour until then"
```

After the destroy, `az group exists --name "$RG"` prints `true` or `false`, so the log shows whether the resource group is really gone. The last line logs a reminder: a Service Bus namespace is deleted at once (it has no soft delete) and the Standard tier bills by the hour until then.

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

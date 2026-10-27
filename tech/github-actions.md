# GitHub Actions

*Runs the same checks on every push. Pinned here: actions/checkout v4, setup-python v5, setup-terraform v3, setup-tflint v4.*

## What it is

GitHub Actions runs automated jobs when something happens in a GitHub repository, such as a push. A **workflow** is a YAML file in `.github/workflows/`. It lists **jobs**; each job runs a list of **steps** on a fresh virtual machine (the **runner**). This is the continuous integration (CI) that checks every push.

## Why this repository uses it

The template asks that CI mirrors the local commands. The workflow runs `make check`, `make audit`, `make scan` and the image smoke test.

## Where it appears

| File | What it does with it |
|---|---|
| `.github/workflows/ci.yml` | The workflow. |

## How it works underneath

`on: [push, pull_request]` is the trigger. Each job starts on an empty `ubuntu-latest` machine, so the first step is `actions/checkout` to download the repository. A step either `uses:` a published **action** (a reusable unit, pinned here by major version such as `actions/checkout@v4`) or `run:`s shell commands.

`permissions: contents: read` limits what the workflow's token can do. `env:` sets variables for every job. `${{ env.NAME }}` is an expression the runner fills in before running. Jobs run in parallel unless one `needs:` another.

## Walkthrough of this repository's use

```yaml
name: ci

on: [push, pull_request]

permissions:
  contents: read

env:
  TERRAFORM_VERSION: "1.17.0"
  TFLINT_VERSION: "v0.59.1"
```

`on: [push, pull_request]` runs on both. `permissions: contents: read` gives the job's token read-only access. `env` defines two version variables used below as `${{ env.TERRAFORM_VERSION }}`.

```yaml
  check:
    name: Format, lint, types, import rules, shellcheck, unit, integration and end-to-end tests, Terraform validate and tests, tflint, dependency audit
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TERRAFORM_VERSION }}
          terraform_wrapper: false
      - uses: terraform-linters/setup-tflint@v4
        with:
          tflint_version: ${{ env.TFLINT_VERSION }}
      - run: make check
      - run: make audit
```

The `check` job: `runs-on: ubuntu-latest` picks the machine; `actions/checkout@v4` downloads the repository; `setup-python` installs Python 3.13 (quoted so it stays text); `hashicorp/setup-terraform` installs Terraform at the pinned version (`terraform_wrapper: false` so output is plain); `setup-tflint` installs TFLint. Then `make check` and `make audit` are the same commands a developer runs.

```yaml
  checkov:
    name: Checkov on the Terraform, Dockerfile and workflows
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install checkov==3.3.30
      - run: make scan CHECKOV=checkov
```

A second job installs checkov with pip and runs `make scan`; the Makefile variable `CHECKOV=checkov` replaces the default `uvx` command. The third job builds the image and runs the smoke test. The three jobs run in parallel.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `.github/workflows/ci.yml`

41 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```yaml
name: ci
```

**New idea.** **YAML** is a data format built on indentation: a line `key: value` sets a value, a line ending in `:` introduces a nested group written on the indented lines below it, and lines starting with `- ` are the items of a list. A `#` starts a comment.

`name: ci` names the workflow. **GitHub Actions** is GitHub's automation: a *workflow* is a YAML file in `.github/workflows/`, and GitHub runs it when the events it names happen.

**Line 3**

```yaml
on: [push, pull_request]
```

`on: [push, pull_request]` lists the events that start the workflow: someone pushes commits, or opens or updates a pull request. The square brackets write a list on one line.

**Lines 5 to 6**

```yaml
permissions:
  contents: read
```

**New idea.** An **access token** is a short-lived piece of text, issued by an identity service after you prove who you are, that you attach to a request to show that you are allowed to make it. It expires after about an hour, so a stolen one is far less dangerous than a password.

`permissions` limits what the workflow's automatic access token may do. `contents: read` allows reading the repository and nothing else, which is the least privilege the checks need.

**Lines 8 to 10**

```yaml
env:
  TERRAFORM_VERSION: "1.17.0"
  TFLINT_VERSION: "v0.59.1"
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

`env` defines variables for the whole workflow: the Terraform version and the tflint version, kept in one place so that every step uses the same pinned values. They are read below as `${{ env.NAME }}`; the double braces are GitHub's expression syntax.

**Line 12**

```yaml
jobs:
```

`jobs:` starts the list of jobs. A *job* is a group of steps run on one fresh machine; jobs run at the same time unless one is told to wait for another.

**Line 13**

```yaml
  check:
```

The first job is called `check` (its key).

**Line 14**

```yaml
    name: Format, lint, types, import rules, shellcheck, unit, integration and end-to-end tests, Terraform validate and tests, tflint, dependency audit
```

`name` is the label shown in GitHub's interface; it lists everything this job checks.

**Line 15**

```yaml
    runs-on: ubuntu-latest
```

**New idea.** A **virtual machine (VM)** is a computer you rent in Azure and run like a real one. `az vm run-command` makes the VM's agent run a script on it and return the output, so no SSH connection or public address is needed.

`runs-on: ubuntu-latest` chooses the kind of machine: a current Ubuntu Linux virtual machine hosted by GitHub, created for this job and thrown away afterwards.

**Line 16**

```yaml
    steps:
```

`steps:` starts the ordered list of things to do.

**Line 17**

```yaml
      - uses: actions/checkout@v4
```

`- uses: actions/checkout@v4` runs a ready-made **action** (a reusable step published on GitHub) that downloads the repository's code onto the machine. `@v4` pins its major version. A line starting with `- ` begins one item of the list.

**Lines 18 to 20**

```yaml
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
```

`actions/setup-python@v5` installs Python. `with:` passes settings to the action; here `python-version: "3.13"`.

**Lines 21 to 24**

```yaml
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: ${{ env.TERRAFORM_VERSION }}
          terraform_wrapper: false
```

`hashicorp/setup-terraform@v3` installs Terraform. `terraform_version` takes the version from the `env` variable `TERRAFORM_VERSION`; `terraform_wrapper: false` turns off a wrapper that would otherwise change how Terraform's output is captured by later steps.

**Lines 25 to 27**

```yaml
      - uses: terraform-linters/setup-tflint@v4
        with:
          tflint_version: ${{ env.TFLINT_VERSION }}
```

`terraform-linters/setup-tflint@v4` installs tflint at the pinned version.

**Line 28**

```yaml
      - run: make check
```

`- run: make check` is a step that runs a shell command: the project's own `check` target, which runs the linters, the tests and the Terraform validation. CI therefore runs exactly what a developer runs on a laptop.

**Line 29**

```yaml
      - run: make audit
```

**New idea.** With **peek-lock**, a receiver takes a message but the broker only hides it under a *lock* for a limited time (30 seconds here). If the receiver *completes* the message it is deleted; if it *abandons* it or the lock expires, the message becomes visible again and is delivered once more, which is why processing must tolerate duplicates.

`- run: make audit` checks the locked dependencies against the database of known vulnerabilities.

**Lines 31 to 34**

```yaml
  checkov:
    name: Checkov on the Terraform, Dockerfile and workflows
    runs-on: ubuntu-latest
    steps:
```

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

The second job, `checkov`, with its label, machine and the start of its steps. It is separate so that the scanner runs in parallel with the main checks.

**Line 35**

```yaml
      - uses: actions/checkout@v4
```

Downloads the code.

**Lines 36 to 38**

```yaml
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
```

Installs Python 3.13 for this job.

**Line 39**

```yaml
      - run: pip install checkov==3.3.30
```

`pip install checkov==3.3.30` installs the scanner at an exact version.

**Line 40**

```yaml
      - run: make scan CHECKOV=checkov
```

`make scan CHECKOV=checkov` runs the scan target and tells it to use the `checkov` command just installed instead of the default `uvx` form.

**Lines 42 to 45**

```yaml
  image:
    name: Build the image and smoke-test it (non-root, packaged SQL, fail-fast configuration)
    runs-on: ubuntu-latest
    steps:
```

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

The third job, `image`: its label, machine and steps.

**Line 46**

```yaml
      - uses: actions/checkout@v4
```

Downloads the code.

**Line 47**

```yaml
      - run: make docker-smoke
```

`make docker-smoke` builds the image and runs the smoke-test script: the container runs as a non-root user, the packaged SQL works, and a missing configuration makes the worker fail at once.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `.checkov.yaml` | 6, 12 | [checkov.md](checkov.md) |
| `.dockerignore` | 4 | [docker.md](docker.md) |
| `.tflint.hcl` | 14 | [tflint.md](tflint.md) |

## Try it yourself

List the actions used.

```bash
grep -n 'uses:' .github/workflows/ci.yml
```

You should see something like this:

```text
17:      - uses: actions/checkout@v4
18:      - uses: actions/setup-python@v5
21:      - uses: hashicorp/setup-terraform@v3
25:      - uses: terraform-linters/setup-tflint@v4
35:      - uses: actions/checkout@v4
36:      - uses: actions/setup-python@v5
46:      - uses: actions/checkout@v4
```

List the commands, which are all `make` targets.

```bash
grep -n 'run:' .github/workflows/ci.yml
```

You should see something like this:

```text
28:      - run: make check
29:      - run: make audit
39:      - run: pip install checkov==3.3.30
40:      - run: make scan CHECKOV=checkov
47:      - run: make docker-smoke
```

Count the steps that simply call `make`.

```bash
grep -c 'run: make' .github/workflows/ci.yml
```

You should see something like this:

```text
4
```

## Mistakes people make

- Giving the workflow write permissions it does not need. This one reads only.
- Pinning actions to a moving branch. They are pinned to a major version tag here (the safest choice is a full commit hash).
- Running different commands in CI than locally. The workflow runs the same `make` targets a developer runs.
- Echoing secrets into logs. There are none here.
- Forgetting that `ubuntu-latest` changes over time.

## Check yourself

1. **What is a runner?**
   Answer: The fresh virtual machine a job runs on.

2. **What does `uses:` do?**
   Answer: Runs a published, reusable action.

3. **What does `permissions: contents: read` do?**
   Answer: Limits the workflow token to reading the repository.

4. **Why does every job start with checkout?**
   Answer: The runner begins empty; checkout downloads the code.

5. **Why does CI call `make` targets?**
   Answer: So CI and developers run exactly the same commands.

## Further reading

- Workflow syntax: https://docs.github.com/en/actions/writing-workflows/workflow-syntax-for-github-actions
- Security hardening: https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions

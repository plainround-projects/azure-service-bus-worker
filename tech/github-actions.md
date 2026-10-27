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

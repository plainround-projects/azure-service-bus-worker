# Git and .gitignore

*Records the history and keeps local state out of it. Pinned here: Git (any recent version).*

## What it is

Git is a **version control system**: it records every change to the files of a project as a series of **commits**, so you can see who changed what and why, and go back. A **repository** is the project folder plus its history (kept in a hidden `.git` folder). A `.gitignore` file lists files Git must never record.

## Why this repository uses it

Each project becomes its own repository to be pushed later. The history is split by layer so a reader can follow how the system was built, and the ignore rules keep state and installs out.

## Where it appears

| File | What it does with it |
|---|---|
| `.gitignore` | What never gets committed. |
| `infra/environments/dev/.terraform.lock.hcl` | A lock file that is committed on purpose. |

## How it works underneath

A commit is a snapshot of the tracked files with a message, an author and a pointer to the commit before it. `git add` chooses what goes into the next commit; `git commit` records it. `git status` shows what changed and what is not tracked. A **branch** (`main`) is a movable name for a commit.

`.gitignore` patterns say which untracked files to leave alone: `.venv/` (the installed packages), `__pycache__/`, `*.tfstate` (Terraform's record of real resources, which can hold secrets), `*.tfvars` (variable files that may hold ids). A negated pattern such as `!*.tfvars.example` brings a file back. Files already tracked are not affected by later ignore rules.

## Walkthrough of this repository's use

```text
.venv/
__pycache__/
*.pyc
*.egg-info/
build/
dist/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.import_linter_cache/
.coverage
.env
.DS_Store
.omc/
```

The first block ignores Python's installs and caches: the virtual environment, `__pycache__`, build folders, tool caches and coverage output, plus `.env` (local settings) and `.DS_Store` (a macOS file).

```text
# Terraform: providers and state stay out of git; the lock file (.terraform.lock.hcl) is committed.
.terraform/
*.tfstate
*.tfstate.*
data/
*.tfvars
!*.tfvars.example
backend.hcl
```

The Terraform block ignores `.terraform/` (downloaded providers), state files (`*.tfstate`, which can hold secrets), `*.tfvars` (variable files with personal ids) but brings back `!*.tfvars.example`, and `backend.hcl`. The last lines ignore throwaway module lock files; only the environment's lock file is committed.

## Try it yourself

Read the history.

```bash
git log --oneline | cat
```

You should see something like this:

```text
49c0c41 docs: record the image smoke test as pending capacity
a1e9fef docs: add README, ARCHITECTURE, RUNBOOK, decision records and CHANGELOG
4706822 build: add the Dockerfile, Makefile, tflint and checkov configuration and the CI workflow
2808416 feat(scripts): add the lesson's runbook as scripts
b1a16ec feat(infra): add the dev environment
b0d0eff feat(infra): add the Terraform modules with their tests
f421845 test: add unit, integration and end-to-end tests
7136da5 feat(infrastructure,interfaces): add the Service Bus and SQLite adapters, the simulated broker and the programs
3b9ea8e feat(domain,application): add orders, ordering, repair and the worker use cases
504c5c4 feat(sql): add the ledger schema, seed, queries, idempotency migration and reset
1e44c2b chore: scaffold the repository
```

A clean tree prints 0.

```bash
git status --short | wc -l
```

You should see something like this:

```text
1
```

Ask Git which rule ignores each path.

```bash
git check-ignore -v .venv terraform.tfstate infra/environments/dev/terraform.tfvars
```

You should see something like this:

```text
.gitignore:1:.venv/	.venv
.gitignore:19:*.tfstate	terraform.tfstate
.gitignore:22:*.tfvars	infra/environments/dev/terraform.tfvars
```

## Mistakes people make

- Committing state files, key files or `.env` files. The ignore rules here exist to prevent that.
- An ignore rule that hides a file you meant to commit: one repository here nearly lost its `phase-*.tfvars` files to `*.tfvars` and needed a `!phase-*.tfvars` exception.
- Committing build output such as `dist/` or `.venv/`.
- One giant commit. The history here is split by layer so each commit is readable.
- Pushing before checking `git status` is clean.

## Check yourself

1. **What is a commit?**
   Answer: A recorded snapshot of the tracked files with a message and a link to the previous commit.

2. **What does `.gitignore` do?**
   Answer: Tells Git which untracked files to leave out.

3. **Why ignore `*.tfstate`?**
   Answer: It can contain secrets and the exact details of real resources.

4. **What does a `!` pattern do in `.gitignore`?**
   Answer: Re-includes files an earlier pattern excluded.

5. **Does adding a rule to `.gitignore` untrack a committed file?**
   Answer: No; already tracked files stay tracked.

## Further reading

- Pro Git book: https://git-scm.com/book/en/v2
- gitignore: https://git-scm.com/docs/gitignore

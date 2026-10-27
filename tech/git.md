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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `.gitignore`

26 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 15**

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
logs/
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** A **virtual environment** is a private folder holding a copy of the Python interpreter and the libraries installed for one project. It keeps the project's libraries separate from the rest of the machine, so two projects can use different versions of the same library.

**New idea.** **Code coverage** measures which lines (and branches) of the program were run while the tests ran. A line the tests never reach is untested, so the project requires a high percentage for its core layers.

**New idea.** **git** is the version-control system that records every change to the project's files as a numbered commit, so any earlier state can be recovered and changes can be reviewed. Files listed in `.gitignore` are never recorded.

- `.venv/`: A `.gitignore` file lists patterns of files that git must not track. Each line is one pattern; a line starting with `#` is a comment; a blank line is ignored. The folder `.venv` holds a Python **virtual environment**: a private copy of the interpreter and the installed libraries for this one project. It is built by a command, never edited by hand, so git must not store it. The trailing `/` means the pattern matches a folder.
- `__pycache__/`: Python writes compiled copies of the source files into folders named `__pycache__`; they are rebuilt on demand.
- `*.pyc`: `*.pyc` matches compiled Python files. `*` stands for any run of characters.
- `*.egg-info/`: Folders ending in `.egg-info` hold package metadata that `pip install -e .` generates.
- `build/`: The `build/` folder holds output created while packaging.
- `dist/`: The `dist/` folder holds finished packages.
- `.pytest_cache/`: pytest's memory of the last run (which tests failed).
- `.mypy_cache/`: mypy's cache of already checked files.
- `.ruff_cache/`: ruff's cache of already checked files.
- `.import_linter_cache/`: import-linter's cache of the import graph.
- `.coverage`: The data file the coverage tool writes while the tests run.
- `.env`: A `.env` file holds local settings, possibly secrets, for one machine. Ignoring it keeps them out of git. (`.env.example`, the template without secrets, is not ignored.)
- `.DS_Store`: A hidden file macOS creates in folders it has displayed.
- `.omc/`: Working files of a developer tool; per-machine, not part of the project.
- `logs/`: Log files written while running locally.

**Lines 17 to 25**

```text
# Terraform: providers and state stay out of git; the lock file (.terraform.lock.hcl) is committed.
.terraform/
*.tfstate
*.tfstate.*
data/
*.tfvars
!*.tfvars.example
backend.hcl
.tflint.d/
```

**New idea.** **Microsoft Entra ID** (formerly Azure Active Directory) is the identity service of Azure. A **tenant** is one organization's directory in it. Every identity in the directory (a person, a group, an application, a managed identity) has an *object id*, and the party that receives permissions is called the *principal*.

**New idea.** A **lock file** records the exact versions (and often the hashes) of every package a project uses, including packages that those packages need. Installing from it gives the same result on every machine and on every day.

**New idea.** Terraform's **state** is a file in which it records the real resources it created and their ids. Each run compares the code, the state and reality to decide what to change. It may contain sensitive values, so it is never committed; a *backend* is the place where the state is stored.

**New idea.** An Azure **subscription** is the billing container for resources: everything created in it is charged to it, and its settings and access control apply to it. A *tenant* (the organization's identity directory) can hold several subscriptions.

- `# Terraform: providers and state stay out of git; the lock file (.terraform.lock.hcl) is committed.`: Comment for the reader: Terraform: providers and state stay out of git; the lock file (.terraform.lock.hcl) is committed.
- `.terraform/`: The folder where `terraform init` downloads the provider plug-ins. It is large, platform-specific and rebuilt by `init`.
- `*.tfstate`: Terraform **state** files record the real resources Terraform created. They can contain secrets, so they must never be committed.
- `*.tfstate.*`: Backups of the state file (`terraform.tfstate.backup`).
- `data/`: Local database files (the SQLite ledger) created while running.
- `*.tfvars`: `.tfvars` files assign values to Terraform variables, here including the personal subscription and tenant ids, so they stay local.
- `!*.tfvars.example`: A line starting with `!` **re-includes** what an earlier line excluded: the `.example` templates with placeholder values are committed even though `*.tfvars` is ignored.
- `backend.hcl`: `backend.hcl` is the local copy of the remote-state settings, with real names; only `backend.hcl.example` is committed.
- `.tflint.d/`: The folder where `tflint --init` downloads its rule plug-ins.

**Lines 27 to 28**

```text
# Only the environment pins provider versions (its lock file is committed); module test runs create throwaway locks.
infra/modules/*/.terraform.lock.hcl
```

- `# Only the environment pins provider versions (its lock file is committed); module test runs create throwaway locks.`: Comment for the reader: Only the environment pins provider versions (its lock file is committed); module test runs create throwaway locks.
- `infra/modules/*/.terraform.lock.hcl`: Test runs of a module create a throwaway provider lock file in the module folder. Only the environment's lock file is the real one (it is committed), so these are ignored.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `infra/environments/dev/terraform.tfvars.example` | 1 to 2 | [terraform.md](terraform.md) |
| `.dockerignore` | 1 | [docker.md](docker.md) |
| `scripts/provision.sh` | 24 | [bash.md](bash.md) |

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

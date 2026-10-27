# YAML

*The format of the CI workflow and the checkov settings. Pinned here: YAML 1.2.*

## What it is

YAML is a text format for configuration. It describes **mappings** (`key: value`), **lists** (lines that start with `- `) and plain values, and it uses **indentation** (spaces, never tabs) to show what belongs inside what. GitHub Actions workflows and the checkov settings file in this repository are YAML.

## Why this repository uses it

GitHub Actions and checkov read YAML. Indentation is the structure, so a one-space slip changes the meaning.

## Where it appears

| File | What it does with it |
|---|---|
| `.github/workflows/ci.yml` | The workflow. |
| `.checkov.yaml` | The scanner settings. |

## How it works underneath

A YAML file is read by a program into nested maps and lists. Indentation is the structure: two lines indented by the same number of spaces are siblings; a line indented further is a child of the line above. A `|` after a key starts a block of literal multi-line text. A `#` starts a comment.

Values are guessed: `true` is a boolean, `1.17.0` is text, `1.0` would be a number. Quote a value when the guess would be wrong (`"1.17.0"`, `"3.13"`). Python version `3.10` unquoted would become the number `3.1`.

## Walkthrough of this repository's use

```yaml
jobs:
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

`jobs:` is a mapping; `check:` is a key inside it and its value is another mapping indented two spaces further. `steps:` holds a list; each `- ` starts one step, and the lines indented under it (`uses:`, `with:`) belong to that step. The `name:` value on the job is a long sentence with commas and a colon-free text, so it needs no quotes. `python-version: "3.13"` is quoted so it stays text.

```yaml
framework:
  - terraform
  - dockerfile
  - github_actions
```

`framework:` is a key whose value is a list of three names.

### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `.github/workflows/ci.yml` | 1 | [github-actions.md](github-actions.md) |
| `Makefile` | 111 | [make.md](make.md) |

## Try it yourself

Read the top of the workflow.

```bash
sed -n 1,12p .github/workflows/ci.yml
```

You should see something like this:

```text
name: ci

on: [push, pull_request]

permissions:
  contents: read

env:
  TERRAFORM_VERSION: "1.17.0"
  TFLINT_VERSION: "v0.59.1"

jobs:
```

Confirm there are no tabs.

```bash
.venv/bin/python - <<'EOF'
import re
text = open('.github/workflows/ci.yml').read()
print('tab characters:', text.count(chr(9)))
EOF
```

You should see something like this:

```text
tab characters: 0
```

## Mistakes people make

- Using tabs. YAML allows only spaces for indentation.
- Not quoting versions like `3.13`, which a parser may read as a number.
- Wrong indentation by one space, which silently changes the meaning.
- Writing `on` or `yes` and getting a boolean; quote when you mean text.
- Long lines with colons inside unquoted text.

## Check yourself

1. **How does YAML show that one item belongs inside another?**
   Answer: By indentation with spaces.

2. **What starts a list item?**
   Answer: A line beginning with `- `.

3. **Why quote `"3.13"`?**
   Answer: Unquoted, a parser might read it as the number 3.13 and later drop meaning (for example `3.10` becomes `3.1`).

4. **Can YAML use tabs for indentation?**
   Answer: No.

5. **What does `|` after a key do?**
   Answer: It starts a block of literal multi-line text.

## Further reading

- YAML 1.2.2: https://yaml.org/spec/1.2.2/

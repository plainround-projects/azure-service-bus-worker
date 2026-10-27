# Checkov

*Scans the Terraform, Dockerfile and workflow for security misconfigurations. Pinned here: Checkov 3.3.30.*

## What it is

Checkov is a security scanner for infrastructure files. It reads Terraform (and Dockerfiles and GitHub workflows) and compares each resource with hundreds of rules such as "storage accounts must not allow public blobs". It reports each rule as passed, failed or skipped.

## Why this repository uses it

The template asks for `checkov` in CI. Findings were fixed where practical; the rest are skipped with a reason beside the resource.

## Where it appears

| File | What it does with it |
|---|---|
| `.checkov.yaml` | What to scan. |
| `infra/modules/servicebus/main.tf` | Inline skips for the Premium-only features. |
| `infra/modules/container_registry/main.tf` | Inline skips for Premium registry features. |
| `Makefile` | `make scan`. |

## How it works underneath

Checkov parses the Terraform into a graph, evaluates variables where it can, and runs each **check** (each named like `CKV_AZURE_59`) against the matching resources. A failed check prints the resource, file and a guide link.

You can **skip** a check with a comment inside the resource: `#checkov:skip=CKV_AZURE_59:reason`. The reason after the second colon is shown in the report. This repository puts every skip with its reason beside the resource it affects, so a reviewer reads the trade-off next to the code. `.checkov.yaml` selects folders, frameworks, and a `var-file` so variables are evaluated as in the final deployment.

## Walkthrough of this repository's use

```yaml
directory:
  - infra
  - .github
file:
  - Dockerfile
framework:
  - terraform
  - dockerfile
  - github_actions
download-external-modules: false
evaluate-variables: true
```

Scans `infra/` and `.github/`, plus the Dockerfile.

```hcl
resource "azurerm_servicebus_namespace" "this" {
  #checkov:skip=CKV_AZURE_201:customer-managed keys need the Premium tier; Standard is the cheapest tier that has sessions
  #checkov:skip=CKV_AZURE_199:double encryption needs the Premium tier
  #checkov:skip=CKV_AZURE_202:the namespace makes no outbound calls, so it needs no identity of its own
  #checkov:skip=CKV_AZURE_204:private endpoints and network rules need the Premium tier; access is Entra ID only (local_auth_enabled = false)
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Standard" # sessions need Standard or Premium; Standard is the cheaper of the two
  tags                = var.tags

  # Entra ID only: shared access signatures and the connection strings that carry them stop working, so the producer
  # and the worker can authenticate with nothing but their identities.
  local_auth_enabled  = false
  minimum_tls_version = "1.2"
}
```

Four checks cannot pass on the Standard tier: customer-managed keys, double encryption, a private endpoint or network rule, and an identity on the namespace itself. Each skip says why. The namespace does pass the check that matters most here: shared access keys are off (`local_auth_enabled = false`).

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `.checkov.yaml`

14 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 3**

```yaml
# checkov over the Terraform in infra/, the Dockerfile and the workflow. Findings that are deliberate choices for this
# teaching slice carry an inline `checkov:skip=ID:reason` next to the resource, so each skip and its reason can be
# read where the code is; nothing is skipped here.
```

**New idea.** **Azure Blob Storage** stores files (*blobs*) in a *storage account*. Blobs live in *containers*, which work like top-level folders, and each blob is addressed by account, container and name. (This "container" is not a Docker container.)

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

A comment of three lines. **checkov** is a scanner that reads infrastructure code (and Dockerfiles and workflow files) and reports settings that are risky, such as a storage account open to the public. Where a finding is a deliberate choice, the code carries an inline `checkov:skip=RULE:reason` comment next to the resource, so each exception and its reason can be read where it applies. This configuration file itself skips nothing.

**Lines 4 to 6**

```yaml
directory:
  - infra
  - .github
```

`directory:` followed by an indented list. **YAML** is a data format built on indentation: a line ending in `:` names a key, and lines starting with `- ` below it, indented, are the items of a list. This list tells checkov to scan every file under `infra` (all Terraform) and under `.github` (the CI workflow).

**Lines 7 to 8**

```yaml
file:
  - Dockerfile
```

`file:` lists single files to scan: here the `Dockerfile` in the repository root.

**Lines 9 to 12**

```yaml
framework:
  - terraform
  - dockerfile
  - github_actions
```

`framework:` lists the kinds of files to check: `terraform`, `dockerfile` and `github_actions`. Limiting the list keeps checkov from trying rule sets that do not apply.

**Line 13**

```yaml
download-external-modules: false
```

`download-external-modules: false` stops checkov from downloading modules from the internet while scanning. It checks only the modules that are in this repository, so the result does not depend on the network.

**Line 14**

```yaml
evaluate-variables: true
```

`evaluate-variables: true` makes checkov work out the values of Terraform variables (from their defaults) before applying rules, so a rule such as "public access must be off" sees `false` instead of the text `var.public_network_access_enabled`.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `infra/modules/container_registry/main.tf` | 2 to 9 | [azure-container-registry.md](azure-container-registry.md) |
| `infra/modules/servicebus/main.tf` | 2 to 5 | [azure-service-bus.md](azure-service-bus.md) |
| `.github/workflows/ci.yml` | 31, 39 to 40 | [github-actions.md](github-actions.md) |
| `Makefile` | 8, 110 to 111 | [make.md](make.md) |

## Try it yourself

Run the scan and read the totals.

```bash
make scan CHECKOV="uvx --from checkov==3.3.30 checkov" 2>&1 | grep -E 'Passed|results'
```

You should see something like this:

```text
terraform scan results:
Passed checks: 4, Failed checks: 0, Skipped checks: 12
terraform scan results:
Passed checks: 8, Failed checks: 0, Skipped checks: 24
github_actions scan results:
Passed checks: 63, Failed checks: 0, Skipped checks: 0
```

Count the skips per module.

```bash
grep -rc 'checkov:skip' infra/modules | grep -v ':0'
```

You should see something like this:

```text
infra/modules/servicebus/main.tf:4
infra/modules/container_registry/main.tf:8
```

## Mistakes people make

- Skipping a check without a reason. Each skip here says why.
- Treating the score as proof of security. It finds known misconfigurations only.
- Skipping instead of fixing when the fix is a one-line change.
- Scanning with default variable values that differ from the real ones; that is what `var-file` fixes.
- Ignoring skips when the lesson moves on (for example once a private endpoint exists).

## Check yourself

1. **What does a check ID like `CKV_AZURE_59` identify?**
   Answer: One rule about one kind of misconfiguration.

2. **How do you skip a check?**
   Answer: With a `#checkov:skip=ID:reason` comment inside the resource.

3. **Why put the reason in the comment?**
   Answer: So the next reader sees the trade-off beside the code.

4. **What does `evaluate-variables` do?**
   Answer: Lets checkov substitute variable values before checking.

5. **Does a passing scan mean the system is secure?**
   Answer: No; it only means known misconfigurations were not found.

## Further reading

- Checkov 3.3: https://www.checkov.io/
- Suppressing checks: https://www.checkov.io/2.Basics/Suppressing%20and%20Skipping%20Policies.html

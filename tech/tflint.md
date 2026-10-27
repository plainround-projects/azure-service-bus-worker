# TFLint

*Lints the Terraform on `make lint`. Pinned here: TFLint 0.65, azurerm ruleset 0.28.0.*

## What it is

TFLint is a linter for Terraform. It reads the configuration without creating anything and reports mistakes the compiler-like `terraform validate` does not catch: unused variables, missing version constraints, values that Azure will reject.

## Why this repository uses it

`terraform validate` accepts anything that is well-formed. TFLint adds rules about unused declarations and values Azure will reject.

## Where it appears

| File | What it does with it |
|---|---|
| `.tflint.hcl` | The configuration. |
| `Makefile` | `make lint` runs it when installed; CI always does. |

## How it works underneath

TFLint reads `.tflint.hcl` for its settings. A **plugin** is a ruleset: the built-in `terraform` plugin (rule preset `recommended`) checks language habits; the `azurerm` plugin knows Azure's accepted values. `tflint --init` downloads the plugins named in the file. `--recursive` lints every module folder, and `--minimum-failure-severity=warning` makes warnings fail the run (the default fails only on errors).

## Walkthrough of this repository's use

```hcl
config {
  call_module_type = "local"
}
```

`call_module_type = "local"` makes it follow the local `module` calls. The `terraform` plugin with `preset = "recommended"` brings the language rules (unused variables, missing version constraints). The `azurerm` plugin, pinned to 0.28.0 and fetched from GitHub by `tflint --init`, knows Azure's accepted values.

```make
	@if command -v tflint >/dev/null; then \
	  tflint --init --config "$(CURDIR)/.tflint.hcl" >/dev/null && tflint --chdir infra --recursive --minimum-failure-severity=warning --config "$(CURDIR)/.tflint.hcl"; \
```

`tflint --init` fetches the plugins; `--chdir infra --recursive` lints every module folder; `--minimum-failure-severity=warning` makes warnings fail the build; `--config` gives the absolute path to the file. If TFLint is not installed, the Makefile prints a visible warning and CI runs it.

## Try it yourself

Check the installed version.

```bash
tflint --version | head -1
```

You should see something like this:

```text
TFLint version 0.65.0
```

Lint all modules (silent when clean).

```bash
tflint --chdir infra --recursive --minimum-failure-severity=warning --config "$(pwd)/.tflint.hcl" && echo 'tflint clean'
```

You should see something like this:

```text
tflint clean
```

## Mistakes people make

- Skipping `--init`, so the plugin is missing: `Plugin "azurerm" not found`.
- Running from the wrong folder so the config file is not found; the Makefile passes `--config` with a full path.
- Leaving unused variables and outputs in modules.
- Letting warnings pass. Here a warning fails the build.
- Expecting TFLint to know your cloud account; it works offline.

## Check yourself

1. **What does TFLint check that `terraform validate` does not?**
   Answer: Style and likely mistakes such as unused declarations and invalid provider values.

2. **What does `tflint --init` do?**
   Answer: Downloads the plugins listed in `.tflint.hcl`.

3. **What does `--recursive` do?**
   Answer: Lints every module folder under the starting folder.

4. **Why raise the failure severity to warning?**
   Answer: So warnings stop the build instead of piling up.

5. **Does it need cloud credentials?**
   Answer: No.

## Further reading

- TFLint 0.65: https://github.com/terraform-linters/tflint
- azurerm ruleset 0.28: https://github.com/terraform-linters/tflint-ruleset-azurerm

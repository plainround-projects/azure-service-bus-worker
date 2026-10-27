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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `.tflint.hcl`

13 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```hcl
# tflint --init downloads the azurerm ruleset once; --recursive then lints infra/ and every module.
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

A comment. **tflint** is a *linter* for Terraform: a program that reads the code without running it and reports mistakes and bad habits. It consists of a small core plus *plug-ins*, each a rule set. `tflint --init` downloads the plug-ins named in this file, once, and `tflint --recursive` then checks the environment folder and every module folder.

**Lines 2 to 4**

```hcl
config {
  call_module_type = "local"
}
```

The `config` block holds settings for tflint itself. `call_module_type = "local"` tells it to follow `module` blocks into the folders on disk (the project's own `infra/modules/...`) and lint those too, but not to download modules from the internet.

**Lines 6 to 9**

```hcl
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}
```

The `terraform` plug-in is the rule set that ships inside tflint. It checks general Terraform hygiene: unused variables, missing version constraints, deprecated syntax. `enabled = true` switches it on. `preset = "recommended"` picks the rule list the tflint authors recommend, so the project does not have to enable each rule by hand.

**Lines 11 to 15**

```hcl
plugin "azurerm" {
  enabled = true
  version = "0.28.0"
  source  = "github.com/terraform-linters/tflint-ruleset-azurerm"
}
```

**New idea.** A **virtual machine (VM)** is a computer you rent in Azure and run like a real one. `az vm run-command` makes the VM's agent run a script on it and return the output, so no SSH connection or public address is needed.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

The `azurerm` plug-in is a separate rule set for the Azure provider. It knows the valid values of Azure settings (for example which virtual machine sizes exist) and reports a typo in a value that plain Terraform would only discover when Azure rejects it during `apply`. `version = "0.28.0"` pins the rule set so that a new release cannot change the result of a lint run, and `source` says where to download it (a GitHub project).

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

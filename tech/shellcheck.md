# ShellCheck

*Lints every script on `make lint`. Pinned here: ShellCheck (Homebrew's current release).*

## What it is

ShellCheck is a tool that reads shell scripts and reports bugs and bad habits without running them: unquoted variables, commands that behave differently than they look, constructs that do not work on other shells. Each finding has a code such as `SC2086`.

## Why this repository uses it

Scripts that touch cloud resources must not have quoting bugs. ShellCheck finds them without running anything.

## Where it appears

| File | What it does with it |
|---|---|
| `Makefile` | `make lint` runs it on `scripts/*.sh`. |
| `scripts/` | The files it checks. |

## How it works underneath

ShellCheck parses the script the way Bash would, tracks where variables are set and used, and compares what you wrote with a long list of known pitfalls. It prints the line, a caret under the problem and a link to a page that explains it.

When a script does `source other.sh`, ShellCheck cannot know which file that is unless it is told. `-x` lets it follow `source` lines and `-P SCRIPTDIR` tells it to look in the script's own folder. The severity filter `-S style` makes even style notes fail the run.

## Walkthrough of this repository's use

```make
	shellcheck -x -P SCRIPTDIR scripts/*.sh
```

`-x` follows `source` lines; `-P SCRIPTDIR` says "look for sourced files next to the script that sources them", which is where `lib.sh` is. The shell glob `scripts/*.sh` expands to every script. In this repository ShellCheck found two things during the build: `grep | wc -l` where `grep -c` is simpler (SC2126, rewritten) and a declare-and-assign that hides an error code (SC2155, split into two lines).

### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `Makefile` | 67, 72 | [make.md](make.md) |
| `.github/workflows/ci.yml` | 14 | [github-actions.md](github-actions.md) |

## Try it yourself

Lint every script at the strictest severity.

```bash
shellcheck -x -P SCRIPTDIR -S style scripts/*.sh && echo clean
```

You should see something like this:

```text
clean
```

See what ShellCheck says about an unquoted variable.

```bash
printf '#!/usr/bin/env bash\nfile=$1\nrm $file\n' > /tmp/bad-example.sh; shellcheck /tmp/bad-example.sh | head -12; rm /tmp/bad-example.sh
```

You should see something like this:

```text
In /tmp/bad-example.sh line 3:
rm $file
   ^---^ SC2086 (info): Double quote to prevent globbing and word splitting.

Did you mean:
rm "$file"

For more information:
  https://www.shellcheck.net/wiki/SC2086 -- Double quote to prevent globbing ...
```

## Mistakes people make

- Disabling a check with `# shellcheck disable=` to get green. The scripts here were changed instead.
- Forgetting `-x`, so sourced helper files are not checked.
- Believing a clean run proves the script works. It checks style and known traps, not behavior.
- Running it only on `.sh` files; scripts without an extension need an explicit path.
- Ignoring `info` level notes such as SC2015 (`A && B || C` is not if-then-else); this repository fixed that one.

## Check yourself

1. **What does ShellCheck do?**
   Answer: It reads a shell script and reports likely bugs without running it.

2. **What is `SC2086`?**
   Answer: The warning about an unquoted variable that may split into several words.

3. **What does `-x` do?**
   Answer: It follows `source` lines to the files they load.

4. **Why is `A && B || C` not if-then-else?**
   Answer: C also runs when A succeeds and B fails.

5. **Does a clean ShellCheck run prove the script works?**
   Answer: No; it checks for known traps, not for correct behavior.

## Further reading

- ShellCheck wiki (checks explained): https://www.shellcheck.net/wiki/
- Usage: https://github.com/koalaman/shellcheck#readme (the version on the author's machine is the one that Homebrew installs)

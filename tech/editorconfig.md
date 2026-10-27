# .editorconfig

*Keeps whitespace consistent across editors. Pinned here: EditorConfig (no version; a plain-text format).*

## What it is

`.editorconfig` is a small file that tells editors how to treat files in a project: which character set, line endings and indentation to use. Most editors read it automatically, so everyone who edits the project gets the same whitespace.

## Why this repository uses it

Four-space Python, two-space YAML and tab-indented Makefiles must stay that way whatever editor is used.

## Where it appears

| File | What it does with it |
|---|---|
| `.editorconfig` | The rules. |

## How it works underneath

The file has sections named by file patterns (`[*.yml]`). Keys such as `indent_style` and `indent_size` apply to files that match. `root = true` at the top stops editors from looking for more `.editorconfig` files in parent folders.

The file does nothing by itself: the editor (or a plugin) reads it and applies it while you type. It does not check files already saved.

## Walkthrough of this repository's use

```text
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{yml,yaml,json,toml,tf,hcl,sh}]
indent_size = 2

[Makefile]
indent_style = tab

[*.md]
trim_trailing_whitespace = false
```

`root = true` stops the search for more `.editorconfig` files. `[*]` applies to every file: UTF-8, Unix line endings (`lf`), a final newline, no trailing spaces, four spaces per indent. `[*.{yml,yaml,json,toml,tf,hcl,sh}]` overrides the indent to two for those file types. `[Makefile]` uses tabs, because Make requires them. `[*.md]` keeps trailing whitespace because two spaces at the end of a Markdown line can mean a line break.

## Try it yourself

Read the file.

```bash
cat .editorconfig | head -12
```

You should see something like this:

```text
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4

[*.{yml,yaml,json,toml,tf,hcl,sh}]
indent_size = 2
```

Count the tab characters in the Makefile (they must exist).

```bash
grep -c $'\t' Makefile
```

You should see something like this:

```text
56
```

## Mistakes people make

- Expecting it to reformat existing files. It only guides editors.
- Conflicting with a formatter. Here ruff's formatter and `.editorconfig` agree on four spaces for Python.
- Forgetting `[Makefile]`: Make requires real tab characters, so the file asks for tabs there.
- Trailing whitespace in Markdown is meaningful (two spaces make a line break), so the Markdown section keeps it.
- Leaving out `root = true`.

## Check yourself

1. **What is `.editorconfig` for?**
   Answer: It tells editors which indentation, line endings and charset to use in the project.

2. **Why does Make need a special rule?**
   Answer: Recipe lines must start with a tab character, not spaces.

3. **Does it fix files that are already saved?**
   Answer: No.

4. **What does `root = true` mean?**
   Answer: Stop searching parent folders for more configuration.

5. **Why does the Markdown section keep trailing spaces?**
   Answer: Two trailing spaces can mean a line break in Markdown.

## Further reading

- EditorConfig specification: https://spec.editorconfig.org/
- Project site: https://editorconfig.org/

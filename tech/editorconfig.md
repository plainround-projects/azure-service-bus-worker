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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `.editorconfig`

14 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```text
root = true
```

- `root = true`: An `.editorconfig` file tells every editor how to format files (indentation, line endings) so that different people's editors produce the same files. Stops editors from looking for more `.editorconfig` files in parent folders; this is the top one.

**Lines 3 to 9**

```text
[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 4
```

**New idea.** **UTF-8** is the standard way to store text as bytes, able to represent every language. A program that reads a file must decode the bytes with the right encoding to get text back.

- `[*]`: A line in square brackets is a **section header**: the settings below it apply to files whose names match the pattern. `*` matches every file.
- `charset = utf-8`: Save files as UTF-8 text.
- `end_of_line = lf`: End lines with a single line-feed character (the Unix style), not the Windows pair.
- `insert_final_newline = true`: End every file with a newline, as Unix tools expect.
- `trim_trailing_whitespace = true`: Remove spaces left at the end of lines when saving.
- `indent_style = space`: Indent with spaces, not tab characters.
- `indent_size = 4`: Each indentation level is four spaces (the Python convention).

**Lines 11 to 12**

```text
[*.{yml,yaml,json,toml,tf,hcl,sh}]
indent_size = 2
```

**New idea.** **JSON** is a text format for data: objects `{"name": value}`, lists `[1, 2]`, strings, numbers, `true`, `false` and `null`. Most web services send and receive their data as JSON because every programming language can read it.

- `[*.{yml,yaml,json,toml,tf,hcl,sh}]`: A section for these file types; the braces list alternatives.
- `indent_size = 2`: Each indentation level is two spaces in these formats.

**Lines 14 to 15**

```text
[Makefile]
indent_style = tab
```

- `[Makefile]`: A section for the file named exactly `Makefile`.
- `indent_style = tab`: `make` requires a real tab character at the start of each command line, so this file must be indented with tabs.

**Lines 17 to 18**

```text
[*.md]
trim_trailing_whitespace = false
```

- `[*.md]`: A section for Markdown files.
- `trim_trailing_whitespace = false`: Keep trailing spaces in Markdown: two spaces at the end of a line mean a line break there.

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

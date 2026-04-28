# CLAUDE.md

Personal Claude Code config toolkit published to PyPI as `claude-code-setup`. Components live under `src/claude_code_setup/components/`, each with a `component.json` manifest.

## Layout

```
src/claude_code_setup/
  cli.py               ← entry point (discover + install components)
  components/<name>/
    component.json     ← files to copy + settings.json keys to patch
    *.py               ← scripts copied to ~/.claude/
pyproject.toml
```

## Commands

```bash
# After publishing / installing from PyPI:
uvx claude-code-setup                    # install all
uvx claude-code-setup statusline         # install one
uvx claude-code-setup --list             # list available
uvx claude-code-setup --uninstall        # remove all

# Local dev (editable install):
uv venv && uv pip install -e .
claude-code-setup --list
```

## Publishing to PyPI

```bash
uv build
uv publish
```

## Adding a component

Create `src/claude_code_setup/components/<name>/component.json`:

```json
{
  "name": "my-component",
  "description": "shown in --list",
  "files": ["script.py"],
  "settings": {
    "settingsKey": { "type": "command", "command": "{runner} {dest}/script.py" }
  }
}
```

`{dest}` = `~/.claude/` · `{runner}` = `uv run` or `python3`. Nothing else to touch — `cli.py` discovers components automatically.

## Statusline segments

Each segment is `def seg_name(...) -> str | None`. `None` drops it silently. To add one: write the function, append it to the relevant `build_row([...])` call in `main()`.

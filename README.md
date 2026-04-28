# Claude Code Setup

A personal Claude Code configuration toolkit. Each component is self-contained and installs into `~/.claude` with a single command. Currently includes a status line that replaces the default bottom bar with a richer, information-dense display.

---

## Components

| Component | Description |
|---|---|
| `statusline` | 5-row status bar showing git state, context usage, session cost, rate limits, and last message |

---

## Installation

```bash
uvx claude-code-setup
```

Restart Claude Code after installing. The status bar appears at the bottom of the interface.

> **No `uv`?** Install it with `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Install a specific component:**
```bash
uvx claude-code-setup statusline
```

**Uninstall:**
```bash
uvx claude-code-setup --uninstall
```

---

## What's included

### Status line

A 5-row bar at the bottom of Claude Code showing everything useful at a glance.

![Statusline screenshot](docs/statusline-screenshot.png)

Color coding: green = healthy · amber = needs attention · red = critical.

| Row | Label | Always shown? | Content |
|---|---|---|---|
| 1 | `Session` | Yes | Model, session, directory, git branch, effort, vim mode |
| 2 | `Git` | In git repos | Staged / modified / untracked counts, ahead/behind remote, stash, last commit |
| 3 | `Context` | Yes | Context bar, token count, cache hit rate, cost, duration, API wait, lines changed |
| 4 | `Limits` | Pro/Max only | 5-hour and 7-day rate limit usage with reset countdowns, Claude Code version |
| 5 | `Message` | When available | Last user message (from transcript), truncated to 100 chars |

**See what every field means:**
```bash
uv run ~/.claude/statusline.py --help
```

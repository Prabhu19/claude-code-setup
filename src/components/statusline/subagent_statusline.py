#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""
Claude Code subagent status line.

Renders one rich row per subagent in the agent panel beneath the prompt.
Each row replaces the default "name · description · token count" line.

Row format:
  [STATUS ICON]  Agent Name  ·  description  ·  🎯 tokens  ·  ⏱ elapsed

Docs: https://code.claude.com/docs/en/statusline#subagent-status-lines

Configuration in ~/.claude/settings.json:
  "subagentStatusLine": { "type": "command", "command": "/path/to/subagent_statusline.py" }

Test with mock input:
  echo '{
    "columns": 120,
    "tasks": [
      {"id":"1","name":"code-reviewer","type":"agent","status":"running",
       "description":"Checking for style violations","tokenCount":8500,
       "startTime":"2025-01-01T10:00:00Z","cwd":"/tmp/proj"},
      {"id":"2","name":"test-runner","type":"agent","status":"completed",
       "description":"All tests passed","tokenCount":12300,
       "startTime":"2025-01-01T09:55:00Z","cwd":"/tmp/proj"}
    ]
  }' | python3 subagent_statusline.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

RESET: str = "\033[0m"
BOLD: str = "\033[1m"


def _c(n: int) -> str:
    return f"\033[38;5;{n}m"


class Colors:
    accent: str = _c(74)  # steel-blue
    gray: str = _c(245)
    dim: str = _c(238)
    good: str = _c(71)  # green  — completed
    warn: str = _c(136)  # amber  — running / pending
    danger: str = _c(167)  # red    — error
    special: str = _c(139)  # purple — waiting


DOT: str = f" {Colors.dim}·{RESET} "


# Status → (icon, colour)
_STATUS_MAP: dict[str, tuple[str, str]] = {
    "running": ("⟳", Colors.warn),
    "completed": ("✓", Colors.good),
    "failed": ("✗", Colors.danger),
    "error": ("✗", Colors.danger),
    "pending": ("○", Colors.special),
    "waiting": ("⏸", Colors.special),
    "cancelled": ("⊘", Colors.dim),
    "stopped": ("■", Colors.dim),
}


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def _fmt_elapsed(start_time_iso: str) -> str:
    """Return human-readable elapsed time from an ISO-8601 timestamp."""
    try:
        start: datetime = datetime.fromisoformat(start_time_iso.replace("Z", "+00:00"))
        delta: int = int((datetime.now(timezone.utc) - start).total_seconds())
        if delta < 60:
            return f"{delta}s"
        if delta < 3_600:
            m, s = divmod(delta, 60)
            return f"{m}m {s:02d}s"
        h, rem = divmod(delta, 3_600)
        return f"{h}h {rem // 60}m"
    except Exception:
        return ""


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def render_task(task: dict[str, Any], columns: int) -> str:
    """Build a single status row for one subagent task."""
    status: str = (task.get("status") or "pending").lower()
    name: str = task.get("name", "agent")
    description: str = task.get("description", "")
    token_count: int = task.get("tokenCount") or 0
    start_time: str = task.get("startTime", "")

    icon: str
    icon_color: str
    icon, icon_color = _STATUS_MAP.get(status, ("?", Colors.gray))

    parts: list[str] = []

    # Status icon + agent name
    parts.append(f"{icon_color}{icon}{RESET}  {Colors.accent}{BOLD}{name}{RESET}")

    # Description (if present)
    if description:
        desc_max: int = max(20, columns // 3)
        parts.append(f"{Colors.gray}{_truncate(description, desc_max)}{RESET}")

    # Token consumption
    if token_count:
        tok_color: str = (
            Colors.danger
            if token_count > 150_000
            else Colors.warn
            if token_count > 50_000
            else Colors.dim
        )
        parts.append(f"{tok_color}🎯 {_fmt_tokens(token_count)} tokens{RESET}")

    # Elapsed time (running tasks only — completed is less relevant)
    if start_time and status in ("running", "pending", "waiting"):
        elapsed: str = _fmt_elapsed(start_time)
        if elapsed:
            parts.append(f"{Colors.dim}⏱ {elapsed}{RESET}")

    return DOT.join(parts)


def main() -> None:
    data: dict[str, Any] = json.load(sys.stdin)
    columns: int = data.get("columns", 80)
    tasks: list[Any] = data.get("tasks") or []

    for task in tasks:
        task_id: str | None = task.get("id")
        if not task_id:
            continue
        content: str = render_task(task, columns)
        # Output one JSON line per task to override its row
        sys.stdout.write(json.dumps({"id": task_id, "content": content}) + "\n")


if __name__ == "__main__":
    main()

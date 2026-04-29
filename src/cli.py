#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""
Claude Code setup installer.

Usage:
    claude-code-setup                        # install all components
    claude-code-setup statusline             # install one by name
    claude-code-setup --list                 # show available components
    claude-code-setup --uninstall            # remove all installed components
    claude-code-setup statusline --uninstall # remove one component
"""

from __future__ import annotations

import argparse
import importlib.resources as pkg_resources
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from deepmerge import Merger  # type: ignore[attr-defined]

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"


# List merge strategy for deepmerge: append items from `nxt` that aren't already in `base`.
# JSON-encode each item so dicts/lists nested inside the list are comparable.
# Example: _dedupe_append(_, _, [1, 2], [2, 3]) -> [1, 2, 3]  (the 2 is not duplicated).
# The `config` and `path` args are required by deepmerge's strategy protocol but unused here.
def _dedupe_append(config: Any, path: Any, base: list[Any], nxt: list[Any]) -> list[Any]:
    seen = {json.dumps(item, sort_keys=True) for item in base}
    return base + [item for item in nxt if json.dumps(item, sort_keys=True) not in seen]


# deepmerge.Merger takes three positional arguments:
#   1. type_strategies     — per-type merge strategies, applied when both sides have that type
#   2. fallback_strategies — used when a type isn't covered above (e.g. str, int, None)
#   3. type_conflict_strategies — used when the two sides have *different* types
# We use "override" for the latter two so the new value always wins for scalars and on conflicts.
_merger = Merger(
    type_strategies=[(list, _dedupe_append), (dict, "merge")],
    fallback_strategies=["override"],
    type_conflict_strategies=["override"],
)


def _detect_runner() -> str:
    """Return the command used to run Python scripts.

    Prefers `uv run` when uv is installed because it resolves inline script
    dependencies automatically. Falls back to plain `python3` otherwise.

    Example:
        _detect_runner()  ->  "uv run"   # when uv is on PATH
        _detect_runner()  ->  "python3"  # fallback
    """
    return "uv run" if shutil.which("uv") else "python3"


def discover_components() -> dict[str, dict[str, Any]]:
    """Scan the bundled `components/` package directory and return all valid components.

    Each sub-directory that contains a `component.json` manifest is treated as a
    component. The manifest is parsed and the traversal handle (`_ref`) is stored
    inside the dict so callers can read sibling files without knowing the path.

    Example return value:
        {
            "statusline": {
                "name": "statusline",
                "description": "5-row status bar ...",
                "files": ["statusline.py"],
                "settings": {...},
                "_ref": <Traversable>,
            }
        }
    """
    found: dict[str, dict[str, Any]] = {}
    components_dir = pkg_resources.files("components")
    for entry in sorted(components_dir.iterdir(), key=lambda e: e.name):
        if entry.name.startswith("_"):
            continue
        manifest = entry / "component.json"
        try:
            data = json.loads(manifest.read_text())
            data["_ref"] = entry
            found[data["name"]] = data
        except Exception as exc:
            print(f"  Warning: could not load {entry.name}/component.json: {exc}", file=sys.stderr)
    return found


def _expand(value: object, placeholders: dict[str, str]) -> object:
    """Recursively substitute `{token}` placeholders in strings.

    Walks dicts and lists so placeholders nested at any depth are replaced.
    Non-string leaf values are returned as-is.

    Example:
        _expand("{runner} {dest}/hook.py", {"runner": "uv run", "dest": "/home/user/.claude"})
        ->  "uv run /home/user/.claude/hook.py"

        _expand({"command": "{runner} {dest}/hook.py"}, {"runner": "uv run", "dest": "~/.claude"})
        ->  {"command": "uv run ~/.claude/hook.py"}
    """
    if isinstance(value, str):
        for token, replacement in placeholders.items():
            value = value.replace(f"{{{token}}}", replacement)
        return value
    if isinstance(value, dict):
        return {k: _expand(v, placeholders) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, placeholders) for v in value]
    return value


def _remove_merged(existing: Any, to_remove: Any) -> Any:
    """Inverse of _merger.merge — subtract `to_remove` from `existing`.

    Return-value contract (None is the sentinel for "delete this key"):
        None          -> the value is fully gone; caller should DELETE the key
        <new value>   -> caller should REPLACE the key with this value
        existing      -> nothing matched; caller should leave the key alone

    Examples:
        # List: removes only matching entries
        _remove_merged(["A", "B", "C"], ["B"])  ->  ["A", "C"]
        _remove_merged(["A"], ["A"])             ->  None  (list is now empty)

        # Dict: recurses into keys
        _remove_merged({"x": 1, "y": 2}, {"x": 1})  ->  {"y": 2}
        _remove_merged({"x": 1}, {"x": 1})           ->  None  (dict is now empty)

        # Scalar: exact match deletes, mismatch leaves alone
        _remove_merged("old", "old")  ->  None
        _remove_merged("old", "new")  ->  "old"
    """
    if isinstance(existing, dict) and isinstance(to_remove, dict):
        result = dict(existing)
        for k, v in to_remove.items():
            if k not in result:
                continue
            cleaned = _remove_merged(result[k], v)
            if cleaned is None:
                del result[k]
            else:
                result[k] = cleaned
        return result if result else None  # empty dict → signal deletion
    if isinstance(existing, list) and isinstance(to_remove, list):
        remove_keys = {json.dumps(item, sort_keys=True) for item in to_remove}
        filtered: list[Any] = [item for item in existing if json.dumps(item, sort_keys=True) not in remove_keys]
        return filtered if filtered else None  # empty list → signal deletion
    # Type mismatch (e.g. dict vs list): no meaningful way to subtract, leave untouched.
    if type(existing) is not type(to_remove):
        return existing
    if existing == to_remove:
        return None  # exact scalar match → signal deletion
    return existing  # scalars differ → nothing to remove


def load_settings() -> dict[str, Any]:
    """Read ~/.claude/settings.json and return it as a dict.

    Returns an empty dict if the file does not exist yet.
    """
    if not SETTINGS.exists():
        return {}
    return json.loads(SETTINGS.read_text())  # type: ignore[no-any-return]


def save_settings(data: dict[str, Any]) -> None:
    """Write `data` to ~/.claude/settings.json as formatted JSON."""
    SETTINGS.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  Updated  {SETTINGS}")


def _apply_setting(settings: dict[str, Any], key: str, value: Any, merge: bool) -> bool:
    """Write one setting key into `settings` in-place. Returns True if anything changed.

    merge=True  → deep-merge `value` into the existing entry. Used for keys shared
                  across components (e.g. "hooks") so each component's contribution
                  is additive rather than destructive.

                  Example — two components both write to "hooks":
                    existing:  {"hooks": {"PreToolUse": [{"matcher": "Bash", ...}]}}
                    value:     {"PreToolUse": [{"matcher": "Edit", ...}]}
                    result:    {"hooks": {"PreToolUse": [<Bash entry>, <Edit entry>]}}

    merge=False → overwrite the key outright. The component owns it exclusively.

                  Example:
                    existing:  {"model": "opus"}
                    value:     "sonnet"
                    result:    {"model": "sonnet"}
    """
    new_value = _merger.merge(settings[key], value) if merge and key in settings else value
    if settings.get(key) == new_value:
        return False
    settings[key] = new_value
    return True


def _remove_setting(settings: dict[str, Any], key: str, value: Any, merge: bool) -> bool:
    """Remove one setting key from `settings` in-place. Returns True if anything changed.

    This is the exact inverse of _apply_setting.

    merge=True  → surgically remove only what this component contributed, leaving
                  other components' entries untouched.

                  Example — removing one component's hook entry while another stays:
                    existing:  {"PreToolUse": [<Bash entry>, <Edit entry>]}
                    value:     {"PreToolUse": [<Edit entry>]}   # what this component added
                    result:    {"PreToolUse": [<Bash entry>]}   # other component's entry kept

    merge=False → drop the whole key; the component owned it exclusively.

                  Example:
                    existing:  {"model": "sonnet"}
                    result:    {}  (key deleted)
    """
    if key not in settings:
        return False
    if not merge:
        del settings[key]
        return True
    # Subtract only this component's contribution; None means the key is now empty.
    cleaned = _remove_merged(settings[key], value)
    if cleaned is None:
        del settings[key]
        return True
    if cleaned != settings[key]:
        settings[key] = cleaned
        return True
    return False


def install_component(component: dict[str, Any], runner: str) -> None:
    """Install a single component: copy its scripts and patch settings.json.

    Phase 1 — Files:
        Each filename listed in component["files"] is copied from the package
        into ~/.claude/ and made executable.

    Phase 2 — Settings:
        Each key in component["settings"] is written into ~/.claude/settings.json.
        Keys listed in component["merge"] are deep-merged (additive); all others
        are overwritten outright. settings.json is only rewritten if something changed.

    Example component.json that triggers a merge:
        {
            "files": ["safety-gate.py"],
            "merge": ["hooks"],
            "settings": {
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [...]}]}
            }
        }

    Sample output:
        Installing [safety-gate]  PreToolUse hook that blocks destructive commands
          Copied   safety-gate.py → /Users/alice/.claude/safety-gate.py
          Updated  /Users/alice/.claude/settings.json
    """
    placeholders = {"dest": str(CLAUDE_DIR), "runner": runner}
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    # Phase 1: copy scripts into ~/.claude/
    for filename in component.get("files", []):
        src = component["_ref"] / filename
        dest = CLAUDE_DIR / filename
        dest.write_bytes(src.read_bytes())
        dest.chmod(0o755)
        print(f"  Copied   {filename} → {dest}")

    # Phase 2: patch settings.json
    settings = load_settings()
    merge_keys = set(component.get("merge", []))
    changed = False

    for key, value in component.get("settings", {}).items():
        if _apply_setting(settings, key, _expand(value, placeholders), merge=key in merge_keys):
            changed = True

    save_settings(settings) if changed else print("  settings.json already up-to-date")


def uninstall_component(component: dict[str, Any], runner: str) -> None:
    """Uninstall a single component: delete its scripts and unpatch settings.json.

    This is the exact inverse of install_component.

    Phase 1 — Files:
        Each filename listed in component["files"] is deleted from ~/.claude/.

    Phase 2 — Settings:
        Each key in component["settings"] is removed from ~/.claude/settings.json.
        Merge keys have only this component's contribution removed, leaving other
        components' entries intact. Non-merge keys are dropped entirely.

    Sample output:
        Uninstalling [safety-gate]  PreToolUse hook that blocks destructive commands
          Removed  /Users/alice/.claude/safety-gate.py
          Updated  /Users/alice/.claude/settings.json
    """
    placeholders = {"dest": str(CLAUDE_DIR), "runner": runner}
    removed = False

    # Phase 1: delete scripts from ~/.claude/
    for filename in component.get("files", []):
        path = CLAUDE_DIR / filename
        if path.exists():
            path.unlink()
            print(f"  Removed  {path}")
            removed = True

    # Phase 2: unpatch settings.json (mirror of install)
    settings = load_settings()
    merge_keys = set(component.get("merge", []))
    changed = False

    for key, value in component.get("settings", {}).items():
        if _remove_setting(settings, key, _expand(value, placeholders), merge=key in merge_keys):
            changed = True

    if changed:
        save_settings(settings)
        removed = True

    if not removed:
        print("  Nothing to remove")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Claude Code setup installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "components",
        nargs="*",
        metavar="COMPONENT",
        help="Component names to install (default: all)",
    )
    parser.add_argument("--list", action="store_true", help="List available components and exit")
    parser.add_argument("--uninstall", action="store_true", help="Remove instead of install")
    args = parser.parse_args()

    available = discover_components()
    if not available:
        print("No components found in package.", file=sys.stderr)
        sys.exit(1)

    if args.list:
        print()
        print("Available components:")
        for name, comp in available.items():
            print(f"  {name:<20} {comp.get('description', '')}")
        print()
        return

    if args.components:
        unknown = [n for n in args.components if n not in available]
        if unknown:
            print(f"Unknown component(s): {', '.join(unknown)}", file=sys.stderr)
            print(f"Available: {', '.join(available)}", file=sys.stderr)
            sys.exit(1)
        targets = {n: available[n] for n in args.components}
    else:
        targets = available

    runner = _detect_runner()
    action = "Uninstalling" if args.uninstall else "Installing"
    print()

    for name, component in targets.items():
        print(f"{action} [{name}]  {component.get('description', '')}")
        if args.uninstall:
            uninstall_component(component, runner)
        else:
            install_component(component, runner)
        print()

    if not args.uninstall:
        print("Done. Restart Claude Code to activate.")
        print()


if __name__ == "__main__":
    main()

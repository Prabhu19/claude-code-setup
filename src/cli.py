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

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS = CLAUDE_DIR / "settings.json"


def _detect_runner() -> str:
    return "uv run" if shutil.which("uv") else "python3"


def discover_components() -> dict[str, dict[str, Any]]:
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
    if isinstance(value, str):
        for token, replacement in placeholders.items():
            value = value.replace(f"{{{token}}}", replacement)
        return value
    if isinstance(value, dict):
        return {k: _expand(v, placeholders) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, placeholders) for v in value]
    return value


def load_settings() -> dict[str, Any]:
    if not SETTINGS.exists():
        return {}
    return json.loads(SETTINGS.read_text())  # type: ignore[no-any-return]


def save_settings(data: dict[str, Any]) -> None:
    SETTINGS.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  Updated  {SETTINGS}")


def install_component(component: dict[str, Any], runner: str) -> None:
    placeholders = {"dest": str(CLAUDE_DIR), "runner": runner}
    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

    for filename in component.get("files", []):
        src = component["_ref"] / filename
        dest = CLAUDE_DIR / filename
        dest.write_bytes(src.read_bytes())
        dest.chmod(0o755)
        print(f"  Copied   {filename} → {dest}")

    settings = load_settings()
    changed = False
    for key, value in component.get("settings", {}).items():
        expanded = _expand(value, placeholders)
        if settings.get(key) != expanded:
            settings[key] = expanded
            changed = True

    if changed:
        save_settings(settings)
    else:
        print("  settings.json already up-to-date")


def uninstall_component(component: dict[str, Any]) -> None:
    removed = False

    for filename in component.get("files", []):
        path = CLAUDE_DIR / filename
        if path.exists():
            path.unlink()
            print(f"  Removed  {path}")
            removed = True

    settings = load_settings()
    changed = False
    for key in component.get("settings", {}):
        if key in settings:
            del settings[key]
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
            uninstall_component(component)
        else:
            install_component(component, runner)
        print()

    if not args.uninstall:
        print("Done. Restart Claude Code to activate.")
        print()


if __name__ == "__main__":
    main()

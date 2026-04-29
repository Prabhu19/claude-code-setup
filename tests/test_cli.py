"""Tests for CLI functionality."""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to path to import cli module
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cli import discover_components


class TestDiscoverComponents:
    """Test component discovery."""

    def test_discover_components_returns_dict(self) -> None:
        """Should return a dictionary of components."""
        components = discover_components()
        assert isinstance(components, dict)

    def test_discover_components_has_statusline(self) -> None:
        """Should discover the statusline component."""
        components = discover_components()
        assert "statusline" in components
        assert "name" in components["statusline"]
        assert "description" in components["statusline"]

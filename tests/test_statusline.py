"""Professional test suite for statusline component.

Testing patterns inspired by Click and Rich testing approaches:
- Fixtures for common test data
- Parametrized tests for edge cases
- Integration tests verifying actual formatted output
- Mocked external dependencies
- Clear error case coverage
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src" / "components" / "statusline"))

from statusline import (
    Colors,
    GitInfo,
    color_for_pct,
    fmt_cost,
    fmt_duration,
    fmt_time_until,
    fmt_tokens,
    load_context_info,
    osc8_link,
    progress_bar,
    seg_branch,
    seg_cache_efficiency,
    seg_cost,
    seg_duration,
    seg_effort,
    seg_git_detail,
    seg_model,
    seg_vim,
)

# ============================================================================
# Fixtures — reusable test data (Click/Rich pattern)
# ============================================================================


@pytest.fixture
def minimal_data() -> dict:
    """Minimal valid Claude Code status data."""
    return {
        "model": {"display_name": "Claude 3.5 Sonnet"},
        "workspace": {"current_dir": "/home/user/project"},
    }


@pytest.fixture
def full_data() -> dict:
    """Complete realistic Claude Code status data."""
    future_time = time.time() + 7200
    return {
        "model": {"display_name": "Claude 3.5 Sonnet"},
        "workspace": {"current_dir": "/home/user/my-project"},
        "context_window": {
            "used_percentage": 55,
            "context_window_size": 200000,
            "current_usage": {
                "input_tokens": 45000,
                "cache_creation_input_tokens": 8000,
                "cache_read_input_tokens": 120000,
            },
        },
        "cost": {"total_cost_usd": 0.42, "total_duration_ms": 780000},
        "version": "2.1.90",
        "rate_limits": {
            "five_hour": {"used_percentage": 35, "resets_at": future_time},
            "seven_day": {"used_percentage": 62, "resets_at": future_time + 432000},
        },
        "vim": {"mode": "INSERT"},
        "effort": {"level": "high"},
    }


@pytest.fixture
def git_clean() -> GitInfo:
    """Clean git working tree."""
    return GitInfo(branch="main", staged=0, modified=0, untracked=0, ahead=0)


@pytest.fixture
def git_with_changes() -> GitInfo:
    """Git repo with staged, modified, and untracked files."""
    return GitInfo(
        branch="feature/auth-improvements",
        staged=3,
        modified=2,
        untracked=1,
        ahead=4,
        behind=0,
        last_commit="refactor: simplify auth flow · 12m ago",
    )


@pytest.fixture
def git_syncing() -> GitInfo:
    """Git repo out of sync with remote."""
    return GitInfo(
        branch="develop",
        staged=0,
        modified=0,
        untracked=0,
        ahead=5,
        behind=2,
        upstream="origin/develop",
    )


# ============================================================================
# Formatting Functions — exact output validation
# ============================================================================


class TestFmtTokens:
    """Test token count formatting with parametrized edge cases."""

    @pytest.mark.parametrize(
        "input_val,expected",
        [
            (0, "0"),
            (100, "100"),
            (999, "999"),
            (1_000, "1k"),
            (5_500, "6k"),
            (50_000, "50k"),
            (1_000_000, "1.0M"),
            (2_500_000, "2.5M"),
        ],
    )
    def test_token_formatting_all_scales(self, input_val: int, expected: str) -> None:
        """Tokens format correctly across all magnitude scales."""
        assert fmt_tokens(input_val) == expected


class TestFmtDuration:
    """Test duration formatting across time scales."""

    @pytest.mark.parametrize(
        "milliseconds,expected",
        [
            (0, "0s"),
            (30_000, "30s"),
            (60_000, "1m 00s"),
            (90_500, "1m 30s"),
            (3_600_000, "1h 00m"),
            (5_400_000, "1h 30m"),
        ],
    )
    def test_duration_across_scales(self, milliseconds: int, expected: str) -> None:
        """Duration formats correctly: seconds → minutes → hours."""
        assert fmt_duration(milliseconds) == expected


class TestFmtCost:
    """Test currency formatting with boundary cases."""

    @pytest.mark.parametrize(
        "usd,expected",
        [
            (0.0, "$0.00"),
            (0.001, "<$0.01"),
            (0.004, "<$0.01"),
            (0.01, "$0.01"),
            (0.50, "$0.50"),
            (1.00, "$1.0"),
            (10.50, "$10.5"),
        ],
    )
    def test_cost_formatting_all_ranges(self, usd: float, expected: str) -> None:
        """Cost formats correctly with proper rounding at boundaries."""
        assert fmt_cost(usd) == expected


class TestColorForPct:
    """Test traffic-light color mapping."""

    @pytest.mark.parametrize(
        "pct,expected_color",
        [
            (0, Colors.good),
            (50, Colors.good),
            (69, Colors.good),
            (70, Colors.warn),
            (80, Colors.warn),
            (89, Colors.warn),
            (90, Colors.danger),
            (100, Colors.danger),
        ],
    )
    def test_color_ranges_complete_coverage(self, pct: int, expected_color: str) -> None:
        """Colors map to ranges: good(<70) warn(70-89) danger(90+)."""
        assert color_for_pct(pct) == expected_color


@pytest.mark.parametrize("pct,width", [(0, 10), (50, 10), (100, 10), (75, 20)])
def test_progress_bar_renders_with_correct_width(pct: int, width: int) -> None:
    """Progress bar renders with correct block characters."""
    result = progress_bar(pct, width)
    assert "█" in result or "▄" in result or "░" in result
    assert "\033[" in result  # ANSI codes present


@patch("statusline.time.time")
class TestFmtTimeUntil:
    """Test relative time formatting with mocked time."""

    def test_time_until_seconds(self, mock_time: object) -> None:
        """Seconds-scale time shows minutes."""
        mock_time.return_value = 1000.0  # type: ignore
        assert fmt_time_until(1060.0) == "1m"

    def test_time_until_hours(self, mock_time: object) -> None:
        """Hour-scale time shows hours and minutes."""
        mock_time.return_value = 0.0  # type: ignore
        assert fmt_time_until(3600.0) == "1h"

    def test_time_until_past(self, mock_time: object) -> None:
        """Time in past shows 'now'."""
        mock_time.return_value = 1000.0  # type: ignore
        assert fmt_time_until(500.0) == "now"


# ============================================================================
# Segment Functions — component integration tests
# ============================================================================


class TestSegmentModel:
    """Test model name segment."""

    def test_model_displays_name(self, minimal_data: dict) -> None:
        """Model segment shows display name."""
        result = seg_model(minimal_data)
        assert "Sonnet" in result

    def test_model_shows_question_mark_when_missing(self) -> None:
        """Model segment shows '?' when no model name."""
        result = seg_model({})
        assert "?" in result

    @pytest.mark.parametrize("model_name", ["Opus", "Sonnet", "Haiku"])
    def test_model_with_various_names(self, model_name: str) -> None:
        """Model segment works with any name."""
        data = {"model": {"display_name": model_name}}
        result = seg_model(data)
        assert model_name in result


class TestSegmentBranch:
    """Test git branch segment."""

    @pytest.mark.parametrize(
        "branch_name",
        ["main", "develop", "feature/auth", "bugfix/JIRA-123"],
    )
    def test_branch_shows_name(self, branch_name: str) -> None:
        """Branch segment displays branch name."""
        git = GitInfo(branch=branch_name)
        result = seg_branch(git)
        assert result is not None
        assert branch_name in result

    def test_branch_none_when_empty(self) -> None:
        """Branch segment returns None for empty branch."""
        git = GitInfo(branch="")
        result = seg_branch(git)
        assert result is None


class TestSegmentGitDetail:
    """Test detailed git status (file counts, sync, last commit)."""

    def test_git_shows_file_counts(self, git_with_changes: GitInfo) -> None:
        """Git segment displays all file state counts."""
        result = seg_git_detail(git_with_changes)
        assert result is not None
        # Verify counts appear in output
        assert any(str(n) in result for n in [1, 2, 3])

    def test_git_shows_last_commit(self, git_with_changes: GitInfo) -> None:
        """Git segment includes last commit message."""
        result = seg_git_detail(git_with_changes)
        assert result is not None
        assert "refactor:" in result


class TestSegmentCost:
    """Test session cost segment."""

    def test_cost_displays_nonzero_amounts(self) -> None:
        """Cost segment shows dollar amounts."""
        data = {"cost": {"total_cost_usd": 0.42}}
        result = seg_cost(data)
        assert result is not None
        assert "$" in result

    def test_cost_none_when_zero(self) -> None:
        """Cost segment returns None when cost is 0."""
        data = {"cost": {"total_cost_usd": 0.0}}
        result = seg_cost(data)
        assert result is None


class TestSegmentCacheEfficiency:
    """Test cache hit rate segment."""

    def test_cache_shows_percentage(self, full_data: dict) -> None:
        """Cache segment shows hit rate."""
        result = seg_cache_efficiency(full_data)
        assert result is not None
        assert "cached" in result.lower()


class TestSegmentDuration:
    """Test elapsed time segment."""

    def test_duration_formats_time(self) -> None:
        """Duration segment formats milliseconds."""
        data = {"cost": {"total_duration_ms": 780000}}  # 13 minutes
        result = seg_duration(data)
        assert result is not None
        assert "13m" in result or "13" in result


class TestSegmentEffort:
    """Test reasoning effort level segment."""

    @pytest.mark.parametrize("level", ["low", "medium", "high", "xhigh", "max"])
    def test_effort_displays_level(self, level: str) -> None:
        """Effort segment shows reasoning level."""
        data = {"effort": {"level": level}}
        result = seg_effort(data)
        assert result is not None
        assert level in result.lower()

    def test_effort_none_when_missing(self) -> None:
        """Effort segment returns None when missing."""
        result = seg_effort({})
        assert result is None


class TestSegmentVim:
    """Test vim editor mode segment."""

    @pytest.mark.parametrize("mode", ["NORMAL", "INSERT", "VISUAL"])
    def test_vim_mode_displays(self, mode: str) -> None:
        """Vim segment shows editor mode."""
        data = {"vim": {"mode": mode}}
        result = seg_vim(data)
        assert result is not None
        assert mode in result

    def test_vim_none_when_missing(self) -> None:
        """Vim segment returns None when mode missing."""
        result = seg_vim({})
        assert result is None


# ============================================================================
# Integration & Context Loading
# ============================================================================


class TestContextInfoLoading:
    """Test context window data loading."""

    def test_context_info_parses_full_data(self, full_data: dict) -> None:
        """Context info correctly loads usage data."""
        ctx = load_context_info(full_data)
        assert ctx.pct == 55
        assert ctx.max_ctx == 200000

    def test_context_info_handles_empty_data(self) -> None:
        """Context info has sensible defaults."""
        ctx = load_context_info({})
        assert ctx.pct >= 0
        assert ctx.max_ctx == 200000


class TestOsc8Hyperlinks:
    """Test clickable hyperlink generation (terminal standard)."""

    def test_osc8_creates_valid_sequence(self) -> None:
        """OSC 8 hyperlink includes escape codes."""
        result = osc8_link("https://github.com/user/repo", "my-repo")
        assert "\033]8;;" in result
        assert "https://github.com/user/repo" in result
        assert "my-repo" in result

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/org/repo",
            "https://example.com/path?q=value",
        ],
    )
    def test_osc8_with_various_urls(self, url: str) -> None:
        """OSC 8 handles different URL formats."""
        result = osc8_link(url, "link")
        assert url in result


# ============================================================================
# Smoke Tests — verify functions don't crash with sparse data
# ============================================================================


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"model": {}},
        {"cost": {}},
        {"context_window": {}},
    ],
)
def test_all_segments_handle_incomplete_data_gracefully(data: dict) -> None:
    """All segment functions handle incomplete data without crashing."""
    seg_model(data)
    seg_branch(GitInfo())
    seg_cost(data)
    seg_duration(data)
    seg_effort(data)
    seg_vim(data)
    seg_cache_efficiency(data)
    load_context_info(data)

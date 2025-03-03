"""
Tests for the Klipper configuration linter.
"""

import pytest
from pathlib import Path

from klipperlint.linter import KlipperLinter, LintIssue
from klipperlint.config import LinterConfig

@pytest.fixture
def linter():
    """Create a basic linter instance."""
    return KlipperLinter()

@pytest.fixture
def strict_linter():
    """Create a linter instance with strict checking enabled."""
    config = LinterConfig()
    config.strict = True
    return KlipperLinter(config)

def test_lint_empty_config(tmp_path: Path, linter: KlipperLinter):
    """Test linting an empty configuration file."""
    config_file = tmp_path / "empty.cfg"
    config_file.write_text("")

    issues = linter.lint_file(config_file)
    assert len(issues) == 1  # Should have at least one issue - missing required sections

def test_lint_sample_config(sample_config: Path, linter: KlipperLinter):
    """Test linting the sample configuration file."""
    issues = linter.lint_file(sample_config)
    # Add assertions based on expected issues in sample config

# def test_lint_invalid_config(invalid_configs: List[Path], linter: KlipperLinter):
#     """Test linting invalid configuration files."""
#     for config_file in invalid_configs:
#         issues = linter.lint_file(config_file)
#         assert len(issues) > 0  # Should find issues in invalid configs

def test_strict_mode(sample_config: Path, strict_linter: KlipperLinter):
    """Test that strict mode finds additional issues."""
    regular_linter = KlipperLinter()

    regular_issues = regular_linter.lint_file(sample_config)
    strict_issues = strict_linter.lint_file(sample_config)

    assert len(strict_issues) >= len(regular_issues)  # Strict mode should find same or more issues
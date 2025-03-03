"""
Pytest configuration and shared fixtures.
"""

import pytest
from pathlib import Path
from typing import Generator, List

@pytest.fixture
def test_configs_dir() -> Path:
    """Return the path to the test configurations directory."""
    return Path(__file__).parent / "test_configs"

@pytest.fixture
def sample_config(test_configs_dir: Path) -> Path:
    """Return the path to a basic sample configuration file."""
    return test_configs_dir / "sample.cfg"

@pytest.fixture
def complex_configs(test_configs_dir: Path) -> List[Path]:
    """Return a list of paths to complex configuration files."""
    config_dir = test_configs_dir / "complex"
    return list(config_dir.glob("*.cfg"))

@pytest.fixture
def invalid_configs(test_configs_dir: Path) -> List[Path]:
    """Return a list of paths to invalid configuration files."""
    config_dir = test_configs_dir / "invalid"
    return list(config_dir.glob("*.cfg"))
"""
Configuration handling for the Klipper config linter.
"""

from pathlib import Path
from typing import List, Optional
import yaml

class LinterConfig:
    """Configuration class for the linter."""

    def __init__(self):
        self.verbose: bool = False
        self.strict: bool = False
        self.ignore: List[str] = []
        self.rules_directory = str(Path(__file__).parent / "rules")
        self.ignore_rules: List[str] = []
        self.warning_as_error: bool = False

    @classmethod
    def from_file(cls, config_file: Path) -> 'LinterConfig':
        """Create a configuration instance from a YAML file."""
        config = cls()

        try:
            with open(config_file, 'r') as f:
                data = yaml.safe_load(f)

            if not isinstance(data, dict):
                raise ValueError("Configuration file must contain a YAML dictionary")

            if 'verbose' in data:
                config.verbose = bool(data['verbose'])
            if 'strict' in data:
                config.strict = bool(data['strict'])
            if 'ignore' in data:
                if not isinstance(data['ignore'], list):
                    raise ValueError("'ignore' must be a list of rule IDs")
                config.ignore = data['ignore']

        except Exception as e:
            raise ValueError(f"Failed to load configuration file: {str(e)}")

        return config

    def should_ignore(self, rule_id: str) -> bool:
        """Check if a rule should be ignored."""
        return rule_id in self.ignore
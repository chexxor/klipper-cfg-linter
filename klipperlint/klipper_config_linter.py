from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from pathlib import Path

from klipperlint.klipper_config_parser import ConfigFile
from klipperlint.types import LintError, LintRule, RuleCategory, RuleDocumentation
from klipperlint.rules.heater_safety import heater_safety_rule

class KlipperLinter:
    def __init__(self, warning_as_error: bool = False):
        self.rules: List[LintRule] = []
        self.warning_as_error = warning_as_error

    def add_rule(self, rule: LintRule):
        self.rules.append(rule)

    def lint(self, config: ConfigFile) -> List[LintError]:
        errors = []
        for rule in self.rules:
            rule_errors = rule.check(config)
            if self.warning_as_error:
                # Convert warnings to errors
                rule_errors = [
                    LintError(
                        message=e.message,
                        section=e.section,
                        option=e.option,
                        severity="error" if e.severity == "warning" else e.severity,
                        line_number=e.line_number,
                        fix=e.fix
                    )
                    for e in rule_errors
                ]
            errors.extend(rule_errors)
        return errors

@dataclass
class LinterConfig:
    rules_directory: str = str(Path(__file__).parent.parent / "rules")
    ignore_rules: List[str] = field(default_factory=list)
    warning_as_error: bool = False
    custom_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)

def create_configured_linter(config: LinterConfig) -> KlipperLinter:
    linter = KlipperLinter(warning_as_error=config.warning_as_error)  # Pass the config option

    # Load rules from directory
    if config.rules_directory:
        from klipperlint.rule_loader import load_rules_from_directory
        all_rules = load_rules_from_directory(config.rules_directory)

        # Only add rules that aren't in ignore_rules
        for rule in all_rules:
            if rule.name not in config.ignore_rules:
                linter.add_rule(rule)

    # Add complex rules that are better suited for Python
    linter.add_rule(heater_safety_rule)

    return linter

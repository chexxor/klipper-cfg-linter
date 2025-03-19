from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from pathlib import Path
import logging

from klipperlint.klipper_config_parser import ConfigFile
from klipperlint.types import LintError, LintRule, RuleCategory, RuleDocumentation
from klipperlint.rules.heater_safety import heater_safety_rule
from .config import LinterConfig

class KlipperLinter:
    def __init__(self, warning_as_error: bool = False):
        self.rules: List[LintRule] = []
        self.warning_as_error = warning_as_error

    def add_rule(self, rule: LintRule):
        self.rules.append(rule)

    def lint(self, config: ConfigFile) -> List[LintError]:
        logger = logging.getLogger(__name__)
        logger.info("Starting lint analysis with %d rules", len(self.rules))

        errors = []
        for rule in self.rules:
            logger.debug("Checking rule: %s (%s)", rule.name, rule.category.name)
            rule_errors = rule.check(config)
            logger.debug("Found %d issues for rule %s", len(rule_errors), rule.name)
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

        logger.info("Completed lint analysis. Found %d total issues", len(errors))
        return errors

def create_configured_linter(config: LinterConfig) -> KlipperLinter:
    logger = logging.getLogger(__name__)
    logger.debug("Using rules directory: %s", config.rules_directory)
    logger.debug("Absolute rules path: %s", Path(config.rules_directory).resolve())

    linter = KlipperLinter(warning_as_error=config.warning_as_error)

    # Load rules from built-in directory
    try:
        from .rule_loader import load_rules_from_directory
        builtin_rules = load_rules_from_directory(config.rules_directory)
        for rule in builtin_rules:
            if rule.name not in config.ignore_rules:
                linter.add_rule(rule)
    except Exception as e:
        logging.error("Failed to load built-in rules: %s", str(e))

    # Add Python-based rules
    linter.add_rule(heater_safety_rule)

    return linter

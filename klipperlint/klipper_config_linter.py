from dataclasses import dataclass, field
from typing import List, Callable, Dict, Any, Tuple, Optional
import re
from enum import Enum

from klipperlint.klipper_config_parser import ConfigFile, ConfigSection

@dataclass(frozen=True)
class LintFix:
    section: str
    option: Optional[str]
    old_value: str
    new_value: str

@dataclass(frozen=True)
class LintError:
    message: str
    section: str
    option: Optional[str] = None
    severity: str = "error"  # could be "error", "warning", "info"
    line_number: Optional[int] = None
    fix: Optional[LintFix] = None

class RuleCategory(Enum):
    SYNTAX = "syntax"
    SAFETY = "safety"
    CONSISTENCY = "consistency"
    STYLE = "style"
    DEPENDENCY = "dependency"

@dataclass(frozen=True)
class RuleDocumentation:
    description: str
    examples: List[str]
    fix_suggestions: List[str]

class LintRule:
    def __init__(self, check_func: Callable[[ConfigFile], List[LintError]],
                 name: str, docs: RuleDocumentation, category: RuleCategory):
        self.check = check_func
        self.name = name
        self.docs = docs
        self.category = category

class KlipperLinter:
    def __init__(self):
        self.rules: List[LintRule] = []

    def add_rule(self, rule: LintRule):
        self.rules.append(rule)

    def lint(self, config: ConfigFile) -> List[LintError]:
        errors = []
        for rule in self.rules:
            errors.extend(rule.check(config))
        return errors

def check_pin_syntax(config: ConfigFile) -> List[LintError]:
    """Check that pin definitions follow correct syntax"""
    errors = []
    pin_pattern = re.compile(r'^[!-]?P[A-Z][0-9]+$')

    for section_name, section in config.sections.items():
        for option, value in section.options.items():
            if option.endswith('_pin'):
                if not pin_pattern.match(value):
                    errors.append(LintError(
                        f"Invalid pin format: {value}",
                        section_name,
                        option
                    ))
    return errors

def check_required_sections(config: ConfigFile) -> List[LintError]:
    """Check that required sections are present"""
    required_sections = {'printer'}
    missing = required_sections - set(config.sections.keys())

    return [
        LintError(f"Missing required section: {section}", section)
        for section in missing
    ]

def check_value_ranges(config: ConfigFile) -> List[LintError]:
    """Check that numeric values are within acceptable ranges"""
    errors = []

    # Example range checks
    ranges = {
        'max_velocity': (0, 1000),
        'max_accel': (0, 10000),
        'microsteps': (1, 256)
    }

    for section_name, section in config.sections.items():
        for option, value in section.options.items():
            if option in ranges:
                try:
                    val = float(value)
                    min_val, max_val = ranges[option]
                    if not min_val <= val <= max_val:
                        errors.append(LintError(
                            f"{option} value {val} outside valid range [{min_val}, {max_val}]",
                            section_name,
                            option
                        ))
                except ValueError:
                    errors.append(LintError(
                        f"Invalid numeric value for {option}: {value}",
                        section_name,
                        option
                    ))
    return errors

# Dependency checks
def check_section_dependencies(config: ConfigFile) -> List[LintError]:
    """Check that dependent sections exist"""
    errors = []
    if 'extruder' in config.sections:
        if 'heater_bed' not in config.sections:
            errors.append(LintError(
                "Extruder defined without heater_bed section",
                "extruder",
                severity="warning"
            ))
    return errors

# Format checks
def check_naming_conventions(config: ConfigFile) -> List[LintError]:
    """Check that names follow conventions"""
    errors = []
    for section_name in config.sections:
        if not section_name.islower():
            errors.append(LintError(
                f"Section name should be lowercase: {section_name}",
                section_name,
                severity="warning"
            ))
    return errors

# Consistency checks
def check_stepper_consistency(config: ConfigFile) -> List[LintError]:
    """Check that stepper configurations are consistent"""
    errors = []
    steppers = [s for s in config.sections if s.startswith('stepper_')]
    if steppers:
        first = config.sections[steppers[0]]
        for stepper in steppers[1:]:
            current = config.sections[stepper]
            if current.options.get('microsteps') != first.options.get('microsteps'):
                errors.append(LintError(
                    f"Inconsistent microsteps value in {stepper}",
                    stepper,
                    'microsteps',
                    severity="warning"
                ))
    return errors

@dataclass
class LinterConfig:
    ignore_rules: List[str] = field(default_factory=list)
    warning_as_error: bool = False
    custom_ranges: Dict[str, Tuple[float, float]] = field(default_factory=dict)

def create_configured_linter(config: LinterConfig) -> KlipperLinter:
    linter = KlipperLinter()

    # Add rules based on configuration
    all_rules = {
        "pin-syntax": (check_pin_syntax, RuleCategory.SYNTAX),
        "required-sections": (check_required_sections, RuleCategory.DEPENDENCY),
        "value-ranges": (check_value_ranges, RuleCategory.SAFETY),
        "naming-conventions": (check_naming_conventions, RuleCategory.STYLE),
        "section-dependencies": (check_section_dependencies, RuleCategory.DEPENDENCY),
        "stepper-consistency": (check_stepper_consistency, RuleCategory.CONSISTENCY)
    }

    for name, (rule_func, category) in all_rules.items():
        if name not in config.ignore_rules:
            linter.add_rule(LintRule(
                rule_func,
                name,
                RuleDocumentation("", [], []),
                category
            ))

    return linter

import pytest
from pathlib import Path
from textwrap import dedent
from typing import List

from klipperlint.klipper_config_linter import (
    KlipperLinter, LinterConfig, create_configured_linter
)
from klipperlint.klipper_config_parser import ConfigFile, ConfigSection
from klipperlint.types import LintError, RuleCategory, RuleDocumentation, LintRule

# Test fixtures
@pytest.fixture
def valid_config():
    return ConfigFile(
        sections={
            "printer": ConfigSection("printer", {
                "kinematics": "cartesian",
                "max_velocity": "300"
            }),
            "stepper_x": ConfigSection("stepper_x", {
                "step_pin": "PF0",
                "dir_pin": "PF1",
                "microsteps": "16"
            })
        },
        includes=[]
    )

@pytest.fixture
def invalid_config():
    return ConfigFile(
        sections={
            "stepper_x": ConfigSection("stepper_x", {
                "step_pin": "invalid_pin",
                "dir_pin": "also_invalid",
                "microsteps": "1000"
            }),
            "Stepper_Y": ConfigSection("Stepper_Y", {
                "step_pin": "PF2",
                "microsteps": "32"
            })
        },
        includes=[]
    )

@pytest.fixture
def temp_rules_dir(tmp_path):
    """Creates a temporary directory with test rule files"""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()

    # Create pin syntax rule
    pin_rule = """
    name: pin-syntax
    category: syntax
    description: "Check that pin definitions follow correct syntax"
    examples:
      valid:
        - "step_pin: PF0"
        - "dir_pin: !PF1"
      invalid:
        - "step_pin: invalid_pin"
        - "dir_pin: GPIO23"
    conditions:
      - type: "regex_match"
        applies_to: "option"
        pattern: ".*_pin$"
        value_pattern: "^[!-]?P[A-Z][0-9]+$"
        error_message: "Invalid pin format: {value}"
        severity: "error"
    """
    (rules_dir / "pin_syntax.yaml").write_text(dedent(pin_rule))

    # Create naming conventions rule
    naming_rule = """
    name: naming-conventions
    category: style
    description: "Check that names follow conventions"
    examples:
      valid:
        - "[stepper_x]"
        - "[extruder]"
      invalid:
        - "[Stepper_X]"
        - "[EXTRUDER]"
    conditions:
      - type: "section_name_pattern"
        pattern: "^[a-z][a-z0-9_]*$"
        error_message: "Section name should be lowercase: {section}"
        severity: "warning"
    """
    (rules_dir / "naming_conventions.yaml").write_text(dedent(naming_rule))

    return rules_dir

def test_linter_with_valid_config(valid_config, temp_rules_dir):
    config = LinterConfig(rules_directory=str(temp_rules_dir))
    linter = create_configured_linter(config)
    errors = linter.lint(valid_config)
    assert not errors, f"Expected no errors but got: {errors}"

def test_linter_with_invalid_config(invalid_config, temp_rules_dir):
    config = LinterConfig(rules_directory=str(temp_rules_dir))
    linter = create_configured_linter(config)
    errors = linter.lint(invalid_config)

    # Check for various expected errors
    assert len(errors) > 0
    error_messages = [e.message for e in errors]

    assert any("Invalid pin format" in msg for msg in error_messages)
    assert any("should be lowercase" in msg for msg in error_messages)

def test_ignore_rules(invalid_config, temp_rules_dir):
    config = LinterConfig(
        rules_directory=str(temp_rules_dir),
        ignore_rules=["naming-conventions"]
    )
    linter = create_configured_linter(config)
    errors = linter.lint(invalid_config)

    # Should only see pin format errors, not naming convention errors
    error_messages = [e.message for e in errors]

    # Should see pin format errors
    assert any("Invalid pin format" in msg for msg in error_messages)

    # Should NOT see naming convention errors
    assert not any("should be lowercase" in msg for msg in error_messages)

def test_warning_as_error(invalid_config, temp_rules_dir):
    config = LinterConfig(
        rules_directory=str(temp_rules_dir),
        warning_as_error=True
    )
    linter = create_configured_linter(config)
    errors = linter.lint(invalid_config)

    # All errors should have severity "error"
    assert all(e.severity == "error" for e in errors)

def test_custom_rule(valid_config):
    def custom_check(config: ConfigFile) -> List[LintError]:
        return [LintError("Custom error", "test_section")]

    custom_rule = LintRule(
        custom_check,
        "custom-rule",
        RuleDocumentation("Test rule", [], []),
        RuleCategory.STYLE
    )

    linter = KlipperLinter()
    linter.add_rule(custom_rule)
    errors = linter.lint(valid_config)

    assert len(errors) == 1
    assert errors[0].message == "Custom error"

import pytest
from klipperlint.klipper_config_parser import ConfigFile, ConfigSection
from klipperlint.klipper_config_linter import (
    KlipperLinter, LintError, LintRule, RuleCategory, RuleDocumentation,
    check_pin_syntax, check_required_sections, check_value_ranges,
    check_section_dependencies, check_naming_conventions, check_stepper_consistency,
    create_configured_linter, LinterConfig
)

# Test fixtures
@pytest.fixture
def valid_config():
    return ConfigFile(
        sections={
            "printer": ConfigSection("printer", {
                "kinematics": "cartesian",
                "max_velocity": "300",
                "max_accel": "3000"
            }),
            "stepper_x": ConfigSection("stepper_x", {
                "step_pin": "PF0",
                "dir_pin": "PF1",
                "enable_pin": "!PD7",
                "microsteps": "16"
            }),
            "stepper_y": ConfigSection("stepper_y", {
                "step_pin": "PF2",
                "dir_pin": "PF3",
                "enable_pin": "!PD5",
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
                "enable_pin": "not_a_pin",
                "microsteps": "1000"  # Out of range
            }),
            "Stepper_Y": ConfigSection("Stepper_Y", {  # Invalid casing
                "step_pin": "PF2",
                "microsteps": "32"  # Inconsistent with stepper_x
            })
        },
        includes=[]
    )

def test_pin_syntax_check():
    config = ConfigFile(
        sections={
            "stepper_x": ConfigSection("stepper_x", {
                "step_pin": "PF0",      # Valid
                "dir_pin": "invalid",    # Invalid
                "enable_pin": "!PD7"     # Valid
            })
        },
        includes=[]
    )

    errors = check_pin_syntax(config)
    assert len(errors) == 1
    assert errors[0].section == "stepper_x"
    assert errors[0].option == "dir_pin"
    assert "Invalid pin format" in errors[0].message

def test_required_sections():
    # Test missing printer section
    config = ConfigFile(
        sections={"stepper_x": ConfigSection("stepper_x", {})},
        includes=[]
    )

    errors = check_required_sections(config)
    assert len(errors) == 1
    assert errors[0].section == "printer"
    assert "Missing required section" in errors[0].message

def test_value_ranges():
    config = ConfigFile(
        sections={
            "printer": ConfigSection("printer", {
                "max_velocity": "2000",  # Out of range
                "max_accel": "invalid",  # Not a number
                "microsteps": "16"       # Valid
            })
        },
        includes=[]
    )

    errors = check_value_ranges(config)
    assert len(errors) == 2
    assert any("outside valid range" in e.message for e in errors)
    assert any("Invalid numeric value" in e.message for e in errors)

def test_section_dependencies():
    config = ConfigFile(
        sections={
            "extruder": ConfigSection("extruder", {})
            # Missing heater_bed section
        },
        includes=[]
    )

    errors = check_section_dependencies(config)
    assert len(errors) == 1
    assert errors[0].severity == "warning"
    assert "heater_bed" in errors[0].message

def test_naming_conventions():
    config = ConfigFile(
        sections={
            "Printer": ConfigSection("Printer", {}),
            "STEPPER_X": ConfigSection("STEPPER_X", {})
        },
        includes=[]
    )

    errors = check_naming_conventions(config)
    assert len(errors) == 2
    assert all(e.severity == "warning" for e in errors)
    assert all("lowercase" in e.message for e in errors)

def test_stepper_consistency():
    config = ConfigFile(
        sections={
            "stepper_x": ConfigSection("stepper_x", {"microsteps": "16"}),
            "stepper_y": ConfigSection("stepper_y", {"microsteps": "32"}),
            "stepper_z": ConfigSection("stepper_z", {"microsteps": "16"})
        },
        includes=[]
    )

    errors = check_stepper_consistency(config)
    assert len(errors) == 1
    assert errors[0].section == "stepper_y"
    assert "Inconsistent microsteps" in errors[0].message

def test_linter_configuration():
    config = LinterConfig(
        ignore_rules=["pin-syntax"],
        warning_as_error=True,
        custom_ranges={"max_velocity": (0, 2000)}
    )

    linter = create_configured_linter(config)
    # Verify pin-syntax rule is not included
    rule_names = [rule.name for rule in linter.rules]
    assert "pin-syntax" not in rule_names

def test_full_linter_valid_config(valid_config):
    linter = create_configured_linter(LinterConfig())
    errors = linter.lint(valid_config)
    assert not errors, f"Expected no errors but got: {errors}"

def test_full_linter_invalid_config(invalid_config):
    linter = create_configured_linter(LinterConfig())
    errors = linter.lint(invalid_config)

    # Check for various expected errors
    assert len(errors) > 0
    error_messages = [e.message for e in errors]

    assert any("Invalid pin format" in msg for msg in error_messages)
    assert any("Missing required section: printer" in msg for msg in error_messages)
    assert any("outside valid range" in msg for msg in error_messages)
    assert any("lowercase" in msg for msg in error_messages)

def test_rule_documentation():
    doc = RuleDocumentation(
        description="Test rule",
        examples=["Good example", "Bad example"],
        fix_suggestions=["How to fix"]
    )

    rule = LintRule(
        check_pin_syntax,
        "pin-syntax",
        doc,
        RuleCategory.SYNTAX
    )

    assert rule.docs.description == "Test rule"
    assert len(rule.docs.examples) == 2
    assert rule.category == RuleCategory.SYNTAX

def test_rule_categories():
    # Test that all rules are assigned to appropriate categories
    linter = create_configured_linter(LinterConfig())

    for rule in linter.rules:
        assert isinstance(rule.category, RuleCategory)
        assert rule.category in RuleCategory

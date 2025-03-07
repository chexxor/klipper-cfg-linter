import pytest
from pathlib import Path
from textwrap import dedent
import yaml

from klipperlint.rule_loader import load_rules_from_directory, create_check_function
from klipperlint.klipper_config_parser import ConfigFile, ConfigSection
from klipperlint.klipper_config_linter import RuleCategory

# Test fixtures
@pytest.fixture
def temp_rules_dir(tmp_path):
    """Creates a temporary directory with test rule files"""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    return rules_dir

@pytest.fixture
def required_sections_rule(temp_rules_dir):
    """Creates a test rule file for required sections"""
    rule_content = """
        name: required-sections
        category: dependency
        description: "Check that required sections are present"
        examples:
          valid:
            - |
              [printer]
              kinematics: cartesian
          invalid:
            - |
              [stepper_x]
              # Missing printer section
        conditions:
          - type: "required_sections"
            sections:
              - "printer"
            error_message: "Missing required section: {section}"
            severity: "error"
    """
    rule_file = temp_rules_dir / "required_sections.yaml"
    rule_file.write_text(dedent(rule_content))
    return yaml.safe_load(dedent(rule_content))

@pytest.fixture
def naming_conventions_rule(temp_rules_dir):
    """Creates a test rule file for naming conventions"""
    rule_content = """
        name: naming-conventions
        category: style
        description: "Check that section names follow naming conventions"
        examples:
          valid:
            - "[stepper_x]"
          invalid:
            - "[Stepper_X]"
        conditions:
          - type: "section_name_pattern"
            pattern: "^[a-z][a-z0-9_]*$"
            error_message: "Section name should be lowercase: {section}"
            severity: "warning"
    """
    rule_file = temp_rules_dir / "naming_conventions.yaml"
    rule_file.write_text(dedent(rule_content))
    return yaml.safe_load(dedent(rule_content))

@pytest.fixture
def valid_config():
    """Creates a valid test config"""
    return ConfigFile(
        sections={
            "printer": ConfigSection("printer", {"kinematics": "cartesian"}),
            "stepper_x": ConfigSection("stepper_x", {"step_pin": "PF0"})
        },
        includes=[]
    )

@pytest.fixture
def invalid_config():
    """Creates an invalid test config"""
    return ConfigFile(
        sections={
            "Stepper_X": ConfigSection("Stepper_X", {"step_pin": "PF0"})
        },
        includes=[]
    )

def test_load_rules_from_directory(temp_rules_dir, required_sections_rule, naming_conventions_rule):
    """Test loading multiple rules from a directory"""
    rules = load_rules_from_directory(str(temp_rules_dir))

    assert len(rules) == 2

    # Check that rules were loaded correctly
    rule_names = {rule.name for rule in rules}
    assert "required-sections" in rule_names
    assert "naming-conventions" in rule_names

    # Check rule categories
    for rule in rules:
        if rule.name == "required-sections":
            assert rule.category == RuleCategory.DEPENDENCY
        elif rule.name == "naming-conventions":
            assert rule.category == RuleCategory.STYLE

def test_required_sections_rule(required_sections_rule):
    """Test the required sections rule"""
    check_func = create_check_function(required_sections_rule)

    # Test with missing printer section
    config = ConfigFile(
        sections={"stepper_x": ConfigSection("stepper_x", {})},
        includes=[]
    )
    errors = check_func(config)

    assert len(errors) == 1
    assert errors[0].message == "Missing required section: printer"
    assert errors[0].severity == "error"

    # Test with all required sections
    config = ConfigFile(
        sections={"printer": ConfigSection("printer", {})},
        includes=[]
    )
    errors = check_func(config)
    assert len(errors) == 0

def test_naming_conventions_rule(naming_conventions_rule):
    """Test the naming conventions rule"""
    check_func = create_check_function(naming_conventions_rule)

    # Test with invalid section names
    config = ConfigFile(
        sections={
            "Stepper_X": ConfigSection("Stepper_X", {}),
            "EXTRUDER": ConfigSection("EXTRUDER", {})
        },
        includes=[]
    )
    errors = check_func(config)

    assert len(errors) == 2
    assert all(error.severity == "warning" for error in errors)
    assert "should be lowercase" in errors[0].message

    # Test with valid section names
    config = ConfigFile(
        sections={
            "stepper_x": ConfigSection("stepper_x", {}),
            "extruder": ConfigSection("extruder", {})
        },
        includes=[]
    )
    errors = check_func(config)
    assert len(errors) == 0

def test_rule_documentation(temp_rules_dir, required_sections_rule):
    """Test that rule documentation is loaded correctly"""
    rules = load_rules_from_directory(str(temp_rules_dir))
    rule = next(r for r in rules if r.name == "required-sections")

    assert rule.docs.description == "Check that required sections are present"
    assert len(rule.docs.examples) == 2
    assert any("[printer]" in example for example in rule.docs.examples)

def test_invalid_rule_file(temp_rules_dir):
    """Test handling of invalid rule files"""
    invalid_rule = """
        name: invalid-rule
        category: not_a_category
        description: "This rule is invalid"
        conditions: []
    """
    rule_file = temp_rules_dir / "invalid_rule.yaml"
    rule_file.write_text(dedent(invalid_rule))

    with pytest.raises(ValueError) as exc_info:
        load_rules_from_directory(str(temp_rules_dir))
    assert "Invalid category" in str(exc_info.value)

def test_missing_required_fields(temp_rules_dir):
    """Test handling of rule files with missing required fields"""
    incomplete_rule = """
        name: incomplete-rule
        category: style
        # Missing description and conditions
    """
    rule_file = temp_rules_dir / "incomplete_rule.yaml"
    rule_file.write_text(dedent(incomplete_rule))

    with pytest.raises(KeyError) as exc_info:
        load_rules_from_directory(str(temp_rules_dir))
    assert "Missing required field" in str(exc_info.value)

def test_optional_fields(temp_rules_dir):
    """Test that optional fields are handled correctly"""
    minimal_rule = """
        name: minimal-rule
        category: style
        description: "A minimal rule"
        conditions:
          - type: "section_name_pattern"
            pattern: "^[a-z]+$"
            error_message: "Invalid section name"
            severity: "warning"
    """
    rule_file = temp_rules_dir / "minimal_rule.yaml"
    rule_file.write_text(dedent(minimal_rule))

    rules = load_rules_from_directory(str(temp_rules_dir))
    assert len(rules) == 1
    assert rules[0].name == "minimal-rule"
    assert isinstance(rules[0].docs.examples, list)
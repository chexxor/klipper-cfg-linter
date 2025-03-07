import pytest
from klipperlint.klipper_config_parser import (
    ConfigSection, ConfigFile, ParsedConfig, ValidationResult,
    parse_line, extract_section_name, parse_include_directive,
    parse_config_section, parse_config_file, validate_value,
    validate_config, generate_autosave_content, AUTOSAVE_HEADER,
    ConfigError
)

# Test data
SAMPLE_CONFIG = """
[printer]
kinematics: cartesian
max_velocity: 300
max_accel: 3000

[stepper_x]
step_pin: PF0
dir_pin: PF1
enable_pin: !PD7
microsteps: 16

# This is a comment
[include other_config.cfg]

[extruder]
step_pin: PA4
dir_pin: !PA6
enable_pin: !PA2
microsteps: 16
"""

MOCK_OTHER_CONFIG = """
[stepper_y]
step_pin: PF2
dir_pin: PF3
enable_pin: !PD5
microsteps: 16
"""

MOCK_FILES = {
    "test.cfg": SAMPLE_CONFIG,
    "other_config.cfg": MOCK_OTHER_CONFIG,
}

def test_parse_line():
    # Test basic line parsing
    content, comment = parse_line("option: value  # comment")
    assert content == "option: value"
    assert comment == "# comment"

    # Test line without comment
    content, comment = parse_line("option: value")
    assert content == "option: value"
    assert comment is None

    # Test empty line
    content, comment = parse_line("   ")
    assert content == ""
    assert comment is None

    # Test comment-only line
    content, comment = parse_line("# just a comment")
    assert content == ""
    assert comment == "# just a comment"

def test_extract_section_name():
    # Test valid section
    assert extract_section_name("[section_name]") == "section_name"

    # Test section with spaces
    assert extract_section_name("[ section_name ]") == "section_name"

    # Test invalid sections
    assert extract_section_name("section_name") is None
    assert extract_section_name("[incomplete") is None
    assert extract_section_name("incomplete]") is None

def test_parse_include_directive():
    # Test valid include
    assert parse_include_directive("[include config.cfg]") == "config.cfg"

    # Test include with spaces
    assert parse_include_directive("[include  config.cfg  ]") == "config.cfg"

    # Test invalid includes
    assert parse_include_directive("[printer]") is None
    assert parse_include_directive("include config.cfg") is None

def test_parse_config_section():
    config_lines = [
        "[printer]",
        "kinematics: cartesian",
        "max_velocity: 300",
        "# Comment line",
        "max_accel: 3000"
    ]

    section = parse_config_section(config_lines)
    assert section.name == "printer"
    assert section.options == {
        "kinematics": "cartesian",
        "max_velocity": "300",
        "max_accel": "3000"
    }

def test_validate_value():
    constraints = {
        "minval": 0,
        "maxval": 100,
        "above": 10,
        "below": 90
    }

    # Test valid value
    result = validate_value(50, constraints)
    assert result.is_valid
    assert not result.errors

    # Test invalid value
    result = validate_value(-1, constraints)
    assert not result.is_valid
    assert len(result.errors) == 2  # Should fail minval and above constraints

def test_validate_config():
    config = ConfigFile(
        sections={
            "printer": ConfigSection("printer", {"kinematics": "cartesian"}),
            "invalid_section": ConfigSection("invalid_section", {})
        },
        includes=[]
    )

    valid_sections = {"printer", "stepper_x", "extruder"}
    result = validate_config(config, valid_sections)

    assert not result.is_valid
    assert len(result.errors) == 1
    assert "Invalid section: invalid_section" in result.errors[0]

def test_generate_autosave_content():
    config = ConfigFile(
        sections={
            "printer": ConfigSection("printer", {
                "position_endstop": "0.0",
                "position_max": "200"
            })
        },
        includes=[]
    )

    content = generate_autosave_content(config)

    assert AUTOSAVE_HEADER in content
    assert "[printer]" in content
    assert "#*# position_endstop = 0.0" in content
    assert "#*# position_max = 200" in content

def test_config_file_immutability():
    """Test that ConfigFile and its contents are truly immutable"""
    config = ConfigFile(
        sections={"printer": ConfigSection("printer", {"option": "value"})},
        includes=[]
    )

    # Test that sections dictionary is immutable
    with pytest.raises(TypeError):
        config.sections["new_section"] = ConfigSection("new", {})

    # Test that includes list is immutable
    with pytest.raises(AttributeError):
        config.includes.append("new_include.cfg")

    # Test that section options are immutable
    with pytest.raises(TypeError):
        config.sections["printer"].options["new_option"] = "value"

def test_parse_config_with_recursive_include():
    # Test that recursive includes are detected
    with pytest.raises(ConfigError) as exc_info:
        parse_config_file(
            "[include test.cfg]",
            "test.cfg",
            visited={"test.cfg"}
        )
    assert "Recursive include" in str(exc_info.value)

def test_parse_config_file_with_includes():
    """Test parsing a config file with includes using mock files"""
    config = parse_config_file(SAMPLE_CONFIG, "test.cfg", mock_files=MOCK_FILES)

    # Check that all sections are present
    assert "printer" in config.sections
    assert "stepper_x" in config.sections
    assert "stepper_y" in config.sections  # From included file
    assert "extruder" in config.sections

    # Check specific values from included file
    stepper_y = config.sections["stepper_y"]
    assert stepper_y.options["step_pin"] == "PF2"
    assert stepper_y.options["dir_pin"] == "PF3"

    # Check includes list
    assert "other_config.cfg" in config.includes

def test_include_file_not_found():
    """Test that missing includes raise appropriate error"""
    config_with_bad_include = """
    [printer]
    kinematics: cartesian

    [include nonexistent.cfg]
    """

    with pytest.raises(ConfigError) as exc_info:
        parse_config_file(config_with_bad_include, "test.cfg", mock_files={})
    assert "does not exist" in str(exc_info.value)

def test_recursive_include():
    """Test that recursive includes are detected"""
    recursive_config = {
        "main.cfg": "[include sub.cfg]",
        "sub.cfg": "[include main.cfg]"
    }

    with pytest.raises(ConfigError) as exc_info:
        parse_config_file(recursive_config["main.cfg"], "main.cfg",
                         mock_files=recursive_config)
    assert "Recursive include" in str(exc_info.value)
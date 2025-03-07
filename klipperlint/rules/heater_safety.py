from dataclasses import dataclass
from typing import Dict, List, Optional
import re

from klipperlint.klipper_config_parser import ConfigFile, ConfigSection
from klipperlint.types import LintError, LintRule, RuleCategory, RuleDocumentation

# Clear documentation of valid configurations
VALID_HEATER_CONFIG = """
[extruder]
heater_pin: PA1
sensor_type: EPCOS 100K B57560G104F
sensor_pin: PF0
control: pid
pid_Kp: 22.2
pid_Ki: 1.08
pid_Kd: 114
min_temp: 0
max_temp: 250
min_extrude_temp: 170
max_power: 1.0
"""

# Constants for validation
HEATER_SECTIONS = [r"^extruder\d*$", r"^heater_bed$"]
REQUIRED_OPTIONS = ["heater_pin", "sensor_type", "sensor_pin", "min_temp", "max_temp"]
PID_OPTIONS = ["pid_Kp", "pid_Ki", "pid_Kd"]

SENSOR_TEMP_LIMITS = {
    "EPCOS 100K B57560G104F": 280,
    "ATC Semitec 104GT-2": 300,
    "SliceEngineering 450": 450
}

def check_heater_safety(config: ConfigFile) -> List[LintError]:
    """Validates heater configuration including safety limits, sensors, and PWM settings."""
    errors = []

    # Find all heater sections
    heater_sections = []
    for pattern in HEATER_SECTIONS:
        heater_sections.extend([
            (name, section) for name, section in config.sections.items()
            if re.match(pattern, name)
        ])

    for section_name, section in heater_sections:
        # Check required options
        errors.extend(check_required_options(section_name, section))

        # Check PID configuration if enabled
        if section.options.get("control") == "pid":
            errors.extend(check_pid_config(section_name, section))

        # Check temperature limits
        errors.extend(check_temperature_limits(section_name, section))

        # Check power settings
        errors.extend(check_power_settings(section_name, section))

        # Check cooling configuration
        errors.extend(check_cooling_config(config, section_name))

    # Check MCU PWM frequency if heaters are present
    if heater_sections and "mcu" in config.sections:
        errors.extend(check_pwm_frequency(config.sections["mcu"]))

    return errors

def check_required_options(section_name: str, section: ConfigSection) -> List[LintError]:
    """Validates that all required heater options are present."""
    errors = []
    for option in REQUIRED_OPTIONS:
        if option not in section.options:
            errors.append(LintError(
                f"Missing required heater option: {option}",
                section_name,
                option,
                "error"
            ))
    return errors

def check_pid_config(section_name: str, section: ConfigSection) -> List[LintError]:
    """Validates PID control settings."""
    errors = []
    for pid_param in PID_OPTIONS:
        if pid_param not in section.options:
            errors.append(LintError(
                f"PID control requires {pid_param}",
                section_name,
                pid_param,
                "error"
            ))
    return errors

def check_temperature_limits(section_name: str, section: ConfigSection) -> List[LintError]:
    """Validates temperature limits based on sensor type."""
    errors = []
    sensor_type = section.options.get("sensor_type")
    if sensor_type in SENSOR_TEMP_LIMITS:
        try:
            max_temp = float(section.options.get("max_temp", "0"))
            limit = SENSOR_TEMP_LIMITS[sensor_type]
            if max_temp > limit:
                errors.append(LintError(
                    f"Max temperature {max_temp} exceeds safe value ({limit}) for sensor {sensor_type}",
                    section_name,
                    "max_temp",
                    "error"
                ))
        except ValueError:
            errors.append(LintError(
                f"Invalid max_temp value: {section.options.get('max_temp')}",
                section_name,
                "max_temp",
                "error"
            ))
    return errors

def check_power_settings(section_name: str, section: ConfigSection) -> List[LintError]:
    """Validates heater power settings."""
    errors = []
    try:
        max_power = float(section.options.get("max_power", "1.0"))
        if not 0.0 <= max_power <= 1.0:
            errors.append(LintError(
                f"max_power must be between 0 and 1, got {max_power}",
                section_name,
                "max_power",
                "error"
            ))
    except ValueError:
        errors.append(LintError(
            f"Invalid max_power value: {section.options.get('max_power')}",
            section_name,
            "max_power",
            "error"
        ))
    return errors

def check_cooling_config(config: ConfigFile, heater_section: str) -> List[LintError]:
    """Validates cooling configuration for heaters."""
    if not heater_section.startswith("extruder"):
        return []  # Only check cooling for extruders

    errors = []
    has_cooling = False

    # Check for any type of cooling fan
    for section_name in config.sections:
        if section_name in ["fan", f"heater_fan {heater_section}"]:
            has_cooling = True
            break

    if not has_cooling:
        errors.append(LintError(
            f"Extruder {heater_section} requires at least one cooling fan",
            heater_section,
            severity="error"
        ))

    return errors

def check_pwm_frequency(mcu_section: ConfigSection) -> List[LintError]:
    """Validates MCU PWM frequency for heater control."""
    errors = []
    try:
        freq = float(mcu_section.options.get("pwm_frequency", "0"))
        if freq < 100:  # Minimum safe PWM frequency for heaters
            errors.append(LintError(
                f"PWM frequency must be at least 100Hz for heater control, got {freq}Hz",
                "mcu",
                "pwm_frequency",
                "error"
            ))
    except ValueError:
        errors.append(LintError(
            f"Invalid PWM frequency: {mcu_section.options.get('pwm_frequency')}",
            "mcu",
            "pwm_frequency",
            "error"
        ))
    return errors

# Create the rule
heater_safety_rule = LintRule(
    check_heater_safety,
    "heater-safety",
    RuleDocumentation(
        "Validates heater configuration including safety limits, sensors, and PWM settings",
        [VALID_HEATER_CONFIG],
        ["Ensure all required options are present",
         "Check sensor type temperature limits",
         "Configure appropriate cooling"]
    ),
    RuleCategory.SAFETY
)
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Callable
import yaml
import glob
import os
import re
from pathlib import Path

from klipperlint.klipper_config_parser import ConfigFile
from klipperlint.types import LintError, LintRule, RuleCategory, RuleDocumentation

@dataclass
class RuleCondition:
    type: str
    applies_to: str
    error_message: str
    severity: str
    # Additional fields based on condition type
    pattern: Optional[str] = None
    value_pattern: Optional[str] = None
    options: Optional[List[str]] = None
    ranges: Optional[Dict[str, List[float]]] = None

class YamlRule:
    def __init__(self, yaml_data: Dict[str, Any]):
        self.name = yaml_data['name']
        self.category = RuleCategory[yaml_data['category'].upper()]
        self.description = yaml_data['description']
        self.examples = yaml_data.get('examples', {})
        self.conditions = [
            RuleCondition(**condition)
            for condition in yaml_data['conditions']
        ]

    def create_check_function(self) -> Callable[[ConfigFile], List[LintError]]:
        def check_config(config: ConfigFile) -> List[LintError]:
            errors = []
            for condition in self.conditions:
                if condition.type == "regex_match":
                    errors.extend(self._check_regex(config, condition))
                elif condition.type == "numeric_range":
                    errors.extend(self._check_range(config, condition))
                elif condition.type == "required_sections":
                    for section in condition['sections']:
                        if section not in config.sections:
                            errors.append(LintError(
                                condition['error_message'].format(section=section),
                                section,
                                severity=condition['severity']
                            ))
                elif condition.type == "section_name_pattern":
                    pattern = re.compile(condition.pattern)
                    for section_name in config.sections:
                        if not pattern.match(section_name):
                            errors.append(LintError(
                                condition.error_message.format(section=section_name),
                                section_name,
                                severity=condition.severity
                            ))
                elif condition.type == "section_dependency":
                    if condition['if_section'] in config.sections:
                        if condition['requires_section'] not in config.sections:
                            errors.append(LintError(
                                condition['error_message'],
                                condition['if_section'],
                                severity=condition['severity']
                            ))
                elif condition.type == "option_consistency":
                    sections = [s for s in config.sections
                              if re.match(condition.pattern, s)]
                    if sections:
                        first = config.sections[sections[0]]
                        for option in condition.options:
                            first_value = first.options.get(option)
                            for section in sections[1:]:
                                current = config.sections[section]
                                if current.options.get(option) != first_value:
                                    errors.append(LintError(
                                        condition.error_message.format(
                                            option=option,
                                            section=section
                                        ),
                                        section,
                                        option,
                                        severity=condition.severity
                                    ))
            return errors
        return check_config

    def _check_regex(self, config: ConfigFile, condition: RuleCondition) -> List[LintError]:
        errors = []
        option_pattern = re.compile(condition.pattern)
        value_pattern = re.compile(condition.value_pattern)

        for section_name, section in config.sections.items():
            for option, value in section.options.items():
                if option_pattern.match(option):
                    if not value_pattern.match(value):
                        errors.append(LintError(
                            condition.error_message.format(value=value),
                            section_name,
                            option,
                            condition.severity
                        ))
        return errors

    def _check_range(self, config: ConfigFile, condition: RuleCondition) -> List[LintError]:
        errors = []
        for section_name, section in config.sections.items():
            for option, value in section.options.items():
                if option in condition.options:
                    try:
                        val = float(value)
                        min_val, max_val = condition.ranges[option]
                        if not min_val <= val <= max_val:
                            errors.append(LintError(
                                condition.error_message.format(
                                    option=option,
                                    value=val,
                                    min=min_val,
                                    max=max_val
                                ),
                                section_name,
                                option,
                                condition.severity
                            ))
                    except ValueError:
                        errors.append(LintError(
                            f"Invalid numeric value for {option}: {value}",
                            section_name,
                            option,
                            condition.severity
                        ))
        return errors

def create_check_function(rule_data: Dict[str, Any]) -> Callable[[ConfigFile], List[LintError]]:
    """Creates a check function based on the rule type"""

    def check_config(config: ConfigFile) -> List[LintError]:
        errors = []
        for condition in rule_data['conditions']:
            condition_type = condition['type']

            if condition_type == "required_sections":
                # Check for required sections
                for section in condition['sections']:
                    if section not in config.sections:
                        errors.append(LintError(
                            condition['error_message'].format(section=section),
                            section,
                            severity=condition['severity']
                        ))

            elif condition_type == "regex_match":
                # For options that match a pattern (like *_pin)
                option_pattern = re.compile(condition['pattern'])
                value_pattern = re.compile(condition['value_pattern'])

                for section_name, section in config.sections.items():
                    for option, value in section.options.items():
                        if option_pattern.match(option):
                            if not value_pattern.match(value):
                                errors.append(LintError(
                                    condition['error_message'].format(value=value),
                                    section_name,
                                    option,
                                    condition['severity']
                                ))

            elif condition_type == "section_name_pattern":
                # For section name validation
                pattern = re.compile(condition['pattern'])
                for section_name in config.sections:
                    if not pattern.match(section_name):
                        errors.append(LintError(
                            condition['error_message'].format(section=section_name),
                            section_name,
                            severity=condition['severity']
                        ))

            elif condition_type == "section_dependency":
                # For section dependencies
                if condition['if_section'] in config.sections:
                    if condition['requires_section'] not in config.sections:
                        errors.append(LintError(
                            condition['error_message'],
                            condition['if_section'],
                            severity=condition['severity']
                        ))

            elif condition_type == "option_consistency":
                # For checking consistency across sections
                sections = [s for s in config.sections
                          if re.match(condition['section_pattern'], s)]
                if sections:
                    first = config.sections[sections[0]]
                    for option in condition['options']:
                        first_value = first.options.get(option)
                        for section in sections[1:]:
                            current = config.sections[section]
                            if current.options.get(option) != first_value:
                                errors.append(LintError(
                                    condition['error_message'].format(
                                        option=option,
                                        section=section
                                    ),
                                    section,
                                    option,
                                    condition['severity']
                                ))
            else:
                raise ValueError(f"Unknown condition type: {condition_type}")

        return errors

    return check_config

def validate_rule_data(rule_data: Dict[str, Any]) -> None:
    """Validates rule data and raises appropriate errors"""
    required_fields = ['name', 'category', 'description', 'conditions']
    for field in required_fields:
        if field not in rule_data:
            raise KeyError(f"Missing required field: {field}")

    # Validate category
    try:
        RuleCategory[rule_data['category'].upper()]
    except KeyError:
        raise ValueError(f"Invalid category: {rule_data['category']}")

def load_rules_from_directory(directory: str) -> List[LintRule]:
    """Loads all YAML rules from a directory"""
    rules = []
    rule_dir = Path(directory)

    for yaml_file in rule_dir.glob("*.yaml"):
        with open(yaml_file) as f:
            rule_data = yaml.safe_load(f)

        # Validate rule data
        validate_rule_data(rule_data)

        # Handle optional fields
        examples = rule_data.get('examples', {'valid': [], 'invalid': []})
        example_strings = [f"{k}:\n{v}" for k, v in examples.items()]

        rules.append(LintRule(
            create_check_function(rule_data),
            rule_data['name'],
            RuleDocumentation(
                rule_data['description'],
                example_strings,
                []  # Fix suggestions are optional
            ),
            RuleCategory[rule_data['category'].upper()]
        ))

    return rules
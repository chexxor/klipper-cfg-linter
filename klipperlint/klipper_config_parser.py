# Purely function version of the Klipper configfile.py file.
# This translation was done to make it easier for the author, who
# is not a python developer, to make it easier to test and modify.
#
# The original file is located at:
# https://github.com/Klipper3d/klipper/blob/f119e96e8fb7b752052930aac0daa4c0721d561d/klippy/configfile.py
# The original file is covered by the GNU GPLv3 license.
from typing import Dict, List, Tuple, Any, Optional, Set, Mapping
from dataclasses import dataclass
from types import MappingProxyType
import os, glob

class ConfigError(Exception):
    """Base class for config parsing errors"""
    pass

# Core data types
@dataclass(frozen=True)
class ConfigSection:
    name: str
    options: Mapping[str, str]

    def __init__(self, name: str, options: Dict[str, str]):
        # We need to use object.__setattr__ because the class is frozen
        object.__setattr__(self, 'name', name)
        object.__setattr__(self, 'options', MappingProxyType(options))

@dataclass(frozen=True)
class ConfigFile:
    sections: Mapping[str, ConfigSection]
    includes: Tuple[str, ...]

    def __init__(self, sections: Dict[str, ConfigSection], includes: List[str]):
        object.__setattr__(self, 'sections', MappingProxyType(sections))
        object.__setattr__(self, 'includes', tuple(includes))

@dataclass(frozen=True)
class ParsedConfig:
    regular_config: ConfigFile
    autosave_config: Optional[ConfigFile]
    access_tracking: Dict[Tuple[str, str], Any]

@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    errors: List[str]

# Pure functions for file operations
def read_file_content(filename: str, mock_files: Dict[str, str] = None) -> str:
    """Reads a file and returns its contents, handling line endings

    Args:
        filename: Path to the file to read
        mock_files: Optional dictionary of mock files for testing {filename: content}
    """
    if mock_files is not None and filename in mock_files:
        return mock_files[filename].replace('\r\n', '\n')

    try:
        with open(filename, 'r') as f:
            return f.read().replace('\r\n', '\n')
    except Exception as e:
        raise ConfigError(f"Unable to open config file {filename}: {str(e)}")

def write_file_content(filename: str, content: str) -> None:
    """Writes content to a file"""
    with open(filename, 'w') as f:
        f.write(content)

# Pure functions for parsing
def parse_line(line: str) -> Tuple[str, Optional[str]]:
    """Splits a line into content and comment"""
    pos = line.find('#')
    if pos >= 0:
        return line[:pos].strip(), line[pos:].strip()
    return line.strip(), None

def extract_section_name(line: str) -> Optional[str]:
    """Extracts section name from a section header line"""
    if line.startswith('[') and line.endswith(']'):
        return line[1:-1].strip()
    return None

def parse_include_directive(line: str) -> Optional[str]:
    """Returns include path if line is an include directive"""
    section_name = extract_section_name(line)
    if section_name and section_name.startswith('include '):
        return section_name[8:].strip()
    return None

def resolve_includes(base_path: str, include_spec: str, mock_files: Dict[str, str] = None) -> List[str]:
    """Resolves include patterns to actual filenames

    Args:
        base_path: Base path for resolving relative includes
        include_spec: Include specification (can contain wildcards)
        mock_files: Optional dictionary of mock files for testing {filename: content}
    """
    include_glob = os.path.join(os.path.dirname(base_path), include_spec.strip())

    # If we have mock files, use them instead of filesystem
    if mock_files is not None:
        matching_files = [f for f in mock_files.keys()
                         if glob.fnmatch.fnmatch(f, include_glob)]
        if matching_files:
            return sorted(matching_files)
        if not glob.has_magic(include_glob):
            raise ConfigError(f"Include file '{include_glob}' does not exist")
        return []

    # Normal filesystem behavior
    filenames = glob.glob(include_glob)
    if not filenames and not glob.has_magic(include_glob):
        raise ConfigError(f"Include file '{include_glob}' does not exist")
    return sorted(filenames)

def parse_config_section(lines: List[str]) -> ConfigSection:
    """Parses a section of config lines into a ConfigSection"""
    options = {}
    section_name = None

    for line in lines:
        content, _ = parse_line(line)
        if not content:
            continue

        if content.startswith('['):
            section_name = extract_section_name(content)
            continue

        if section_name and ':' in content:
            key, value = map(str.strip, content.split(':', 1))
            options[key.lower()] = value

    return ConfigSection(section_name, options)

def parse_config_file(content: str, filename: str, visited: Set[str] = None,
                     mock_files: Dict[str, str] = None) -> ConfigFile:
    """Parses a config file into a ConfigFile structure"""
    if visited is None:
        visited = set()

    if filename in visited:
        raise ConfigError(f"Recursive include of config file '{filename}'")

    visited.add(filename)
    sections: Dict[str, ConfigSection] = {}
    includes: List[str] = []
    current_section_lines: List[str] = []

    def process_current_section():
        if current_section_lines:
            section = parse_config_section(current_section_lines)
            if section.name:
                sections[section.name.lower()] = section
            current_section_lines.clear()

    for line in content.split('\n'):
        content, _ = parse_line(line)
        include_path = parse_include_directive(content)

        if include_path:
            # Process current section before handling include
            process_current_section()

            # Handle include
            for include_file in resolve_includes(filename, include_path, mock_files):
                includes.append(include_file)
                include_content = read_file_content(include_file, mock_files)
                included_config = parse_config_file(include_content, include_file,
                                                 visited, mock_files)
                sections.update(included_config.sections)
                includes.extend(included_config.includes)
        else:
            # If we find a new section, process the current one first
            if content and content.startswith('['):
                process_current_section()
            current_section_lines.append(line)

    # Process final section
    process_current_section()

    visited.remove(filename)
    return ConfigFile(sections, includes)

# Validation functions
def validate_value(value: Any, constraints: Dict[str, Any]) -> ValidationResult:
    """Validates a value against a set of constraints"""
    errors = []

    if 'minval' in constraints and value < constraints['minval']:
        errors.append(f"Value {value} must be at least {constraints['minval']}")
    if 'maxval' in constraints and value > constraints['maxval']:
        errors.append(f"Value {value} must be at most {constraints['maxval']}")
    if 'above' in constraints and value <= constraints['above']:
        errors.append(f"Value {value} must be above {constraints['above']}")
    if 'below' in constraints and value >= constraints['below']:
        errors.append(f"Value {value} must be below {constraints['below']}")

    return ValidationResult(len(errors) == 0, errors)

def validate_config(config: ConfigFile, valid_sections: Set[str]) -> ValidationResult:
    """Validates an entire config file"""
    errors = []

    for section_name, section in config.sections.items():
        if section_name not in valid_sections:
            errors.append(f"Invalid section: {section_name}")

    return ValidationResult(len(errors) == 0, errors)


AUTOSAVE_HEADER = """
#*# <---------------------- SAVE_CONFIG ---------------------->
#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.
#*#
"""

    # Autosave functions
def generate_autosave_content(config: ConfigFile) -> str:
    """Generates autosave section content"""
    lines = [AUTOSAVE_HEADER]

    for section_name, section in sorted(config.sections.items()):
        lines.append(f"[{section_name}]")
        for key, value in sorted(section.options.items()):
            lines.append(f"#*# {key} = {value}")

    return "\n".join(lines)
"""
Tests for the Klipper configuration parser.
"""

from typing import Dict
import pytest
from pathlib import Path
from configparser import RawConfigParser
from klipperlint.grammar import parse_config, transform_config_tree

def test_empty_config():
    """Test parsing an empty configuration."""
    result = parse_config("")
    assert result == None
    # assert len(result.sections()) == 0
def test_basic_section():
    """Test parsing a basic section with a single setting."""
    config ="""[printer]
max_velocity: 300
"""
    result = parse_config(config)
    assert result is not None
    assert result.expr_name == 'config'
    assert result.children[0].children[0].expr_name == 'entry'
    assert result.children[0].children[0].children[0].expr_name == 'section'
    # assert result.children[0].children[0].children[2].expr_name == 'config_lines'
    # assert result.children[0].children[0].children[2].children[0].children[0].expr_name == 'config_line'
    # assert result.children[0].children[0].children[2].children[0].children[0].children[0].expr_name == 'name'
    # assert result.children[0].children[0].children[2].children[0].children[0].children[0].text == 'max_velocity'
    # assert result.children[0].children[0].children[2].children[0].children[0].children[2].children[0].expr_name == 'prop_value'
    # assert result.children[0].children[0].children[2].children[0].children[0].children[2].text == ' 300'
    result_tree = transform_config_tree(result)
    assert result_tree == [('printer', {'max_velocity': '300'})]


def test_invalid_syntax():
    """Test that invalid syntax raises appropriate errors."""
    with pytest.raises(Exception):
        parse_config("[incomplete section")

    with pytest.raises(Exception):
        parse_config("[section]\nkey without value")

def test_include_directive():
    """Test that include directive is parsed correctly."""
    config = """[include included.cfg]
    """
    result = parse_config(config)
    assert result is not None
    assert result.expr_name == 'config'
    assert result.children[0].children[0].expr_name == 'include_section'
    assert result.children[0].children[0].children[2].text == ' included.cfg'

def test_sample_config(sample_config: Path):
    """Test parsing the sample configuration file."""
    config_text = sample_config.read_text()
    result = parse_config(config_text)
    assert result is not None
    # Add more specific assertions based on sample config content

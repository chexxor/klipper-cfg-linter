"""
Tests for the Klipper configuration parser.
"""

from typing import Dict
import pytest
from pathlib import Path
from configparser import RawConfigParser
from klipperlint.grammar import parse_config

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
    assert result.meta.line == 1
    assert result.meta.column == 1
    assert result.meta.end_line == 2
    assert result.meta.end_column == 18
    assert result.children[0].meta.line == 1
    assert result.data.type == 'RULE'
    assert result.data.value == 'start'
    assert result.children[0].data.type == 'RULE'
    assert result.children[0].data.value == 'config'
    assert result.children[0].children[0].data.type == 'RULE'
    assert result.children[0].children[0].data.value == 'section'
    assert result.children[0].children[0].children[0].data.type == 'RULE'
    assert result.children[0].children[0].children[0].data.value == 'section_header'
    assert result.children[0].children[0].children[0].children[0].type == 'NAME'
    assert result.children[0].children[0].children[0].children[0].value == 'printer'
    assert result.children[0].children[0].children[1].data.type == 'RULE'
    assert result.children[0].children[0].children[1].data.value == 'config_lines'
    assert result.children[0].children[0].children[1].children[0].data.type == 'RULE'
    assert result.children[0].children[0].children[1].children[0].data.value == 'config_line'
    assert result.children[0].children[0].children[1].children[0].children[0].type == 'NAME'
    assert result.children[0].children[0].children[1].children[0].children[0].value == 'max_velocity'
    assert result.children[0].children[0].children[1].children[0].children[1].data.type == 'RULE'
    assert result.children[0].children[0].children[1].children[0].children[1].data.value == 'value'
    assert result.children[0].children[0].children[1].children[0].children[1].children[0].data.type == 'RULE'
    assert result.children[0].children[0].children[1].children[0].children[1].children[0].data.value == 'word'
    assert result.children[0].children[0].children[1].children[0].children[1].children[0].children[0].type == '__ANON_0'
    assert result.children[0].children[0].children[1].children[0].children[1].children[0].children[0].value == '300'


def test_sample_config(sample_config: Path):
    """Test parsing the sample configuration file."""
    config_text = sample_config.read_text()
    result = parse_config(config_text)
    assert isinstance(result, RawConfigParser)
    # Add more specific assertions based on sample config content

def test_invalid_syntax():
    """Test that invalid syntax raises appropriate errors."""
    with pytest.raises(Exception):
        parse_config("[incomplete section")

    with pytest.raises(Exception):
        parse_config("[section]\nkey without value")
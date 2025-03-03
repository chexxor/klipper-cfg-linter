"""
Lark grammar for parsing Klipper configuration files.
"""

from lark import Lark, v_args, Transformer
from typing import List, Tuple, Dict

# Klipper config grammar in Lark format
#  EPCOS 100K B57560G104F
# Test grammar changes here: https://www.lark-parser.org/ide/
KLIPPER_GRAMMAR = r"""
    start: config
    config: section*
    section: section_header config_lines
    section_header: "[" NAME "]"
    config_lines: config_line*
    config_line: NAME ":" value
    value: word+
    word: /[a-zA-Z0-9][a-zA-Z0-9_.\-\/]*/
    inline_comment: /#[^\n]*/
    COMMENT: /#[^\n]*/
    NEWLINE: /\r?\n/

    %import common.ESCAPED_STRING
    %import common.SIGNED_NUMBER
    %import common.WS
    %import common.CNAME -> NAME

    %ignore WS
    %ignore COMMENT
"""

@v_args(inline=True)
class ConfigTreeToJson(Transformer):
    def __init__(self):
        super().__init__()
        self.current_section = None

    def start(self, config):
        return config

    def config(self, *sections):
        return [s for s in sections if s is not None]

    def section(self, header, content):
        return (self.current_section, content)

    def section_header(self, name):
        self.current_section = str(name)
        return None

    def config_lines(self, *items):
        settings = {}
        for item in items:
            if isinstance(item, tuple):
                key, value = item
                settings[str(key)] = str(value)
        return settings

    def config_line(self, name, value):
        return (str(name), str(value))

    def value(self, *words):
        return ' '.join(str(w) for w in words if w is not None)

    def word(self, w):
        return str(w)

    def NEWLINE(self, _):
        return None

# Create the parser
parser = Lark(KLIPPER_GRAMMAR, start='start', parser='lalr', propagate_positions=True)

def parse_config(config_text: str):
    """Parse a Klipper configuration file using the Lark grammar."""
    if not config_text.strip():
        return None
    # Parse and transform to intermediate structure
    tree = parser.parse(config_text)
    return tree


def transform_config_tree(tree) -> List[Tuple[str, Dict[str, str]]]:
    """Transform a Klipper configuration tree into a list of section tuples."""
    transformer = ConfigTreeToJson()
    sections = transformer.transform(tree)
    return sections

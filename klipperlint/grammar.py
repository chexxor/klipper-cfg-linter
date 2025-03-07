"""
Parsimonious grammar for parsing Klipper configuration files.
"""

from parsimonious.grammar import Grammar
from parsimonious.nodes import NodeVisitor
from typing import List, Tuple, Dict

# Klipper config grammar in Parsimonious format
grammar = Grammar(
    r"""
    config      = (entry / emptyline)*
    entry       = section pair*

    section     = lpar word word? rpar ws? crlf
    pair        = key equal value? ws? crlf

    key         = word+
    value       = (word / quoted)+
    word        = ~r"[-\w]+"
    quoted      = ~'"[^\"]+"'
    equal       = ws? ":" ws?
    lpar        = "["
    rpar        = "]"
    ws          = ~r"[ \t\f\v]*"
    crlf        = ~r"\r?\n"
    emptyline   = ws+
    """
)

class IniVisitor(NodeVisitor):
    def __init__(self):
        self.current_line = 1

    def visit_crlf(self, node, visited_children):
        self.current_line += 1
        return node

    def visit_config(self, node, visited_children):
        """ Returns the overall output. """
        output = []
        for child in visited_children:
            output.append(child[0])
        return output

    def visit_entry(self, node, visited_children):
        """ Makes a dict of the section (as key) and the key/value pairs. """
        key, values = visited_children
        return [{key: dict(values)}]

    def visit_section(self, node, visited_children):
        """ Gets the section name. """
        _, section, *_ = visited_children
        return {"line_number": self.line_number, "section_name": section.text}

    def visit_pair(self, node, visited_children):
        """ Gets each key/value pair, returns a tuple. """
        key, _, value, *_ = node.children
        return {"line_number": self.line_number, "key": key.text, "value": value.text}

    def generic_visit(self, node, visited_children):
        """ The generic visit method. """
        # node.line_number = self.current_line
        return visited_children or node


def parse_config(config_text: str):
    """Parse a Klipper configuration file using the Parsimonious grammar."""
    if not config_text.strip():
        return None
    tree = grammar.parse(config_text)
    return tree

def transform_config_tree(tree) -> List[Tuple[str, Dict[str, str]]]:
    """Transform a Klipper configuration tree into a list of section tuples."""
    visitor = IniVisitor()
    sections = visitor.visit(tree)
    return sections

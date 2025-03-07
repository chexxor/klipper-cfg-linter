from dataclasses import dataclass, field
from typing import List, Optional, Callable
from enum import Enum
from klipperlint.klipper_config_parser import ConfigFile

@dataclass(frozen=True)
class LintFix:
    section: str
    option: Optional[str]
    old_value: str
    new_value: str

@dataclass(frozen=True)
class LintError:
    message: str
    section: str
    option: Optional[str] = None
    severity: str = "error"  # could be "error", "warning", "info"
    line_number: Optional[int] = None
    fix: Optional[LintFix] = None

class RuleCategory(Enum):
    SYNTAX = "syntax"
    SAFETY = "safety"
    CONSISTENCY = "consistency"
    STYLE = "style"
    DEPENDENCY = "dependency"

@dataclass(frozen=True)
class RuleDocumentation:
    description: str
    examples: List[str]
    fix_suggestions: List[str]

class LintRule:
    def __init__(self, check_func: Callable[[ConfigFile], List[LintError]],
                 name: str, docs: RuleDocumentation, category: RuleCategory):
        self.check = check_func
        self.name = name
        self.docs = docs
        self.category = category
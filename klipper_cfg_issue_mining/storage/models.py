from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

@dataclass
class ConfigIssue:
    source: str  # 'github', 'discord', 'reddit'
    title: str
    description: str
    solution: Optional[str]
    created_at: datetime
    labels: List[str]
    url: str
    impact_score: float = 0.0

@dataclass
class ConfigPattern:
    pattern_type: str  # 'error', 'warning', 'best_practice'
    description: str
    frequency: int
    examples: List[str]
    related_issues: List[str]
    suggested_rule: Optional[str] = None
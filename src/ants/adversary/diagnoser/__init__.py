"""Diagnoser: failed rollout -> Failure + Constraint. Rules now; the model diagnoser comes next.

Keeps System 1's v0 interface (`diagnose`, `signature`, `RULES`) at `ants.adversary.diagnoser`.
"""

from ants.adversary.diagnoser.rules import RULES, classify, diagnose, signature

__all__ = ["RULES", "classify", "diagnose", "signature"]

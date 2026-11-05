"""Diagnoser: failed rollout -> Failure + Constraint, by rules or by the model (`model.py`).

Keeps System 1's v0 interface (`diagnose`, `signature`, `RULES`) at `ants.adversary.diagnoser`.
"""

from ants.adversary.diagnoser.rules import RULES, classify, diagnose, signature, without_nominal

__all__ = ["RULES", "classify", "diagnose", "signature", "without_nominal"]

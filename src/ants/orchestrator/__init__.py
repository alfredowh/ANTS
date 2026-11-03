"""Orchestrator: the closed loop, the regression gate and escalation.

The only package that knows both systems: it drives System 2 (`ants.adversary.Adversary`) and
System 1 (behind `Synthesizer`), and talks to both only through `ants.contracts`.
"""

from ants.orchestrator.gate import GATE_MODES, GateDecision, gate
from ants.orchestrator.human_gate import GateAnswer, answer_to_constraint
from ants.orchestrator.loop import Loop, LoopConfig, LoopResult
from ants.orchestrator.synthesis import MOCK_WORLD_PATCHES, PatchSynthesizer, Synthesizer
from ants.orchestrator.workflow import WORKFLOW_PATH, load_workflow, workflow_info

__all__ = [
    "GATE_MODES",
    "MOCK_WORLD_PATCHES",
    "WORKFLOW_PATH",
    "GateAnswer",
    "GateDecision",
    "Loop",
    "LoopConfig",
    "LoopResult",
    "PatchSynthesizer",
    "Synthesizer",
    "answer_to_constraint",
    "gate",
    "load_workflow",
    "workflow_info",
]

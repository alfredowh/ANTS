"""Synthesizer adapter: wraps the Muse generator behind `orchestrator.synthesis.Synthesizer`.

The orchestrator's loop (PR #8, `feature/orchestrator`) only needs
`rewrite(incumbent, feedback, constraints) -> Policy | None`. This module is the thin seam
between that protocol and System 1's existing prompt builder (`generator.py`) and chat client
(`llm.py`); it adds no new generation logic and does not touch either file.

One call = one candidate: build the standard prompt, show the incumbent's code, state every
constraint and the failures that motivated them, ask for the corrected program. The orchestrator
is the one that replays and gates the candidate, so this adapter does not run anything.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from ants.contracts import Constraint, Feedback, Policy
from ants.synthesizer.generator import build_messages, extract_code
from ants.synthesizer.llm import BudgetExceeded, ChatClient


def _failure_note(fb: Feedback) -> str:
    """One short line per failure, enough context for the model without a full trace dump."""
    parts = [f"case {fb.test_case.case_id}", f"mode={fb.failure.mode}"]
    if fb.failure.root_cause:
        parts.append(fb.failure.root_cause)
    return "- " + ", ".join(parts)


@dataclass
class MuseSynthesizer:
    """Fits System 1's `ChatClient` + prompt builder behind `Synthesizer.rewrite`."""

    client: ChatClient
    api_reference: str
    example_program: str
    example_task: str
    task: str
    demo_summary: dict | None = None
    scene_context: str | None = None
    temperature: float = 0.2
    explain: bool = False

    def rewrite(
        self, incumbent: Policy, feedback: Sequence[Feedback], constraints: Sequence[Constraint]
    ) -> Policy | None:
        messages = build_messages(
            self.api_reference,
            self.example_program,
            self.example_task,
            self.task,
            self.demo_summary,
            constraints=[c.rule for c in constraints],
            scene_context=self.scene_context,
        )
        messages.append({"role": "assistant", "content": incumbent.code})
        ask = (
            "Reply with only the full corrected program."
            if not self.explain
            else "Reply with 3-6 lines starting with 'WHY:', then the full corrected program "
            "in one ```python block."
        )
        notes = "\n".join(_failure_note(fb) for fb in feedback) or "(no new failures)"
        messages.append(
            {
                "role": "user",
                "content": "This program failed on the cases below. Apply the rules learned "
                f"above and fix it.\n{notes}\n{ask}",
            }
        )
        try:
            reply = self.client.chat(messages, temperature=self.temperature, tag="orchestrator")
        except BudgetExceeded:
            return None
        code = extract_code(reply.text)
        return replace(
            incumbent,
            version=incumbent.version + 1,
            code=code,
            parent_version=incumbent.version,
            constraints=tuple(c.constraint_id for c in constraints),
            metadata={
                **incumbent.metadata,
                "synthesizer": "muse",
                "tokens": reply.prompt_tokens + reply.completion_tokens,
            },
        )

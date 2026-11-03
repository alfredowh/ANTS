"""The first Muse-Code-backed orchestrator: fills System 2's `Generate` slot in `harden()`.

Builds one prompt from `docs/orchestrator/phases.md` plus the incumbent program, the constraints
learned so far and the latest failure feedback, asks `muse exec` for a repair, and writes the
candidate plus a per-cycle JSONL trace of the full Muse Code event stream, for the dashboard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ants.contracts import Constraint
from ants.orchestrator.muse_cli import MuseCliError, run_muse
from ants.synthesizer.generator import extract_code

PHASES_DOC = Path(__file__).resolve().parents[3] / "docs" / "orchestrator" / "phases.md"


@dataclass
class MuseOrchestrator:
    """Stateful `Generate` callable: tracks total spend across every call in one `harden()` run.

    Attributes:
        out_dir: where each cycle's candidate program, reply, trace and usage are written.
        token_budget: hard cap on prompt+completion tokens across every call this makes; once
            reached, the call returns None so `harden()` stops the same way a budget-exhausted
            `ChatClient` does today.
    """

    out_dir: Path
    token_budget: int
    reasoning_effort: str = "high"
    max_model_steps: int | None = 40
    _spent: int = field(default=0, repr=False)
    _cycle: int = field(default=0, repr=False)

    def spent(self) -> int:
        return self._spent

    def __call__(
        self, incumbent: Path, constraints: list[Constraint], feedbacks: list[dict]
    ) -> tuple[Path, int] | None:
        if self.spent() >= self.token_budget:
            return None
        prompt = self._build_prompt(incumbent, constraints, feedbacks)
        try:
            result = run_muse(
                prompt,
                reasoning_effort=self.reasoning_effort,
                max_model_steps=self.max_model_steps,
            )
        except MuseCliError:
            return None
        self._spent += result.total_tokens
        self._cycle += 1
        cycle_dir = self.out_dir / f"cycle{self._cycle}"
        cycle_dir.mkdir(parents=True, exist_ok=True)
        candidate = cycle_dir / "program.py"
        candidate.write_text(extract_code(result.text), encoding="utf-8")
        (cycle_dir / "incumbent.py").write_text(
            incumbent.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (cycle_dir / "reply.md").write_text(result.text, encoding="utf-8")
        (cycle_dir / "trace.jsonl").write_text(
            "\n".join(json.dumps(e) for e in result.events), encoding="utf-8"
        )
        (cycle_dir / "usage.json").write_text(
            json.dumps(
                {
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "reasoning_tokens": result.reasoning_tokens,
                    "cached_tokens": result.cached_tokens,
                    "spent_total": self._spent,
                    "budget": self.token_budget,
                },
                indent=1,
            ),
            encoding="utf-8",
        )
        return candidate, result.total_tokens

    def _build_prompt(
        self, incumbent: Path, constraints: list[Constraint], feedbacks: list[dict]
    ) -> str:
        parts = [PHASES_DOC.read_text(encoding="utf-8")]
        parts.append(
            "## Incumbent program\n```python\n" + incumbent.read_text(encoding="utf-8") + "```"
        )
        if constraints:
            parts.append(
                "## Constraints learned so far\n"
                + "\n".join(
                    f"- ({c.failure_signature}) {c.when_to_apply}: {c.rule}" for c in constraints
                )
            )
        if feedbacks:
            parts.append(
                "## Feedback from the failures just observed\n"
                + "\n".join(f"```json\n{json.dumps(f, indent=1)}\n```" for f in feedbacks)
            )
        return "\n\n".join(parts)

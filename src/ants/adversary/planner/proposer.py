"""Perturbation proposer: M model agents each read the program and propose values aimed at one of
its assumptions; the most novel valid proposal wins.

Every proposal passes `PerturbationSpace.validate` (unknown settings dropped, values clamped,
severity capped), so no reply can produce an out-of-range scene. On a model error, a budget stop
or replies with no usable JSON, the proposer falls back to the scalar sampler and says so.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from string import Template

from ants.adversary.models import Effort, Message, ModelError, ReasoningModel, extract_json
from ants.adversary.perturbations import Bounds, PerturbationSpace, make
from ants.contracts import Perturbation

PROMPT = Template(
    (Path(__file__).parents[1] / "prompts" / "propose.md").read_text(encoding="utf-8")
)


@dataclass(frozen=True)
class Candidate:
    perturbation: Perturbation
    assumption: str
    novelty: float


@dataclass(frozen=True)
class Proposal:
    perturbation: Perturbation
    source: str  # "model" or "fallback: <reason>"
    assumption: str = ""
    candidates: tuple[Candidate, ...] = ()
    usage: Mapping[str, int] = field(default_factory=dict)


def _vector(p: Perturbation, space: PerturbationSpace) -> list[float]:
    out = []
    for param in space.params(p.category):
        v = p.params.get(param.name, param.nominal)
        sign = 1.0 if v >= param.nominal else -1.0
        out.append(sign * param.distance(v))
    return out


def novelty(p: Perturbation, previous: Sequence[Perturbation], space: PerturbationSpace) -> float:
    """Distance in normalised parameter space to the closest previous attack (inf if none)."""
    same = [q for q in previous if q.category == p.category]
    if not same:
        return math.inf
    v = _vector(p, space)
    return min(math.dist(v, _vector(q, space)) for q in same)


@dataclass
class Proposer:
    model: ReasoningModel
    space: PerturbationSpace
    n_agents: int = 4

    def propose(
        self,
        category: str,
        program: str,
        task: str,
        recent: Sequence[tuple[Perturbation, str]],  # (perturbation, outcome) newest last
        severity_limit: float,
        rng: random.Random,
        seed: int | None = None,
    ) -> Proposal:
        bounded = PerturbationSpace(self.space.categories, rho=min(self.space.rho, severity_limit))
        prompt = PROMPT.substitute(
            task=task,
            program=program,
            category=category,
            bounds=bounded.describe(category),
            recent="\n".join(f"- {dict(p.params)} -> {outcome}" for p, outcome in recent)
            or "- none yet",
        )
        try:
            resp = self.model.complete(
                [Message("user", prompt)], Effort.PARALLEL, json_schema={}, n=self.n_agents
            )
        except ModelError as exc:
            return self._fallback(category, severity_limit, rng, seed, f"model error: {exc}")

        previous = [p for p, _ in recent]
        candidates = []
        for text in resp.texts:
            try:
                reply = extract_json(text)
                raw = reply.get("params")
                if not isinstance(raw, dict):
                    continue
                p = bounded.validate(category, raw, seed, str(reply.get("rationale", ""))[:300])
            except (ModelError, AttributeError):
                continue
            candidates.append(
                Candidate(p, str(reply.get("assumption", ""))[:300], novelty(p, previous, bounded))
            )
        if not candidates:
            return self._fallback(category, severity_limit, rng, seed, "no usable proposal")
        best = max(candidates, key=lambda c: (c.novelty, c.perturbation.severity))
        return Proposal(best.perturbation, "model", best.assumption, tuple(candidates), resp.usage)

    def _fallback(self, category, severity_limit, rng, seed, reason) -> Proposal:
        lo = min(0.3, severity_limit)
        p = make(category, rng.uniform(lo, severity_limit), rng, Bounds(default=severity_limit),
                 self.space, seed)  # fmt: skip
        return Proposal(p, f"fallback: {reason}")

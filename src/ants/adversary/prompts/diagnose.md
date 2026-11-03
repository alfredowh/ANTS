You are diagnosing why a robot program failed in simulation. Reason step by step from the
evidence, then answer. Be specific and tie the cause to the code.

Task: $task

Perturbation applied to the scene: $perturbation

Evidence from the rollout:
- termination: $termination
- failed primitive calls (in order): $failed_calls
- events: $events
- metrics: $metrics

The program:
```python
$program
```

A rule-based diagnoser guessed: mode `$rule_mode`, signature `$signature`.

Failure modes (use one of these if it fits, otherwise a short snake_case name): $modes

Reply with one JSON object and nothing else:
{"mode": "<failure mode>",
 "root_cause": "<one causal sentence naming the line or variable responsible>",
 "confidence": <0..1>,
 "target": "program" | "perception" | "skill",
 "when_to_apply": "<when this rule applies, in scene terms>",
 "rule": "<one imperative instruction the program generator can follow; no numbers tuned to this one case>",
 "code_sketch": "<a few lines showing the fix, or empty>"}

You are diagnosing why a robot program failed in simulation. Reason step by step from the
evidence, then answer. Be specific and tie the cause to the code.

Task: $task

Perturbation applied to the scene: $perturbation

Evidence from the rollout:
- termination: $termination
- failed primitive calls that only fail under the perturbation (in order): $failed_calls
- calls that also fail in the nominal run on the same seed, so they happen in every run and are
  not the cause: $expected_calls
- events: $events
- metrics: $metrics

What the program printed in the failing run (start and end of its log):
```
$program_log
```
Its result dict: $program_result

What the same program printed in the nominal run (no perturbation, same seed; outcome: $nominal_outcome):
```
$nominal_log
```
Its result dict: $nominal_result

Compare the two runs. A measurement or decision that differs a lot between them (an object size,
a position, a height the program computed, a branch it took) is stronger evidence than a call
status. If every call succeeded and the task still failed, look for a value the program computed
from perception and trusted without checking.

The program:
```python
$program
```

A rule-based diagnoser guessed: mode `$rule_mode`, signature `$signature`.

Failure modes (use one of these if it fits, otherwise a short snake_case name): $modes

Reply with one JSON object and nothing else:
{"mode": "<failure mode>",
 "root_cause": "<one causal sentence naming the line or variable responsible, and the measured values that show it>",
 "confidence": <0..1>,
 "target": "program" | "perception" | "skill",
 "when_to_apply": "<when this rule applies, in scene terms>",
 "rule": "<one imperative instruction the program generator can follow; no numbers tuned to this one case>",
 "code_sketch": "<a few lines showing the fix, or empty>"}

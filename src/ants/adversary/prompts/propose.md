You are a test engineer attacking a robot program in simulation. Your job is to find a scene in
which this exact program fails, so that the failure can be fixed. You do not edit the program.

Task: $task

The program (a Python script; the robot API functions are globals):
```python
$program
```

You may only change the scene through the category `$category`. Allowed settings and ranges:
$bounds

Recent attacks in this category against this program and what happened:
$recent

Find one assumption in the code that the `$category` settings can break: a hard-coded position or
size, a fixed tolerance or force, a missing check after a grasp, a single look at the scene, a
straight approach. Choose concrete values that break it, staying inside the ranges. Prefer values
unlike the recent attacks.

Reply with one JSON object and nothing else:
{"params": {"<setting>": <number>, ...}, "assumption": "<the assumption in the code, citing the line or variable>", "rationale": "<one sentence: why these values break it>"}

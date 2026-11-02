"""Build the generator prompt and pull the program out of the reply.

The prompt has fixed parts (program rules, API reference, one example program) and the
parts that make the experimental arms differ: an optional demonstration summary and the
constraints learned so far. Everything else is identical across arms.
"""

from __future__ import annotations

import json
import re

RULES = """You write robot programs for a Franka Panda arm in the LIBERO simulator.
The program is plain Python executed in a sandbox. Rules:
- The API functions and constructors below are already in scope. Do not import anything (only `math` is allowed).
- No classes, `with`, `global`, `del`, or names starting with `_`.
- Builtins are restricted: no `getattr`, `setattr`, `hasattr`, `isinstance`, `eval`, `open` or `__import__`. Probe an object's fields with direct attribute access inside `try/except AttributeError` and fall back to the next field name.
- Positions are metres in the `robot_base` frame. Do not hard-code absolute object positions: localize objects at run time.
- Check the `.ok` of every result and stop safely when something fails.
- Use `print(...)` to log the numbers you rely on (object positions, sizes, target poses) so a failure can be diagnosed.
- Start the program with two dict literals. `params` holds every number you take from the demonstration (grasp height, approach offsets, carry and release heights), each as a fraction of a measured object size, never absolute metres. `attack_ranges` maps each `params` key to a `[min, max]` list of values you consider still safe. Read these values from `params` below; do not repeat them as literals.
- Set a top-level variable `result` to a small dict reporting what happened (which steps succeeded, key numbers).
Reply with ONLY the program inside one ```python fenced block."""


def demo_section(summary: dict) -> str:
    """Describe a demonstration in object-relative terms (sizes as fractions of the object)."""
    g, c, r = summary["grasp"], summary["carry"], summary["release"]
    bowl = summary["objects_real"]["bowl"]
    return f"""A human showed this task once on a real bowl (diameter {bowl["diameter_m"] * 100:.1f} cm, height {bowl["height_m"] * 100:.1f} cm) and plate. Measured from the video, relative to the objects:
- Grasp: the hand pinched the bowl's RIM, not its centre: the pinch point was {g["radial_offset_over_radius"]:.2f} bowl radii from the bowl's vertical axis, at {g["height_over_object_height"]:.2f} of the bowl's height above the table. The pinch closed to about {g["aperture_at_grasp_m"] * 100:.1f} cm (one wall of the bowl between the fingers).
- Approach: in the last 0.5 s before the pinch the hand moved {g["approach_last_0.5s"]["drop_m"] * 100:.1f} cm down and {g["approach_last_0.5s"]["horizontal_m"] * 100:.1f} cm sideways, i.e. it came down from above onto the rim.
- Carry: it lifted first, then carried the bowl at up to {c["max_height_above_table_m"] * 100:.0f} cm above the table ({c["duration_s"]:.1f} s).
- Release: it opened over the plate, {r["radial_offset_over_plate_radius"]:.2f} plate radii from the plate centre. (The measured release height, {r["height_above_table_m"] * 100:.0f} cm above the table, is uncertain.)
The simulated bowl and plate have different sizes: scale these numbers by the sizes you measure at run time."""


def build_messages(
    api_reference: str,
    example_program: str,
    example_task: str,
    task: str,
    demo_summary: dict | None = None,
    constraints: list[str] | None = None,
    scene_context: str | None = None,
    images: list[tuple[str, str]] | None = None,
) -> list[dict]:
    system = (
        f"{RULES}\n\nAPI reference:\n{api_reference}\n\n"
        f'Example program for a different task ("{example_task}"):\n```python\n{example_program}\n```'
    )
    user = f"Task: {task}"
    if demo_summary is not None:
        user += "\n\nDemonstration:\n" + demo_section(demo_summary)
    if scene_context:
        user += "\n\n" + scene_context
    if constraints:
        user += "\n\nRules learned from earlier failures:\n" + "\n".join(
            f"- {c}" for c in constraints
        )
    return [{"role": "system", "content": system}, image_message(user, images)]


def image_message(text: str, images: list[tuple[str, str]] | None = None) -> dict:
    """User message; `images` are (caption, data URL) pairs shown to the VLM after the text.

    Examples: the initial scene, a generated goal scene (`image_gen.ImageGenerator`).
    """
    if not images:
        return {"role": "user", "content": text}
    parts: list[dict] = [{"type": "text", "text": text}]
    for caption, url in images:
        parts.append({"type": "text", "text": caption})
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return {"role": "user", "content": parts}


def repair_message(
    feedback: dict, explain: bool = False, images: list[tuple[str, str]] | None = None
) -> dict:
    """Feedback for the next attempt; `explain` asks for a short rationale before the program."""
    ask = (
        "Reply with only the full corrected program."
        if not explain
        else "Reply with 3-6 lines starting with 'WHY:' (what went wrong, what you change and why), "
        "then the full corrected program in one ```python block."
    )
    return image_message(
        "The program did not complete the task. What happened:\n"
        + json.dumps(feedback, indent=1)
        + f"\nFind the cause and fix the program. {ask}",
        images,
    )


def extract_code(text: str) -> str:
    """Return the first fenced Python block, or the whole text if there is none."""
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip() + "\n"

# Task: write the demonstration section of a robot-program-generation prompt

You are given a few frames from a human demonstration video, sampled at its key moments
(approach, grasp, lift, release, retreat), plus a JSON block of numbers already measured from the
full video: object-relative offsets (as a fraction of the object's own radius or height, not
absolute metres), an aperture in metres, and timings in seconds. A robot-program generator will
read what you write and nothing else about the demonstration -- it cannot see the video or the
JSON itself.

## What to write

One paragraph (plain text, no headings, no markdown list syntax beyond plain "- " bullets) that:

- Describes where exactly the demonstration grasped the object: which part (rim, centre, a named
  feature visible in the frames), how far from the object's axis as a fraction of its own radius,
  and how high as a fraction of its own height. Include the aperture at grasp in centimetres.
- Describes the final approach into the grasp: how far down and sideways the hand moved in roughly
  the last half-second before closing, so the generator knows the approach direction.
- Describes the carry: how high above the table the object was lifted, and for how long.
- Describes the release: how far from the target's centre, as a fraction of the target's own
  radius, and at what height above the table (say so if this number looked uncertain from the
  video).
- Ends with one sentence reminding the generator that the real objects it will see are a different
  size, so it must scale every one of these numbers by the sizes it measures at run time.

Every number in your paragraph must be object-relative (a fraction of a measured size, or a
fraction of a second), never an absolute position in metres. This is the single most important
rule: a program written from absolute positions does not generalize to a differently-sized or
differently-placed object, which defeats the entire purpose of the demonstration.

## The guarantee this generation must meet

Given the bowl-on-plate demonstration below (frames at its five keyframes, this exact JSON
summary), your output must be usable as a drop-in replacement for the following hand-written
paragraph -- same facts, same numbers, same object-relative framing, your own wording. Note that
`drop_m` below is negative: the hand's last correction before closing was slightly *upward*, not
downward (the hand-coded version this replaces always prints "down" regardless of sign, which is
a bug you should not repeat):

```
A human showed this task once on a real bowl (diameter 13.8 cm, height 6.7 cm) and plate. Measured from the video, relative to the objects:
- Grasp: the hand pinched the bowl's RIM, not its centre: the pinch point was 1.24 bowl radii from the bowl's vertical axis, at 0.82 of the bowl's height above the table. The pinch closed to about 2.9 cm (one wall of the bowl between the fingers).
- Approach: in the last 0.5 s before the pinch the hand moved 2.7 cm up and 4.1 cm sideways.
- Carry: it lifted first, then carried the bowl at up to 23 cm above the table (3.1 s).
- Release: it opened over the plate, 0.67 plate radii from the plate centre. (The measured release height, 14 cm above the table, is uncertain.)
The simulated bowl and plate have different sizes: scale these numbers by the sizes you measure at run time.
```

Matching JSON summary for that paragraph (the shape you will always receive, field names constant
across tasks; `objects_real` names the two objects involved and their measured size):

```json
{
 "grasp": {
  "radial_offset_over_radius": 1.24,
  "height_over_object_height": 0.82,
  "aperture_at_grasp_m": 0.029,
  "approach_last_0.5s": {"horizontal_m": 0.041, "drop_m": -0.027}
 },
 "carry": {"max_height_above_table_m": 0.233, "duration_s": 3.1},
 "release": {"radial_offset_over_plate_radius": 0.67, "height_above_table_m": 0.142},
 "objects_real": {"bowl": {"diameter_m": 0.138, "height_m": 0.067}, "plate": {"diameter_m": 0.255, "height_m": 0.028}}
}
```

A `drop_m` of `-0.027` means the hand moved *up* in the last half-second (it can happen on a late
correction); say "up" in that case, not "down" -- read the sign, do not assume it is always a
descent.

Reply with ONLY the paragraph. No preamble, no explanation of what you did, no repetition of the
JSON.

from ants.evalkit.phases import task_phases

BOWL, PLATE = [0.6, 0.1, 0.0], [0.4, -0.1, 0.0]


def track(steps):
    """steps: (xyz, gripper) per time step."""
    return (
        [i * 0.05 for i in range(len(steps))],
        [list(p) for p, _ in steps],
        [g for _, g in steps],
    )


def run(bowl_pose, hold, lift, plate_pose, release, success=False):
    steps = [([0.45, 0.0, 0.3], 1.0)] * 5
    steps += [(bowl_pose, hold)] * 40  # closed at the bowl
    steps += [([bowl_pose[0], bowl_pose[1], bowl_pose[2] + lift], hold)] * 5
    steps += [(plate_pose, hold if not release else 1.0)] * 5
    return task_phases(*track(steps), {"bowl": BOWL, "plate": PLATE}, success)


def test_never_closed():
    steps = [([0.45, 0.0, 0.3], 1.0)] * 20
    out = task_phases(*track(steps), {"bowl": BOWL}, False)
    assert out["depth"] == 0 and out["label"] == "never closed the gripper"


def test_closed_on_nothing():
    out = run(BOWL, 0.01, 0.1, PLATE, True)
    assert out["label"] == "grasp missed (closed on nothing)"


def test_closed_away_from_bowl():
    out = run([0.3, 0.3, 0.0], 0.07, 0.1, PLATE, True)
    assert out["label"] == "closed away from the bowl"


def test_not_lifted_then_lifted_not_over_plate():
    assert run(BOWL, 0.07, 0.0, PLATE, True)["label"] == "bowl not lifted"
    far = [0.9, 0.5, 0.2]
    assert run(BOWL, 0.07, 0.1, far, True)["label"] == "carried but not over the plate"


def test_released_over_plate_but_task_not_done():
    out = run(BOWL, 0.07, 0.1, PLATE, True)
    assert out["depth"] == 6 and out["label"].startswith("released over the plate")
    assert out["bowl_cm"] == 0.0 and out["plate_cm"] == 0.0


def test_success_overrides_and_best_grasp_counts():
    out = run(BOWL, 0.07, 0.1, PLATE, True, success=True)
    assert out["label"] == "success" and out["depth"] == 7
    miss = [([0.45, 0.0, 0.3], 1.0)] * 3 + [(BOWL, 0.01)] * 30 + [(BOWL, 1.0)] * 5
    good = [(BOWL, 0.07)] * 40 + [([0.6, 0.1, 0.2], 0.07)] * 5 + [(PLATE, 1.0)] * 5
    out = task_phases(*track(miss + good), {"bowl": BOWL, "plate": PLATE}, False)
    assert out["grasps"] == 2 and out["depth"] == 6

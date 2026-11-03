# ruff: noqa: F821, E501  (ASPIRE injects the primitives into the sandbox)
import math

CU = MotionStrategy(trajectory_planner="curobo")

report = {}
ok_all = True
grasp_verified = False
u_chosen = False
ux = 1.0
uy = 0.0
downward = (0.0, 1.0, 0.0, 0.0)
scale = 1.0
plate_center_x = 0.0
plate_center_y = 0.0
plate_radius = 0.10
plate_top_z = 0.0
used_frac = 0.82
used_offset = 0.06
used_height = 0.06
used_table_z = 0.0
carry_gripper_z = 0.32
gripper_to_bottom = 0.05
descent_complete = False
descent_close = False
descent_failed = False
released_ok = False
frac_list = [0.82, 0.92, 0.68]
inward_list = [0.002, 0.001, 0.004]

ctx = get_task_context()
language = str(ctx.language)
print("task language:", language)
report["language"] = language

opened = open_gripper()
report["open_initial"] = opened.ok
print("open_initial ok:", opened.ok)
if not opened.ok:
    ok_all = False

plate = None
if ok_all:
    plate = localize_object("plate", camera_name="agentview")
    report["plate_localized"] = plate.ok
    print("plate localized ok:", plate.ok)
    if not plate.ok:
        plate = localize_object("dinner plate", camera_name="agentview")
        report["plate_localized_fallback"] = plate.ok
        print("plate fallback localized ok:", plate.ok)
    if not plate.ok:
        ok_all = False

if ok_all:
    plate_points = plate.point_cloud.points
    plate_n = len(plate_points)
    report["plate_point_count"] = plate_n
    print("plate point count:", plate_n)
    if plate_n < 20:
        ok_all = False
    else:
        plate_xs = [float(p[0]) for p in plate_points]
        plate_ys = [float(p[1]) for p in plate_points]
        plate_zs = [float(p[2]) for p in plate_points]
        plate_xs_sorted = sorted(plate_xs)
        plate_ys_sorted = sorted(plate_ys)
        plate_zs_sorted = sorted(plate_zs)
        plate_med_x = plate_xs_sorted[int(0.50 * (plate_n - 1))]
        plate_med_y = plate_ys_sorted[int(0.50 * (plate_n - 1))]
        plate_bbox_x = (
            plate_xs_sorted[int(0.01 * (plate_n - 1))] + plate_xs_sorted[int(0.99 * (plate_n - 1))]
        ) / 2.0
        plate_bbox_y = (
            plate_ys_sorted[int(0.01 * (plate_n - 1))] + plate_ys_sorted[int(0.99 * (plate_n - 1))]
        ) / 2.0
        if abs(plate_bbox_x - plate_med_x) > 0.025:
            plate_center_x = plate_med_x
        else:
            plate_center_x = plate_bbox_x
        if abs(plate_bbox_y - plate_med_y) > 0.025:
            plate_center_y = plate_med_y
        else:
            plate_center_y = plate_bbox_y
        plate_dx = (
            plate_xs_sorted[int(0.99 * (plate_n - 1))] - plate_xs_sorted[int(0.01 * (plate_n - 1))]
        )
        plate_dy = (
            plate_ys_sorted[int(0.99 * (plate_n - 1))] - plate_ys_sorted[int(0.01 * (plate_n - 1))]
        )
        plate_rads = [
            math.sqrt(
                (plate_xs[i] - plate_center_x) * (plate_xs[i] - plate_center_x)
                + (plate_ys[i] - plate_center_y) * (plate_ys[i] - plate_center_y)
            )
            for i in range(plate_n)
        ]
        plate_rads_sorted = sorted(plate_rads)
        plate_radius = plate_rads_sorted[int(0.95 * (plate_n - 1))]
        if plate_radius < 0.04 or plate_radius > 0.22:
            plate_radius = max(plate_dx, plate_dy) / 2.0
        plate_top_z = plate_zs_sorted[int(0.90 * (plate_n - 1))]
        print(
            "plate median center:",
            plate_med_x,
            plate_med_y,
            "bbox center:",
            plate_bbox_x,
            plate_bbox_y,
            "chosen center:",
            plate_center_x,
            plate_center_y,
        )
        print(
            "plate bbox dx dy:",
            plate_dx,
            plate_dy,
            "radius p95:",
            plate_radius,
            "top z p90:",
            plate_top_z,
            "z p50:",
            plate_zs_sorted[int(0.50 * (plate_n - 1))],
            "z max:",
            plate_zs_sorted[plate_n - 1],
        )
        report["plate_center_x"] = plate_center_x
        report["plate_center_y"] = plate_center_y
        report["plate_radius_m"] = plate_radius
        report["plate_top_z"] = plate_top_z

if ok_all:
    state0 = get_robot_state()
    ee0 = state0.end_effector_poses["primary"]
    q0 = ee0.quaternion_wxyz
    qw = float(q0[0])
    qx = float(q0[1])
    qy = float(q0[2])
    qz = float(q0[3])
    downward = (qw, qx, qy, qz)
    closing_x_raw = 2.0 * (qx * qy - qw * qz)
    closing_y_raw = 1.0 - 2.0 * (qx * qx + qz * qz)
    closing_norm = math.sqrt(closing_x_raw * closing_x_raw + closing_y_raw * closing_y_raw)
    print(
        "gripper local Y axis projected to XY, assumed closing axis raw:",
        closing_x_raw,
        closing_y_raw,
        "norm:",
        closing_norm,
        "downward quat:",
        downward,
    )
    if closing_norm < 0.2:
        ux = 1.0
        uy = 0.0
    else:
        ux = closing_x_raw / closing_norm
        uy = closing_y_raw / closing_norm
    report["closing_axis_x"] = ux
    report["closing_axis_y"] = uy

for attempt in range(3):
    if not ok_all:
        break
    if grasp_verified:
        break
    report["grasp_attempts"] = attempt + 1
    print("grasp attempt:", attempt)
    reopened_start = open_gripper()
    report["open_attempt_" + str(attempt)] = reopened_start.ok
    print("open at attempt start ok:", reopened_start.ok)
    if not reopened_start.ok:
        ok_all = False
        break
    bowl = localize_object("bowl", camera_name="agentview")
    report["bowl_localized_attempt_" + str(attempt)] = bowl.ok
    print("bowl localized ok:", bowl.ok)
    if not bowl.ok:
        bowl = localize_object("the bowl", camera_name="agentview")
        report["bowl_localized_fallback_attempt_" + str(attempt)] = bowl.ok
        print("bowl fallback localized ok:", bowl.ok)
    if not bowl.ok:
        ok_all = False
        break
    bowl_points = bowl.point_cloud.points
    bowl_n = len(bowl_points)
    report["bowl_point_count_attempt_" + str(attempt)] = bowl_n
    print("bowl point count:", bowl_n)
    if bowl_n < 20:
        ok_all = False
        break
    bowl_xs = [float(p[0]) for p in bowl_points]
    bowl_ys = [float(p[1]) for p in bowl_points]
    bowl_zs = [float(p[2]) for p in bowl_points]
    bowl_xs_sorted = sorted(bowl_xs)
    bowl_ys_sorted = sorted(bowl_ys)
    bowl_zs_sorted = sorted(bowl_zs)
    bowl_med_x = bowl_xs_sorted[int(0.50 * (bowl_n - 1))]
    bowl_med_y = bowl_ys_sorted[int(0.50 * (bowl_n - 1))]
    bowl_bbox_x = (
        bowl_xs_sorted[int(0.01 * (bowl_n - 1))] + bowl_xs_sorted[int(0.99 * (bowl_n - 1))]
    ) / 2.0
    bowl_bbox_y = (
        bowl_ys_sorted[int(0.01 * (bowl_n - 1))] + bowl_ys_sorted[int(0.99 * (bowl_n - 1))]
    ) / 2.0
    if abs(bowl_bbox_x - bowl_med_x) > 0.025:
        bowl_center_x = bowl_med_x
    else:
        bowl_center_x = bowl_bbox_x
    if abs(bowl_bbox_y - bowl_med_y) > 0.025:
        bowl_center_y = bowl_med_y
    else:
        bowl_center_y = bowl_bbox_y
    bowl_dx = bowl_xs_sorted[int(0.99 * (bowl_n - 1))] - bowl_xs_sorted[int(0.01 * (bowl_n - 1))]
    bowl_dy = bowl_ys_sorted[int(0.99 * (bowl_n - 1))] - bowl_ys_sorted[int(0.01 * (bowl_n - 1))]
    bowl_diam = max(bowl_dx, bowl_dy)
    table_z = bowl_zs_sorted[int(0.01 * (bowl_n - 1))]
    bowl_top_z = bowl_zs_sorted[int(0.99 * (bowl_n - 1))]
    bowl_height = bowl_top_z - table_z
    if bowl_height < 0.02 or bowl_height > 0.12:
        bowl_height = bowl_diam * 0.4855
        print("bowl height fallback:", bowl_height)
    bowl_rads = [
        math.sqrt(
            (bowl_xs[i] - bowl_center_x) * (bowl_xs[i] - bowl_center_x)
            + (bowl_ys[i] - bowl_center_y) * (bowl_ys[i] - bowl_center_y)
        )
        for i in range(bowl_n)
    ]
    bowl_rads_sorted = sorted(bowl_rads)
    top_radius = bowl_rads_sorted[int(0.97 * (bowl_n - 1))]
    if top_radius < 0.02 or top_radius > 0.12:
        top_radius = bowl_diam / 2.0
    print(
        "bowl median center:",
        bowl_med_x,
        bowl_med_y,
        "bbox center:",
        bowl_bbox_x,
        bowl_bbox_y,
        "chosen center:",
        bowl_center_x,
        bowl_center_y,
    )
    print(
        "bowl dx dy diam:",
        bowl_dx,
        bowl_dy,
        bowl_diam,
        "height:",
        bowl_height,
        "table z:",
        table_z,
        "top z:",
        bowl_top_z,
        "top radius p97:",
        top_radius,
    )
    report["bowl_center_x"] = bowl_center_x
    report["bowl_center_y"] = bowl_center_y
    report["bowl_diameter_m"] = bowl_diam
    report["bowl_height_m"] = bowl_height
    report["bowl_top_radius_m"] = top_radius
    report["table_z"] = table_z
    if attempt == 0:
        scale = bowl_diam / 0.138
        print(
            "scale by bowl diameter versus demo 0.138 m:",
            scale,
            "scaled carry bottom height:",
            0.25 * scale,
            "scaled demo pinch aperture:",
            0.022 * scale,
        )
        report["scale_diameter"] = scale
    if not u_chosen:
        dot_robot = ux * (-bowl_center_x) + uy * (-bowl_center_y)
        if dot_robot < 0.0:
            ux = -ux
            uy = -uy
        u_chosen = True
        print("chosen radial grasp direction u, gripper side of bowl:", ux, uy)
        report["grasp_dir_x"] = ux
        report["grasp_dir_y"] = uy
    perp_x = -uy
    perp_y = ux
    grasp_frac = frac_list[attempt]
    grasp_z = table_z + grasp_frac * bowl_height
    slice_rads = []
    for point_index in range(bowl_n):
        if abs(bowl_zs[point_index] - grasp_z) < 0.010:
            radial_u = (bowl_xs[point_index] - bowl_center_x) * ux + (
                bowl_ys[point_index] - bowl_center_y
            ) * uy
            lateral_t = (bowl_xs[point_index] - bowl_center_x) * perp_x + (
                bowl_ys[point_index] - bowl_center_y
            ) * perp_y
            if radial_u > 0.02 and abs(lateral_t) < 0.025:
                slice_rads.append(radial_u)
    print(
        "slice point count at grasp height:",
        len(slice_rads),
        "grasp height fraction:",
        grasp_frac,
        "grasp z:",
        grasp_z,
    )
    if len(slice_rads) > 30:
        slice_sorted = sorted(slice_rads)
        wall_radius = slice_sorted[int(0.95 * (len(slice_rads) - 1))]
    else:
        wall_radius = top_radius * (0.75 + 0.25 * grasp_frac)
        print("slice fallback wall radius:", wall_radius)
    if wall_radius > top_radius * 1.03:
        wall_radius = top_radius
    if wall_radius < 0.02:
        wall_radius = top_radius * 0.95
    grasp_offset = wall_radius - inward_list[attempt]
    grasp_x = bowl_center_x + ux * grasp_offset
    grasp_y = bowl_center_y + uy * grasp_offset
    used_frac = grasp_frac
    used_offset = grasp_offset
    used_height = bowl_height
    used_table_z = table_z
    print(
        "wall radius at grasp height:",
        wall_radius,
        "top radius:",
        top_radius,
        "TCP offset from bowl axis:",
        grasp_offset,
        "ratio to top radius:",
        grasp_offset / top_radius,
    )
    print(
        "grasp TCP:",
        grasp_x,
        grasp_y,
        grasp_z,
        "demo hand point was 1.16 radii, robot TCP is placed on the wall itself",
    )
    report["wall_radius_attempt_" + str(attempt)] = wall_radius
    report["grasp_offset_m"] = grasp_offset
    report["grasp_x"] = grasp_x
    report["grasp_y"] = grasp_y
    report["grasp_z"] = grasp_z
    moved_high = move_to_pose(
        Pose(
            position=(grasp_x, grasp_y, grasp_z + 0.16),
            quaternion_wxyz=downward,
            frame="robot_base",
        ),
        tolerance=0.03,
        strategy=CU,
        max_steps=600,
    )
    report["moved_high_attempt_" + str(attempt)] = moved_high.ok
    print("moved high above rim ok:", moved_high.ok)
    if not moved_high.ok:
        ok_all = False
        break
    moved_mid = move_to_pose(
        Pose(
            position=(grasp_x, grasp_y, grasp_z + 0.04),
            quaternion_wxyz=downward,
            frame="robot_base",
        ),
        tolerance=0.02,
        strategy=CU,
        max_steps=400,
    )
    report["moved_mid_attempt_" + str(attempt)] = moved_mid.ok
    print("moved to just above rim ok:", moved_mid.ok)
    if not moved_mid.ok:
        ok_all = False
        break
    moved_grasp = move_to_pose(
        Pose(position=(grasp_x, grasp_y, grasp_z), quaternion_wxyz=downward, frame="robot_base"),
        tolerance=0.015,
        strategy=CU,
        max_steps=400,
    )
    report["moved_grasp_attempt_" + str(attempt)] = moved_grasp.ok
    print("moved to rim pinch ok:", moved_grasp.ok)
    if not moved_grasp.ok:
        ok_all = False
        break
    closed = close_gripper()
    width_after_close = float(get_robot_state().gripper_positions["primary"])
    report["closed_attempt_" + str(attempt)] = closed.ok
    report["width_after_close_attempt_" + str(attempt)] = width_after_close
    print("close ok:", closed.ok, "gripper width after close, normalized:", width_after_close)
    if not closed.ok:
        ok_all = False
        break
    lift_ok = True
    for lift_idx in range(5):
        lift_target_z = grasp_z + 0.025 * (lift_idx + 1)
        moved_lift = move_to_pose(
            Pose(
                position=(grasp_x, grasp_y, lift_target_z),
                quaternion_wxyz=downward,
                frame="robot_base",
            ),
            tolerance=0.02,
            strategy=CU,
            max_steps=400,
        )
        report["lift_step_attempt_" + str(attempt) + "_" + str(lift_idx)] = moved_lift.ok
        print("stepped lift step:", lift_idx, "target z:", lift_target_z, "ok:", moved_lift.ok)
        if not moved_lift.ok:
            moved_lift_retry = move_to_pose(
                Pose(
                    position=(grasp_x, grasp_y, lift_target_z),
                    quaternion_wxyz=downward,
                    frame="robot_base",
                ),
                tolerance=0.03,
                strategy=CU,
                max_steps=600,
            )
            report["lift_step_retry_attempt_" + str(attempt) + "_" + str(lift_idx)] = (
                moved_lift_retry.ok
            )
            print("stepped lift retry ok:", moved_lift_retry.ok)
            if not moved_lift_retry.ok:
                lift_ok = False
                ok_all = False
                break
    if not lift_ok:
        break
    width_after_lift = float(get_robot_state().gripper_positions["primary"])
    report["width_after_lift_attempt_" + str(attempt)] = width_after_lift
    print("gripper width after stepped lift:", width_after_lift)
    verified_by_vision = False
    verify = localize_object("bowl", camera_name="agentview")
    report["verify_localize_attempt_" + str(attempt)] = verify.ok
    print("verify bowl localize ok:", verify.ok)
    if verify.ok:
        verify_points = verify.point_cloud.points
        if len(verify_points) >= 20:
            verify_zs_sorted = sorted([float(p[2]) for p in verify_points])
            verify_bottom = verify_zs_sorted[int(0.10 * (len(verify_zs_sorted) - 1))]
            verify_median_z = verify_zs_sorted[int(0.50 * (len(verify_zs_sorted) - 1))]
            verified_by_vision = verify_bottom > table_z + 0.035
            report["verify_bottom_p10_attempt_" + str(attempt)] = verify_bottom
            print(
                "verify bowl bottom p10:",
                verify_bottom,
                "median z:",
                verify_median_z,
                "table z:",
                table_z,
                "vision verified:",
                verified_by_vision,
            )
    verified_by_width = width_after_lift > 0.012 and width_after_lift < 0.45
    grasp_verified = verified_by_vision or verified_by_width
    report["grasp_verified_attempt_" + str(attempt)] = grasp_verified
    print(
        "verified by vision:",
        verified_by_vision,
        "verified by width:",
        verified_by_width,
        "grasp verified:",
        grasp_verified,
    )
    if grasp_verified:
        break
    reopened_failed = open_gripper()
    report["reopen_failed_attempt_" + str(attempt)] = reopened_failed.ok
    print("reopen after failed grasp ok:", reopened_failed.ok)
    if not reopened_failed.ok:
        ok_all = False
        break
    state_failed = get_robot_state()
    pose_failed = state_failed.end_effector_poses["primary"]
    retreat_failed_pose = Pose(
        position=(
            float(pose_failed.position[0]),
            float(pose_failed.position[1]),
            float(pose_failed.position[2]) + 0.12,
        ),
        quaternion_wxyz=pose_failed.quaternion_wxyz,
        frame=pose_failed.frame,
    )
    retreated_failed = move_to_pose(retreat_failed_pose, tolerance=0.03, strategy=CU, max_steps=400)
    report["retreat_failed_attempt_" + str(attempt)] = retreated_failed.ok
    print("retreat after failed grasp ok:", retreated_failed.ok)
    if not retreated_failed.ok:
        ok_all = False
        break

report["grasp_verified"] = grasp_verified
if ok_all and not grasp_verified:
    ok_all = False
    print("all grasp attempts failed verification")

if ok_all and grasp_verified:
    carry_gripper_z = used_table_z + 0.25 * scale + used_frac * used_height
    report["carry_gripper_z"] = carry_gripper_z
    print("carry gripper z, bowl bottom scaled demo height 0.25 m above table:", carry_gripper_z)
    for carry_idx in range(8):
        state_carry = get_robot_state()
        pose_carry = state_carry.end_effector_poses["primary"]
        current_z = float(pose_carry.position[2])
        print("carry lift step:", carry_idx, "current z:", current_z, "target z:", carry_gripper_z)
        if current_z >= carry_gripper_z - 0.01:
            break
        target_carry_z = min(carry_gripper_z, current_z + 0.05)
        carry_pose = Pose(
            position=(float(pose_carry.position[0]), float(pose_carry.position[1]), target_carry_z),
            quaternion_wxyz=pose_carry.quaternion_wxyz,
            frame=pose_carry.frame,
        )
        moved_carry = move_to_pose(carry_pose, tolerance=0.02, strategy=CU, max_steps=400)
        report["carry_step_" + str(carry_idx)] = moved_carry.ok
        print("carry step ok:", moved_carry.ok)
        if not moved_carry.ok:
            moved_carry_retry = move_to_pose(carry_pose, tolerance=0.03, strategy=CU, max_steps=600)
            report["carry_step_retry_" + str(carry_idx)] = moved_carry_retry.ok
            print("carry step retry ok:", moved_carry_retry.ok)
            moved_carry = moved_carry_retry
        if not moved_carry.ok:
            ok_all = False
            break

if ok_all and grasp_verified:
    above_gripper_x = plate_center_x + ux * used_offset
    above_gripper_y = plate_center_y + uy * used_offset
    print(
        "above plate gripper target:",
        above_gripper_x,
        above_gripper_y,
        carry_gripper_z,
        "gripper distance from plate center:",
        used_offset,
        "ratio to plate radius:",
        used_offset / plate_radius,
        "demo release ratio was 0.49",
    )
    report["above_gripper_x"] = above_gripper_x
    report["above_gripper_y"] = above_gripper_y
    above_pose = Pose(
        position=(above_gripper_x, above_gripper_y, carry_gripper_z),
        quaternion_wxyz=downward,
        frame="robot_base",
    )
    moved_above = move_to_pose(above_pose, tolerance=0.03, strategy=CU, max_steps=600)
    report["moved_above_plate"] = moved_above.ok
    print("moved above plate ok:", moved_above.ok)
    if not moved_above.ok:
        moved_above_retry = move_to_pose(above_pose, tolerance=0.04, strategy=CU, max_steps=800)
        report["moved_above_plate_retry"] = moved_above_retry.ok
        print("moved above plate retry ok:", moved_above_retry.ok)
        moved_above = moved_above_retry
    if not moved_above.ok:
        ok_all = False

if ok_all and grasp_verified:
    theoretical_gtb = used_frac * used_height
    gripper_to_bottom = theoretical_gtb + 0.02
    held = localize_object("bowl", camera_name="agentview")
    report["held_bowl_localized"] = held.ok
    print("held bowl localized ok, diagnostic only, no correction move:", held.ok)
    state_held = get_robot_state()
    pose_held = state_held.end_effector_poses["primary"]
    held_gripper_x = float(pose_held.position[0])
    held_gripper_y = float(pose_held.position[1])
    held_gripper_z = float(pose_held.position[2])
    expected_bowl_x = held_gripper_x - ux * used_offset
    expected_bowl_y = held_gripper_y - uy * used_offset
    print(
        "expected bowl center from grasp geometry:",
        expected_bowl_x,
        expected_bowl_y,
        "plate center:",
        plate_center_x,
        plate_center_y,
    )
    report["expected_bowl_center_x"] = expected_bowl_x
    report["expected_bowl_center_y"] = expected_bowl_y
    if held.ok:
        held_points = held.point_cloud.points
        if len(held_points) >= 20:
            held_xs_sorted = sorted([float(p[0]) for p in held_points])
            held_ys_sorted = sorted([float(p[1]) for p in held_points])
            held_zs_sorted = sorted([float(p[2]) for p in held_points])
            held_n = len(held_points)
            held_med_x = held_xs_sorted[int(0.50 * (held_n - 1))]
            held_med_y = held_ys_sorted[int(0.50 * (held_n - 1))]
            held_bottom = held_zs_sorted[int(0.10 * (held_n - 1))]
            measured_gtb = held_gripper_z - held_bottom
            print(
                "held bowl median, biased by gripper occlusion:",
                held_med_x,
                held_med_y,
                "bottom p10:",
                held_bottom,
                "measured gripper to bottom:",
                measured_gtb,
                "theoretical:",
                theoretical_gtb,
            )
            report["held_bowl_median_x"] = held_med_x
            report["held_bowl_median_y"] = held_med_y
            report["held_measured_gripper_to_bottom_m"] = measured_gtb
            if measured_gtb > theoretical_gtb - 0.005 and measured_gtb < theoretical_gtb + 0.045:
                gripper_to_bottom = measured_gtb
    print("gripper to bowl bottom used for release:", gripper_to_bottom)
    report["gripper_to_bottom_m"] = gripper_to_bottom

if ok_all and grasp_verified:
    release_gripper_z = plate_top_z + gripper_to_bottom + 0.008
    report["release_gripper_z"] = release_gripper_z
    print(
        "release gripper z, plate top plus gripper to bowl bottom plus 0.008 m margin:",
        release_gripper_z,
        "plate top:",
        plate_top_z,
    )
    for down_idx in range(16):
        if descent_complete or descent_failed:
            break
        state_d = get_robot_state()
        pose_d = state_d.end_effector_poses["primary"]
        cur_x = float(pose_d.position[0])
        cur_y = float(pose_d.position[1])
        cur_z = float(pose_d.position[2])
        print(
            "descent step:",
            down_idx,
            "current gripper:",
            cur_x,
            cur_y,
            cur_z,
            "final target z:",
            release_gripper_z,
        )
        if cur_z <= release_gripper_z + 0.010:
            descent_complete = True
            break
        target_z = max(release_gripper_z, cur_z - 0.025)
        step_ok = False
        for retry_idx in range(2):
            moved_down = move_to_pose(
                Pose(
                    position=(cur_x, cur_y, target_z), quaternion_wxyz=downward, frame="robot_base"
                ),
                tolerance=0.03,
                strategy=CU,
                max_steps=600,
            )
            report["release_down_" + str(down_idx) + "_" + str(retry_idx)] = moved_down.ok
            print("descent move ok:", moved_down.ok, "target z:", target_z, "retry:", retry_idx)
            if moved_down.ok:
                step_ok = True
                break
            state_a = get_robot_state()
            pose_a = state_a.end_effector_poses["primary"]
            after_x = float(pose_a.position[0])
            after_y = float(pose_a.position[1])
            after_z = float(pose_a.position[2])
            print(
                "descent move failed, gripper after:",
                after_x,
                after_y,
                after_z,
                "progress toward target, remaining:",
                after_z - target_z,
            )
            if after_z <= target_z + 0.018:
                step_ok = True
                break
            if retry_idx == 0:
                backoff = move_to_pose(
                    Pose(
                        position=(after_x, after_y, after_z + 0.025),
                        quaternion_wxyz=downward,
                        frame="robot_base",
                    ),
                    tolerance=0.03,
                    strategy=CU,
                    max_steps=500,
                )
                report["release_backoff_" + str(down_idx)] = backoff.ok
                print("descent backoff up 0.025 m ok:", backoff.ok)
                state_b = get_robot_state()
                pose_b = state_b.end_effector_poses["primary"]
                cur_x = float(pose_b.position[0])
                cur_y = float(pose_b.position[1])
        if step_ok:
            continue
        state_f = get_robot_state()
        pose_f = state_f.end_effector_poses["primary"]
        final_desc_z = float(pose_f.position[2])
        print("descent step failed after retries, gripper z:", final_desc_z)
        if final_desc_z <= release_gripper_z + 0.045:
            descent_close = True
        else:
            descent_failed = True
        break
    if not descent_complete and not descent_close and not descent_failed:
        state_e = get_robot_state()
        pose_e = state_e.end_effector_poses["primary"]
        end_z = float(pose_e.position[2])
        print("descent loop ended, gripper z:", end_z, "release z:", release_gripper_z)
        if end_z <= release_gripper_z + 0.010:
            descent_complete = True
        elif end_z <= release_gripper_z + 0.045:
            descent_close = True
        else:
            descent_failed = True
    if descent_failed:
        state_dir = get_robot_state()
        pose_dir = state_dir.end_effector_poses["primary"]
        direct_move = move_to_pose(
            Pose(
                position=(
                    float(pose_dir.position[0]),
                    float(pose_dir.position[1]),
                    release_gripper_z,
                ),
                quaternion_wxyz=downward,
                frame="robot_base",
            ),
            tolerance=0.04,
            strategy=CU,
            max_steps=900,
        )
        report["release_direct_retry"] = direct_move.ok
        print("direct move to release pose ok:", direct_move.ok)
        if direct_move.ok:
            descent_complete = True
            descent_failed = False
        else:
            state_dir2 = get_robot_state()
            pose_dir2 = state_dir2.end_effector_poses["primary"]
            direct_after_z = float(pose_dir2.position[2])
            print("direct move failed, gripper z after:", direct_after_z)
            if direct_after_z <= release_gripper_z + 0.045:
                descent_close = True
                descent_failed = False
    report["descent_complete"] = descent_complete
    report["descent_close_enough"] = descent_close
    report["descent_failed"] = descent_failed
    print(
        "descent outcome complete:",
        descent_complete,
        "close enough:",
        descent_close,
        "failed:",
        descent_failed,
    )

proceed_release = False
if ok_all and grasp_verified:
    state_pre = get_robot_state()
    pose_pre = state_pre.end_effector_poses["primary"]
    pre_gripper_x = float(pose_pre.position[0])
    pre_gripper_y = float(pose_pre.position[1])
    pre_gripper_z = float(pose_pre.position[2])
    est_bowl_x = pre_gripper_x - ux * used_offset
    est_bowl_y = pre_gripper_y - uy * used_offset
    est_dist = math.sqrt(
        (est_bowl_x - plate_center_x) * (est_bowl_x - plate_center_x)
        + (est_bowl_y - plate_center_y) * (est_bowl_y - plate_center_y)
    )
    width_pre = float(state_pre.gripper_positions["primary"])
    print(
        "before release estimated bowl center:",
        est_bowl_x,
        est_bowl_y,
        "distance to plate center:",
        est_dist,
        "plate radius:",
        plate_radius,
        "gripper z:",
        pre_gripper_z,
        "width:",
        width_pre,
    )
    report["estimated_bowl_distance_to_plate_before_release_m"] = est_dist
    report["width_before_release"] = width_pre
    if descent_complete or descent_close:
        proceed_release = True
    elif descent_failed and est_dist < plate_radius * 0.60:
        proceed_release = True
        report["release_from_height_fallback"] = True
        print(
            "descent failed but bowl is centred over plate, releasing as last resort instead of aborting"
        )
    else:
        ok_all = False
        print("not releasing, descent failed and bowl not centred over plate")

if proceed_release:
    released = open_gripper()
    released_ok = released.ok
    report["released"] = released_ok
    print("release open ok:", released_ok)
    if not released_ok:
        released_retry = open_gripper()
        released_ok = released_retry.ok
        report["released_retry"] = released_ok
        print("release open retry ok:", released_ok)
    if not released_ok:
        ok_all = False

if released_ok:
    state_retreat = get_robot_state()
    pose_retreat = state_retreat.end_effector_poses["primary"]
    retreat_pose = Pose(
        position=(
            float(pose_retreat.position[0]),
            float(pose_retreat.position[1]),
            float(pose_retreat.position[2]) + 0.14,
        ),
        quaternion_wxyz=pose_retreat.quaternion_wxyz,
        frame=pose_retreat.frame,
    )
    retreated = move_to_pose(retreat_pose, tolerance=0.03, strategy=CU, max_steps=500)
    report["retreated_after_release"] = retreated.ok
    print("retreated after release ok:", retreated.ok)
    if not retreated.ok:
        retreated_retry = move_to_pose(retreat_pose, tolerance=0.04, strategy=CU, max_steps=700)
        report["retreated_after_release_retry"] = retreated_retry.ok
        print("retreated after release retry ok:", retreated_retry.ok)
        retreated = retreated_retry
    if not retreated.ok:
        ok_all = False

if released_ok:
    final_check = localize_object("bowl", camera_name="agentview")
    report["final_bowl_localized"] = final_check.ok
    print("final bowl localized ok:", final_check.ok)
    if final_check.ok:
        final_points = final_check.point_cloud.points
        if len(final_points) >= 20:
            final_xs_sorted = sorted([float(p[0]) for p in final_points])
            final_ys_sorted = sorted([float(p[1]) for p in final_points])
            final_zs_sorted = sorted([float(p[2]) for p in final_points])
            final_n = len(final_points)
            final_center_x = final_xs_sorted[int(0.50 * (final_n - 1))]
            final_center_y = final_ys_sorted[int(0.50 * (final_n - 1))]
            final_bottom = final_zs_sorted[int(0.10 * (final_n - 1))]
            final_dist = math.sqrt(
                (final_center_x - plate_center_x) * (final_center_x - plate_center_x)
                + (final_center_y - plate_center_y) * (final_center_y - plate_center_y)
            )
            print(
                "final bowl center:",
                final_center_x,
                final_center_y,
                "bottom p10:",
                final_bottom,
                "distance to plate center:",
                final_dist,
                "plate radius:",
                plate_radius,
                "plate top:",
                plate_top_z,
            )
            report["final_bowl_center_x"] = final_center_x
            report["final_bowl_center_y"] = final_center_y
            report["final_bowl_bottom_p10"] = final_bottom
            report["final_distance_to_plate_m"] = final_dist
            report["final_on_plate_estimate"] = (
                final_dist < plate_radius * 0.60
                and final_bottom < plate_top_z + 0.04
                and final_bottom > plate_top_z - 0.03
            )

report["ok_all"] = ok_all
result = report

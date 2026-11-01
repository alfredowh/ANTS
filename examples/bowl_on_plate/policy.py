import math

report = {}
failed = False

ctx = get_task_context()
print("task language:", ctx.language)
report["language"] = str(ctx.language)

state = get_robot_state()
print("base frame:", state.base_frame)
frame_name = str(state.base_frame)
initial_pose = state.end_effector_poses["primary"]
initial_q = (float(initial_pose.quaternion_wxyz[0]), float(initial_pose.quaternion_wxyz[1]), float(initial_pose.quaternion_wxyz[2]), float(initial_pose.quaternion_wxyz[3]))
print("initial eef position:", initial_pose.position)
print("initial eef quaternion wxyz:", initial_q)
report["initial_eef"] = [float(initial_pose.position[0]), float(initial_pose.position[1]), float(initial_pose.position[2])]

opened = open_gripper()
report["open_initial"] = bool(opened.ok)
print("open_initial ok:", opened.ok)
if not opened.ok:
    failed = True

bowl_loc = None
if not failed:
    for query in ["the bowl", "bowl", "black bowl"]:
        cand = localize_object(query, camera_name="agentview")
        print("bowl query:", query, "ok:", cand.ok)
        if cand.ok:
            bowl_loc = cand
            break
    if bowl_loc is None or not bowl_loc.ok:
        report["bowl_localized"] = False
        failed = True
    else:
        report["bowl_localized"] = True

plate_loc = None
if not failed:
    for query in ["the plate", "plate", "white plate"]:
        cand = localize_object(query, camera_name="agentview")
        print("plate query:", query, "ok:", cand.ok)
        if cand.ok:
            plate_loc = cand
            break
    if plate_loc is None or not plate_loc.ok:
        report["plate_localized"] = False
        failed = True
    else:
        report["plate_localized"] = True

bowl_cx = 0.0
bowl_cy = 0.0
plate_cx = 0.0
plate_cy = 0.0
plate_r = 0.0
pinch_dist = 0.0
pinch_x = 0.0
pinch_y = 0.0
pinch_z = 0.0
pre_x = 0.0
pre_y = 0.0
pre_z = 0.0
ux = -1.0
uy = 0.0
carry_z = 0.0
release_gx = 0.0
release_gy = 0.0
release_z = 0.0
pinch_height = 0.0
plate_top_z = 0.0
target_q = initial_q

if not failed:
    bowl_points = bowl_loc.point_cloud.points
    bxs = [float(p[0]) for p in bowl_points]
    bys = [float(p[1]) for p in bowl_points]
    bzs = [float(p[2]) for p in bowl_points]
    bowl_cx = (min(bxs) + max(bxs)) / 2.0
    bowl_cy = (min(bys) + max(bys)) / 2.0
    bowl_geo = bowl_loc.geometry.pose.position
    print("bowl bounds center:", bowl_cx, bowl_cy, (min(bzs) + max(bzs)) / 2.0)
    print("bowl geometry center:", float(bowl_geo[0]), float(bowl_geo[1]), float(bowl_geo[2]))
    print("bowl geometry extents:", bowl_loc.geometry.extents)
    bowl_dx = max(bxs) - min(bxs)
    bowl_dy = max(bys) - min(bys)
    bowl_h = max(bzs) - min(bzs)
    bowl_d = max(bowl_dx, bowl_dy)
    bowl_r = bowl_d / 2.0
    table_z = min(bzs)

    plate_points = plate_loc.point_cloud.points
    pxs = [float(p[0]) for p in plate_points]
    pys = [float(p[1]) for p in plate_points]
    pzs = [float(p[2]) for p in plate_points]
    plate_cx = (min(pxs) + max(pxs)) / 2.0
    plate_cy = (min(pys) + max(pys)) / 2.0
    plate_geo = plate_loc.geometry.pose.position
    print("plate bounds center:", plate_cx, plate_cy, (min(pzs) + max(pzs)) / 2.0)
    print("plate geometry center:", float(plate_geo[0]), float(plate_geo[1]), float(plate_geo[2]))
    print("plate geometry extents:", plate_loc.geometry.extents)
    plate_dx = max(pxs) - min(pxs)
    plate_dy = max(pys) - min(pys)
    plate_h = max(pzs) - min(pzs)
    plate_d = max(plate_dx, plate_dy)
    plate_r = plate_d / 2.0
    plate_top_z = max(pzs)

    print("bowl diameter m:", bowl_d, "radius m:", bowl_r, "height m:", bowl_h, "table z:", table_z)
    print("plate diameter m:", plate_d, "radius m:", plate_r, "height m:", plate_h, "top z:", plate_top_z)
    report["bowl_diameter"] = float(bowl_d)
    report["bowl_height"] = float(bowl_h)
    report["plate_diameter"] = float(plate_d)

    if bowl_d < 0.02 or bowl_h < 0.008 or plate_r < 0.02:
        print("implausible measured sizes, stopping")
        failed = True
    else:
        scale_diameter = bowl_d / 0.138
        scale_height = bowl_h / 0.067
        pinch_height = 0.82 * bowl_h
        pinch_z = table_z + pinch_height
        demo_pinch_dist = 1.24 * bowl_r
        sideways_scaled = 0.041 * scale_diameter
        down_scaled = 0.027 * scale_height
        carry_height = 0.23 * scale_diameter
        demo_release_height = 0.14 * scale_diameter
        demo_release_dist = 0.67 * plate_r
        print("scale diameter:", scale_diameter, "scale height:", scale_height)
        print("demo scaled pinch dist 1.24R (hand centre, outside rim):", demo_pinch_dist)
        print("demo scaled approach sideways:", sideways_scaled, "down:", down_scaled)
        print("demo scaled carry height above table:", carry_height)
        print("demo scaled release offset 0.67 plate R:", demo_release_dist, "uncertain release height:", demo_release_height)

        radial_values = []
        for point in bowl_points:
            if abs(float(point[2]) - pinch_z) < 0.20 * bowl_h:
                dxp = float(point[0]) - bowl_cx
                dyp = float(point[1]) - bowl_cy
                radial_values.append(math.sqrt(dxp * dxp + dyp * dyp))
        if len(radial_values) >= 8:
            radial_sorted = sorted(radial_values)
            wall_radius = radial_sorted[len(radial_sorted) // 2]
        else:
            wall_radius = bowl_r
        print("wall radius at pinch height from points:", wall_radius, "samples:", len(radial_values))
        pinch_dist = wall_radius + 0.001
        if pinch_dist < 0.75 * bowl_r:
            pinch_dist = 0.75 * bowl_r
        if pinch_dist > 1.02 * bowl_r:
            pinch_dist = 1.02 * bowl_r
        print("chosen rim pinch dist from bowl axis (gripper centre on wall):", pinch_dist)
        report["pinch_dist"] = float(pinch_dist)
        report["pinch_height"] = float(pinch_height)

        norm = math.sqrt(bowl_cx * bowl_cx + bowl_cy * bowl_cy)
        if norm < 0.001:
            ux = -1.0
            uy = 0.0
        else:
            ux = -bowl_cx / norm
            uy = -bowl_cy / norm
        print("radial unit from bowl centre to pinch side (toward robot):", ux, uy)

        qw0 = initial_q[0]
        qx0 = initial_q[1]
        qy0 = initial_q[2]
        qz0 = initial_q[3]
        axis_x = 2.0 * (qx0 * qy0 - qw0 * qz0)
        axis_y = 1.0 - 2.0 * (qx0 * qx0 + qz0 * qz0)
        axis_z = 2.0 * (qy0 * qz0 + qw0 * qx0)
        print("initial gripper local-Y (finger closing) axis in world:", axis_x, axis_y, axis_z)
        delta = math.atan2(uy, ux) - math.atan2(axis_y, axis_x)
        delta = math.atan2(math.sin(delta), math.cos(delta))
        print("yaw rotation needed about world Z, deg:", math.degrees(delta))
        report["yaw_delta_deg"] = float(math.degrees(delta))
        half = delta / 2.0
        cq = math.cos(half)
        sq = math.sin(half)
        tw = cq * qw0 - sq * qz0
        tx = cq * qx0 - sq * qy0
        ty = cq * qy0 + sq * qx0
        tz = cq * qz0 + sq * qw0
        tnorm = math.sqrt(tw * tw + tx * tx + ty * ty + tz * tz)
        target_q = (tw / tnorm, tx / tnorm, ty / tnorm, tz / tnorm)
        print("target gripper quaternion wxyz (Pose, not rpy):", target_q)

        pinch_x = bowl_cx + ux * pinch_dist
        pinch_y = bowl_cy + uy * pinch_dist
        pre_x = pinch_x + ux * sideways_scaled
        pre_y = pinch_y + uy * sideways_scaled
        pre_z = pinch_z + down_scaled
        print("pinch pose xyz:", pinch_x, pinch_y, pinch_z)
        print("pre pinch pose xyz:", pre_x, pre_y, pre_z)

        carry_z = table_z + carry_height
        if carry_z < pinch_z + 0.10:
            carry_z = pinch_z + 0.10
        if carry_z < plate_top_z + pinch_height + 0.06:
            carry_z = plate_top_z + pinch_height + 0.06
        release_gx = plate_cx + ux * pinch_dist
        release_gy = plate_cy + uy * pinch_dist
        release_z = plate_top_z + pinch_height + 0.004
        print("carry eef z:", carry_z)
        print("release gripper xyz:", release_gx, release_gy, release_z)
        print("expected bowl centre at release:", release_gx - ux * pinch_dist, release_gy - uy * pinch_dist, "plate centre:", plate_cx, plate_cy)
        report["carry_z"] = float(carry_z)
        report["release_z"] = float(release_z)

if not failed:
    pre_stages = [
        ("transit_bowl_high", bowl_cx, bowl_cy, 0.22, initial_q, 0.04),
        ("approach_high", pre_x, pre_y, pre_z + 0.09, target_q, 0.035),
        ("pre_pinch", pre_x, pre_y, pre_z, target_q, 0.025),
        ("pinch_rim", pinch_x, pinch_y, pinch_z, target_q, 0.02),
    ]
    for stage in pre_stages:
        if failed:
            break
        stage_name = stage[0]
        stage_ok = False
        accept_dist = 0.03
        if stage_name == "pinch_rim":
            accept_dist = 0.016
        for attempt in range(3):
            target_pose = Pose(position=(float(stage[1]), float(stage[2]), float(stage[3])), quaternion_wxyz=stage[4], frame=frame_name)
            print("move stage:", stage_name, "attempt:", attempt, "target:", target_pose.position, target_pose.quaternion_wxyz)
            moved = move_to_pose(target_pose, tolerance=float(stage[5]), max_steps=260)
            report[stage_name] = bool(moved.ok)
            print("move stage:", stage_name, "ok:", moved.ok)
            if moved.ok:
                stage_ok = True
                break
            cur_state = get_robot_state()
            cur_pose = cur_state.end_effector_poses["primary"]
            cur_pos = cur_pose.position
            dxc = float(cur_pos[0]) - float(stage[1])
            dyc = float(cur_pos[1]) - float(stage[2])
            dzc = float(cur_pos[2]) - float(stage[3])
            dist = math.sqrt(dxc * dxc + dyc * dyc + dzc * dzc)
            cur_q = cur_pose.quaternion_wxyz
            dot = abs(float(cur_q[0]) * float(stage[4][0]) + float(cur_q[1]) * float(stage[4][1]) + float(cur_q[2]) * float(stage[4][2]) + float(cur_q[3]) * float(stage[4][3]))
            if dot > 1.0:
                dot = 1.0
            angle = 2.0 * math.acos(dot)
            print("after failed move: pos error m:", dist, "orientation error rad:", angle, "cur pos:", cur_pos)
            if dist <= accept_dist and angle < 0.35:
                print("accepting stage from measured pose despite move timeout")
                stage_ok = True
                report[stage_name] = True
                report[stage_name + "_accepted_by_pose"] = True
                break
        if not stage_ok:
            print("stage failed, stopping:", stage_name)
            failed = True

if not failed:
    closed = close_gripper()
    report["close_gripper"] = bool(closed.ok)
    print("close_gripper ok:", closed.ok, "gripper pos:", get_robot_state().gripper_positions["primary"])
    report["gripper_after_close"] = float(get_robot_state().gripper_positions["primary"])
    if not closed.ok:
        failed = True

if not failed:
    for lift_index in range(7):
        if failed:
            break
        cur_state = get_robot_state()
        cur_pos = cur_state.end_effector_poses["primary"].position
        print("lift check index:", lift_index, "cur z:", float(cur_pos[2]), "carry z:", carry_z)
        if float(cur_pos[2]) >= carry_z - 0.006:
            report["lift_carry"] = True
            break
        target_z = float(cur_pos[2]) + 0.05
        if target_z > carry_z:
            target_z = carry_z
        lift_ok = False
        for attempt in range(2):
            target_pose = Pose(position=(float(pinch_x), float(pinch_y), float(target_z)), quaternion_wxyz=target_q, frame=frame_name)
            print("lift move attempt:", attempt, "target:", target_pose.position)
            moved = move_to_pose(target_pose, tolerance=0.025, max_steps=200)
            print("lift move ok:", moved.ok)
            if moved.ok:
                lift_ok = True
                break
            check_pos = get_robot_state().end_effector_poses["primary"].position
            dxc = float(check_pos[0]) - pinch_x
            dyc = float(check_pos[1]) - pinch_y
            dzc = float(check_pos[2]) - target_z
            dist = math.sqrt(dxc * dxc + dyc * dyc + dzc * dzc)
            print("lift pos error after failure:", dist)
            if dist <= 0.025:
                lift_ok = True
                break
        report["lift_step_" + str(lift_index)] = bool(lift_ok)
        if not lift_ok:
            failed = True
    if not failed:
        report["lift_carry"] = True

if not failed:
    start_state = get_robot_state()
    start_pos = start_state.end_effector_poses["primary"].position
    start_x = float(start_pos[0])
    start_y = float(start_pos[1])
    print("carry start:", start_x, start_y, float(start_pos[2]), "goal gripper:", release_gx, release_gy, carry_z)
    for seg in range(3):
        if failed:
            break
        frac = float(seg + 1) / 3.0
        seg_x = start_x + (release_gx - start_x) * frac
        seg_y = start_y + (release_gy - start_y) * frac
        seg_ok = False
        for attempt in range(2):
            target_pose = Pose(position=(float(seg_x), float(seg_y), float(carry_z)), quaternion_wxyz=target_q, frame=frame_name)
            print("carry seg:", seg, "attempt:", attempt, "target:", target_pose.position)
            moved = move_to_pose(target_pose, tolerance=0.03, max_steps=220)
            print("carry seg ok:", moved.ok)
            if moved.ok:
                seg_ok = True
                break
            check_pos = get_robot_state().end_effector_poses["primary"].position
            dxc = float(check_pos[0]) - seg_x
            dyc = float(check_pos[1]) - seg_y
            dzc = float(check_pos[2]) - carry_z
            dist = math.sqrt(dxc * dxc + dyc * dyc + dzc * dzc)
            print("carry pos error after failure:", dist)
            if dist <= 0.03:
                seg_ok = True
                break
        report["carry_seg_" + str(seg)] = bool(seg_ok)
        if not seg_ok:
            failed = True
    if not failed:
        report["carry_over_plate"] = True

if not failed:
    for lower_index in range(7):
        if failed:
            break
        cur_state = get_robot_state()
        cur_pos = cur_state.end_effector_poses["primary"].position
        print("lower check index:", lower_index, "cur z:", float(cur_pos[2]), "release z:", release_z)
        if float(cur_pos[2]) <= release_z + 0.006:
            report["lower_to_plate"] = True
            break
        target_z = float(cur_pos[2]) - 0.045
        if target_z < release_z:
            target_z = release_z
        lower_ok = False
        for attempt in range(2):
            target_pose = Pose(position=(float(release_gx), float(release_gy), float(target_z)), quaternion_wxyz=target_q, frame=frame_name)
            print("lower move attempt:", attempt, "target:", target_pose.position)
            moved = move_to_pose(target_pose, tolerance=0.02, max_steps=200)
            print("lower move ok:", moved.ok)
            if moved.ok:
                lower_ok = True
                break
            check_pos = get_robot_state().end_effector_poses["primary"].position
            dxc = float(check_pos[0]) - release_gx
            dyc = float(check_pos[1]) - release_gy
            dzc = float(check_pos[2]) - target_z
            dist = math.sqrt(dxc * dxc + dyc * dyc + dzc * dzc)
            print("lower pos error after failure:", dist)
            if dist <= 0.02:
                lower_ok = True
                break
        report["lower_step_" + str(lower_index)] = bool(lower_ok)
        if not lower_ok:
            failed = True
    if not failed:
        report["lower_to_plate"] = True

if not failed:
    released = open_gripper()
    report["release_open"] = bool(released.ok)
    print("release_open ok:", released.ok)
    if not released.ok:
        failed = True

if not failed:
    retreat_ok = False
    for attempt in range(3):
        target_pose = Pose(position=(float(release_gx), float(release_gy), float(release_z + 0.12)), quaternion_wxyz=target_q, frame=frame_name)
        print("retreat attempt:", attempt, "target:", target_pose.position)
        moved = move_to_pose(target_pose, tolerance=0.03, max_steps=220)
        report["retreat"] = bool(moved.ok)
        print("retreat ok:", moved.ok)
        if moved.ok:
            retreat_ok = True
            break
        check_pos = get_robot_state().end_effector_poses["primary"].position
        dzc = float(check_pos[2]) - (release_z + 0.12)
        print("retreat z error after failure:", dzc, "cur pos:", check_pos)
        if dzc < 0.04 and dzc > -0.04:
            retreat_ok = True
            report["retreat"] = True
            break
    if not retreat_ok:
        failed = True

if not failed:
    final_loc = localize_object("the bowl", camera_name="agentview")
    report["final_bowl_localized"] = bool(final_loc.ok)
    print("final bowl localized ok:", final_loc.ok)
    if final_loc.ok:
        fpos = final_loc.geometry.pose.position
        fdx = float(fpos[0]) - plate_cx
        fdy = float(fpos[1]) - plate_cy
        dist = math.sqrt(fdx * fdx + fdy * fdy)
        print("final bowl centre:", float(fpos[0]), float(fpos[1]), float(fpos[2]), "plate centre:", plate_cx, plate_cy, "xy dist:", dist, "plate R:", plate_r)
        report["final_bowl_plate_xy_dist"] = float(dist)
        report["final_bowl_z"] = float(fpos[2])

report["failed"] = bool(failed)
report["success_steps"] = bool(not failed)
result = report

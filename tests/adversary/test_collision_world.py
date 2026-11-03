from ants.adversary.collision_world import (
    Box,
    describe,
    load_world,
    radial_profile,
    relations,
    view,
)

IDENT = [1, 0, 0, 0, 1, 0, 0, 0, 1]


def geom(name, body, pos, half):
    return {
        "name": name, "body": body, "type": 6, "size": half, "pos": pos, "xmat": IDENT,
        "contype": 1, "conaffinity": 1,
    }  # fmt: skip


def dump():
    bodies = {
        "world": {"root": "world", "mass": 0.0, "pos": [0, 0, 0]},
        "robot0_base": {"root": "robot0_base", "mass": 1.0, "pos": [-0.5, 0.0, 0.9]},
        "table": {"root": "table", "mass": 100.0, "pos": [0, 0, 0.8]},
        "plate_1_main": {"root": "plate_1_main", "mass": 0.2, "pos": [0, 0, 0]},
        "wine_rack_1_main": {"root": "wine_rack_1_main", "mass": 0.6, "pos": [0, 0, 0]},
        "wooden_cabinet_1_main": {"root": "wooden_cabinet_1_main", "mass": 0.0, "pos": [0, 0, 0]},
        "wooden_cabinet_1_base": {"root": "wooden_cabinet_1_main", "mass": 0.0, "pos": [0, 0, 0]},
    }
    geoms = [
        geom("t", "table", [0, 0, 0.8], [1, 1, 0.1]),  # top at world z 0.9 -> base frame 0.0
        geom("p", "plate_1_main", [0.0, 0.0, 0.92], [0.1, 0.1, 0.02]),  # bottom at 0.90
        geom("r1", "wine_rack_1_main", [0.0, 0.3, 1.0], [0.1, 0.1, 0.1]),  # gap 0.1 to plate
        geom("c", "wooden_cabinet_1_base", [0.0, 0.9, 1.0], [0.1, 0.1, 0.1]),  # far away
    ]
    return {"bodies": bodies, "geoms": geoms}


def test_world_is_in_the_robot_base_frame():
    w = load_world(dump())
    assert abs(w.table_top_z) < 1e-9
    plate = w.get("plate")
    assert abs(plate.aabb.centre[0] - 0.5) < 1e-9
    assert [o.label for o in w.objects] == ["plate", "wine rack", "wooden cabinet"]
    assert w.get("wooden cabinet").movable is False and w.get("plate").movable is True


def test_relations_and_describe_levels():
    w = load_world(dump())
    kinds = {(r.a, r.b, r.kind) for r in relations(w)}
    assert ("plate", "table", "supported_by") in kinds
    assert ("plate", "wine rack", "near") in kinds
    assert not any(r.b == "wooden cabinet" and r.kind != "supported_by" for r in relations(w))
    pos, ext, graph, combo = (
        describe(w, lvl) for lvl in ("positions", "extents", "graph", "combo")
    )
    assert "size" not in pos and "size" in ext and "Relations" not in ext
    assert "Relations" in graph and "gap 100 mm" in graph
    assert "round" in combo and "Gripper" in combo and "Gripper" not in graph


def test_shifting_an_object_changes_its_gap():
    w = load_world(dump())
    moved = w.shifted("wine rack", 0.0, 0.5)
    assert w.get("plate").gap(moved.get("wine rack")) > w.get("plate").gap(w.get("wine rack"))


def test_box_gap_and_profile():
    a, b = Box((0, 0, 0), (1, 1, 1)), Box((2, 0, 0), (3, 1, 1))
    assert a.gap(b) == 1.0 and a.gap(a) == 0.0
    axis, rings = radial_profile(load_world(dump()).get("plate"))
    assert rings and rings[0][1] > 0.09
    assert view(load_world(dump()))["objects"][0]["profile"] is not None

"""Live sector boundary walls and invisible sky ceiling collision."""

from collections import defaultdict
from collections.abc import Iterable
from typing import Any, cast

import ue


def ceiling(mode: Any, index: int) -> float:
    offset = (
        mode.doors[index]["height"] if index in mode.doors else mode.ceilings.get(index, {}).get("offset", 0)
    )
    return float(mode.data["sectors"][index]["ceiling"]) + float(offset)


def mover_order(mode: Any) -> list[tuple[str, int]]:
    """Every moving sector in an order both machines derive from the same map: doors, floors, ceilings."""
    order = cast("list[tuple[str, int]] | None", getattr(mode, "mover_order_cache", None))
    if order is None or len(order) != len(mode.doors) + len(mode.movers) + len(mode.ceilings):
        order = [
            *(("door", int(i)) for i in sorted(mode.doors)),
            *(("floor", int(i)) for i in sorted(mode.movers)),
            *(("ceiling", int(i)) for i in sorted(mode.ceilings)),
        ]
        mode.mover_order_cache = order
    return order


def mover_values(mode: Any) -> list[float]:
    """The doors' heights and the floors' and ceilings' offsets, in `mover_order`."""
    return [
        float(
            mode.doors[i]["height"]
            if kind == "door"
            else mode.movers[i]["offset"]
            if kind == "floor"
            else mode.ceilings[i]["offset"]
        )
        for kind, i in mover_order(mode)
    ]


def set_mover(mode: Any, kind: str, index: int, value: float) -> None:
    """Move one door, floor or ceiling (a client applying the server's state)."""
    from doom.campaign import game

    state = (mode.doors if kind == "door" else mode.movers if kind == "floor" else mode.ceilings)[index]
    key = "height" if kind == "door" else "offset"
    if state[key] == value:
        return
    state[key] = value
    mode.geo_dirty.add(index)
    if state["actor"]:
        state["actor"].set_actor_location(ue.Vector(0, 0, value * game().SCALE), False, True)


def register_button(mode: Any, line_index: int, material: Any, texture: str) -> None:
    """Remember a switch face's material and load its SW1/SW2 counterpart now, not on the press.

    Loading the other texture when the player presses the switch would hand the material a texture whose
    render resource is not ready yet for the first frames, drawing the whole face with the default texture.
    """
    mode.button_materials.setdefault(line_index, []).append((material, texture))
    mode.texture(("SW2" if texture.startswith("SW1") else "SW1") + texture[3:])


def prepare(mode: Any) -> None:
    mode.wall_faces = []
    mode.sky_faces = []
    mode.clearance_faces = []
    mode.geo_index = None
    mode.geo_dirty = set()
    mode.mover_order_cache = None


def register(
    mode: Any,
    side: dict[str, Any],
    a: Any,
    b: Any,
    si: int,
    oi: int,
    upper: bool,
    line_index: int,
    light: float,
) -> None:
    texture = side["upper" if upper else "lower"]
    sectors = mode.data["sectors"]
    if texture == "-" or (upper and sectors[si]["ceiling_tex"] == sectors[oi]["ceiling_tex"] == "F_SKY1"):
        return
    material = mode.material(texture, sector=len(sectors) + line_index)
    if texture.startswith(("SW1", "SW2")):
        register_button(mode, line_index, material, texture)
    if mode.data["lines"][line_index]["special"] == 48:
        mode.scroll_materials[(line_index, texture)] = (material, mode.data["textures"][texture][0])
    mode.wall_faces.append(
        dict(
            side=side,
            a=a,
            b=b,
            si=si,
            oi=oi,
            upper=upper,
            line=line_index,
            texture=texture,
            material=material,
            light=light,
            bounds=None,
        )
    )


def create(mode: Any) -> None:
    from doom.campaign import game

    g = game()
    mode.wall_geometry = ue.spawn_actor(g.DoomGeometry)
    mode.sky_geometry = ue.spawn_actor(g.DoomGeometry)
    mode.clearance_geometry = ue.spawn_actor(g.DoomGeometry)
    for actor in (mode.wall_geometry, mode.sky_geometry):
        actor.mesh.set_collision_profile_name("BlockAll")
        actor.mesh.use_complex_as_simple_collision = True
        mode.geometry.append(actor)
    mode.sky_geometry.set_actor_hidden_in_game(True)
    mode.sky_geometry.mesh.set_collision_response_to_channel(
        ue.ECollisionChannel.ECC_Visibility, ue.ECollisionResponse.ECR_Ignore
    )
    clearance = mode.clearance_geometry
    clearance.set_actor_hidden_in_game(True)
    clearance.mesh.set_collision_profile_name("BlockAll")
    clearance.mesh.use_complex_as_simple_collision = True
    clearance.mesh.set_collision_response_to_all_channels(ue.ECollisionResponse.ECR_Ignore)
    clearance.mesh.set_collision_response_to_channel(
        ue.ECollisionChannel.ECC_Pawn, ue.ECollisionResponse.ECR_Block
    )
    mode.geometry.append(clearance)
    for line in mode.data["lines"]:
        if line["left"] == 65535 or line["right"] == 65535 or line["flags"] & 1:
            continue
        mode.clearance_faces.append(
            dict(
                a=mode.data["vertices"][line["a"]],
                b=mode.data["vertices"][line["b"]],
                si=mode.data["sides"][line["right"]]["sector"],
                oi=mode.data["sides"][line["left"]]["sector"],
                bounds=None,
            )
        )
    index_faces(mode)
    refresh(mode)


def index_faces(mode: Any) -> None:
    """Sector -> face indices, built once per level (faces never change sector membership)."""
    walls, clearances, skies = (defaultdict[int, list[int]](list) for _ in range(3))
    for i, face in enumerate(mode.wall_faces):
        walls[face["si"]].append(i)
        if face["oi"] != face["si"]:
            walls[face["oi"]].append(i)
    for i, face in enumerate(mode.clearance_faces):
        clearances[face["si"]].append(i)
        if face["oi"] != face["si"]:
            clearances[face["oi"]].append(i)
    for i, face in enumerate(mode.sky_faces):
        skies[face["sector"]].append(i)
    mode.geo_index = (walls, clearances, skies)


def refresh_changed(mode: Any) -> None:
    """Refresh only the faces of sectors that moved this frame (mode.geo_dirty, filled by the movers)."""
    if mode.geo_dirty:
        changed, mode.geo_dirty = mode.geo_dirty, set()
        mode.geo_version += 1  # Invalidates the monsters' path-search memo.
        refresh(mode, changed)


def refresh(mode: Any, sectors: set[int] | None = None) -> None:
    from doom.campaign import game

    g = game()
    if sectors is None:
        mode.geo_dirty = set()
        clearance_ids: Iterable[int] = range(len(mode.clearance_faces))
        wall_ids: Iterable[int] = range(len(mode.wall_faces))
        sky_ids: Iterable[int] = range(len(mode.sky_faces))
    else:
        walls, clearances, skies = mode.geo_index
        clearance_ids = sorted({n for s in sectors for n in clearances.get(s, ())})
        wall_ids = sorted({n for s in sectors for n in walls.get(s, ())})
        sky_ids = sorted({n for s in sectors for n in skies.get(s, ())})
    # CMC needs a slightly shorter physical capsule to accommodate its floor hover.
    # Preserve Doom's logical 56-unit headroom at every opening, including moving doors.
    for index in clearance_ids:
        face = mode.clearance_faces[index]
        si, oi = face["si"], face["oi"]
        floor = max(mode.sector_floor(si), mode.sector_floor(oi))
        top = min(ceiling(mode, si), ceiling(mode, oi))
        bounds = None if top - floor >= 56 - 1e-6 else (floor, floor + 56)
        if bounds == face["bounds"]:
            continue
        face["bounds"] = bounds
        if bounds is None:
            mode.clearance_geometry.mesh.clear_mesh_section(index)
            continue
        a, b = face["a"], face["b"]
        low, high = bounds
        g.section(
            mode.clearance_geometry.mesh,
            index,
            [
                g.vec(a[0], a[1], low),
                g.vec(b[0], b[1], low),
                g.vec(b[0], b[1], high),
                g.vec(a[0], a[1], high),
            ],
            [0, 1, 2, 0, 2, 3],
            [ue.Vector2D(0, 0) for _ in range(4)],
            1,
            None,
        )
    for index in wall_ids:
        face = mode.wall_faces[index]
        si, oi = face["si"], face["oi"]
        low, high = (
            (ceiling(mode, oi), ceiling(mode, si))
            if face["upper"]
            else (mode.sector_floor(si), mode.sector_floor(oi))
        )
        bounds = (low, high, ceiling(mode, si))
        if face["bounds"] == bounds:
            continue
        face["bounds"] = bounds
        if high <= low:
            mode.wall_geometry.mesh.clear_mesh_section(index)
            continue
        side, a, b = face["side"], face["a"], face["b"]
        w, h = mode.data["textures"][face["texture"]]
        length = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        flags = mode.data["lines"][face["line"]]["flags"]
        if face["upper"]:
            anchor = high if flags & 8 else low + h
        else:
            anchor = ceiling(mode, si) if flags & 16 else high
        u0, u1 = side["x"] / w, (side["x"] + length) / w
        v0, v1 = (side["y"] + anchor - low) / h, (side["y"] + anchor - high) / h
        g.section(
            mode.wall_geometry.mesh,
            index,
            [
                g.vec(a[0], a[1], low),
                g.vec(b[0], b[1], low),
                g.vec(b[0], b[1], high),
                g.vec(a[0], a[1], high),
            ],
            [0, 1, 2, 0, 2, 3],
            [ue.Vector2D(u0, v0), ue.Vector2D(u1, v0), ue.Vector2D(u1, v1), ue.Vector2D(u0, v1)],
            face["light"],
            face["material"],
        )
    for index in sky_ids:
        face = mode.sky_faces[index]
        height = ceiling(mode, face["sector"])
        if face.get("height") == height:
            continue
        face["height"] = height
        points = face["points"]
        triangles = [n for i in range(1, len(points) - 1) for n in (0, i + 1, i)]
        g.section(
            mode.sky_geometry.mesh,
            index,
            [g.vec(p[0], p[1], height) for p in points],
            triangles,
            [ue.Vector2D(0, 0) for _ in points],
            1,
            mode.material("STARTAN3"),
        )

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

import ue
from doom import lighting
from doom.animation import BARREL_EXPLOSION as BARREL_EXPLOSION
from doom.animation import WEAPON_FRAMES
from doom.dataset import CONTENT
from doom.rules import (
    AMMO_PICKUPS,
    COUNT_ITEMS,
    KEY_PICKUPS,
    MONSTERS,
    THING_SPRITES,
    WEAPON_PICKUPS,
    WEAPONS,
)

if TYPE_CHECKING:
    from doom import mode as _mode

MODE = "/Script/UnrealPyTypes.DoomHangarMode"
# Moving floors: geometry groups are keyed by sector for doors, FLOOR_KEY + sector for floors.
FLOOR_KEY = 100000
CEILING_KEY = 200000
# Floor specials of E1M1: (kind, speed in map units per second); Doom moves 1 unit per tic slowly, 4 fast.
FLOOR_SPECIALS = {88: ("lift", 140.0), 36: ("highest8", 140.0), 38: ("lowest", 35.0)}
# Specials triggered by walking over the line: W1 once, WR (88) every time.
WALK_SPECIALS = (88, 36, 38, 109)
SCALE = 2.0
KEYS = {
    k: ue.Key(key_name=k)
    for k in (
        "W",
        "A",
        "S",
        "D",
        "LeftShift",
        "LeftMouseButton",
        "MouseScrollUp",
        "MouseScrollDown",
        "E",
        "R",
        "Tab",
        "One",
        "Two",
        "Three",
        "Escape",
        "Enter",
        "Up",
        "Down",
        "Left",
        "Right",
        "F5",
        "F9",
        "Four",
        "Five",
        "Six",
        "Seven",
        "Eight",
    )
}
ITEMS = {
    2011: "STIMA0",
    2012: "MEDIA0",
    2014: "BON1A0",
    2015: "BON2A0",
    2018: "ARM1A0",
    2019: "ARM2A0",
    2007: "CLIPA0",
    2008: "SHELA0",
    2048: "AMMOA0",
    2049: "SBOXA0",
    2001: "SHOTA0",
    2002: "MGUNA0",
    2003: "LAUNA0",
    2005: "CSAWA0",
    2046: "BROKA0",
    2023: "PSTRA0",
}
DECOR = {
    2035: "BAR1A0",
    2028: "COLUA0",
    24: "POL5A0",
    15: "PLAYN0",
    35: "CBRAA0",
    48: "ELECA0",
    10: "PLAYW0",
    12: "PLAYW0",
}
DEMONS = MONSTERS
DECOR.update(THING_SPRITES)
ITEMS.update(
    {
        kind: THING_SPRITES[kind]
        for kind in THING_SPRITES
        if kind in {*AMMO_PICKUPS, *KEY_PICKUPS, *WEAPON_PICKUPS, *COUNT_ITEMS, 8}
    }
)
WHITE = ue.LinearColor(1, 1, 1, 1)
TIC = 1 / 35


def weapon_frame(weapon: str, elapsed: float) -> str:
    """The weapon's frame `elapsed` seconds into its firing animation (its idle frame after)."""
    t = 0.0
    for frame, tics in WEAPON_FRAMES[weapon]:
        t += tics * TIC
        if elapsed < t:
            return frame
    return str(WEAPONS[weapon]["idle"])


def weapon_time(weapon: str) -> float:
    return sum(tics for _, tics in WEAPON_FRAMES[weapon]) * TIC


def weapon_aim_x(weapon: str, sprites: dict[str, Any]) -> float:
    """Horizontal centre of the idle weapon, in the HUD's original 320-pixel coordinates."""
    frame = weapon_frame(weapon, math.inf)
    width, _, left, _ = sprites[frame]
    return float(-left + width / 2)


def components(v: Any) -> tuple[float, float, float]:
    """x, y, z of a vector, whether it was built with ue.Vector() or returned by the engine."""
    try:
        return float(v.x), float(v.y), float(v.z)
    except AttributeError:
        return float(v[0]), float(v[1]), float(v[2])


def vec(x: float, y: float, z: float = 0) -> ue.Vector:
    return ue.Vector(x * SCALE, -y * SCALE, z * SCALE)


_cached_mode: Any = None
_cached_player: ue.Pawn | None = None


def mode_now() -> _mode.DoomHangarMode | None:
    """The Doom runtime of this machine: the game mode on the server, the game state on a client.

    Typed as the game mode: a client's game state offers the part of its API a client needs (the level, the
    sounds, the HUD fields), and the simulation only ever runs where the real game mode is.
    """
    global _cached_mode, _cached_player
    if _cached_mode is not None and _cached_mode.is_valid():
        return cast("_mode.DoomHangarMode", _cached_mode)
    from doom import level as _level_mod

    mode: Any = ue.GameplayStatics.get_game_mode()
    if not isinstance(mode, _level_mod.LevelRuntime):
        mode = ue.GameplayStatics.get_game_state()
    _cached_mode = mode if isinstance(mode, _level_mod.LevelRuntime) else None
    _cached_player = None
    return cast("_mode.DoomHangarMode | None", _cached_mode)


def player_now() -> ue.Pawn | None:
    """Player pawn 0 (same as GameplayStatics.get_player_pawn(0)), cached while the pawn stays alive."""
    global _cached_player
    if _cached_player is not None and _cached_player.is_valid():
        return _cached_player
    _cached_player = ue.GameplayStatics.get_player_pawn(0)
    return _cached_player


def clear_cache() -> None:
    global _cached_mode, _cached_player
    _cached_mode = _cached_player = None


def segments_cross(p: Sequence[float], q: Sequence[float], a: Sequence[float], b: Sequence[float]) -> bool:
    def side(o: Sequence[float], u: Sequence[float], v: Sequence[float]) -> float:
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])

    return side(p, q, a) * side(p, q, b) < 0 and side(a, b, p) * side(a, b, q) < 0


def xy(actor: ue.Actor) -> tuple[float, float]:
    p = actor.get_actor_location()
    return float(p[0]) / SCALE, -float(p[1]) / SCALE


def ray(start: Any, end: Any, ignore: Sequence[ue.Actor]) -> tuple[ue.Actor | None, Any]:
    result = ue.line_trace(ue.get_world(), start, end, ue.ECollisionChannel.ECC_Visibility, ignore, True)
    return (result[0] if result else None), result


def sprite_material(mode: Any, key: str, flipped: bool = False, fuzz: bool = False) -> Any:
    """Billboard material instance for a sprite lump: the patch is mapped into a pivot-centred quad.

    The camera-facing quad is centred on its component, so the Doom pivot (patch left offset) becomes
    a U scale/offset on the material, mirrored when `flipped`; texels outside the patch are masked.
    """
    cache_key = (key, "billboard", flipped, fuzz)
    if cache_key not in mode.materials:
        parent = ue.load_object(
            CONTENT + "/M_Fuzz.M_Fuzz" if fuzz else lighting.parent_path("M_SpriteBillboard")
        )
        assert isinstance(parent, ue.MaterialInterface), "Run doom.importer:main in editor first"
        mat = ue.KismetMaterialLibrary.create_dynamic_material_instance(parent)
        assert mat is not None
        width, _, left, _ = mode.data["sprites"][key]
        lo, hi = (left - width, left) if flipped else (-left, width - left)
        quad = 2 * max(abs(lo), abs(hi))
        # The patch's +x runs towards the viewer's left, as on the old facing quads (u grows rightwards).
        if flipped:
            scale, offset = quad / width, 1 - (quad / 2 - lo) / width
        else:
            scale, offset = -quad / width, (quad / 2 - lo) / width
        mat.set_texture_parameter_value("DoomTexture", mode.texture(key, True))
        mat.set_scalar_parameter_value("DoomUScale", scale)
        mat.set_scalar_parameter_value("DoomUOffset", offset)
        if lighting.active() and not fuzz:
            lighting.tune_sprite(mat, key)
        mode.materials[cache_key] = mat
    return mode.materials[cache_key]


def show_sprite(
    billboard: ue.MaterialBillboardComponent,
    mode: Any,
    key: str,
    flipped: bool = False,
    base_z: float = 0.0,
    floor_clip: bool = False,
    fuzz: bool = False,
) -> None:
    """Point a camera-facing billboard at a sprite lump with its Doom pivot (feet on the floor)."""
    width, height, left, top = mode.data["sprites"][key]
    if floor_clip:
        # Doom's patch offsets may extend below the floor; depth-tested UE quads cannot.
        top += max(0, height - top) + 0.5
    lo, hi = (left - width, left) if flipped else (-left, width - left)
    billboard.set_elements(
        [
            ue.MaterialSpriteElement(
                material=sprite_material(mode, key, flipped, fuzz),
                size_is_in_screen_space=False,
                # Unreal reads the sizes as half extents, X along the camera's up axis and Y along its right.
                base_size_x=height * SCALE / 2,
                base_size_y=max(abs(lo), abs(hi)) * SCALE,
            )
        ]
    )
    billboard.set_relative_location(ue.Vector(0, 0, base_z + (top - height / 2) * SCALE), False, True)


def section(
    mesh: ue.ProceduralMeshComponent,
    index: int,
    vertices: list[Any],
    triangles: list[int],
    uv: list[Any],
    light: float,
    material: ue.MaterialInterface | None,
    collision: bool = True,
) -> None:
    mesh.create_mesh_section_linear_color(
        index,
        vertices,
        triangles,
        lighting.surface_normals(vertices, triangles) if lighting.supported() else [],
        uv,
        [],
        [],
        [],
        [ue.LinearColor(light, light, light, 1) for _ in vertices],
        [],
        collision,
    )
    if material is not None:
        mesh.set_material(index, material)

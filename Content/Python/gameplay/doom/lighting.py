"""Lumen lighting for Doom, used when the project settings allow it (else Doom's flat unlit look).

Nothing is forced: the game reads the running engine's console variables (what the project settings set) and
switches to the lit mode only when Lumen GI and reflections, hardware ray tracing and the skin cache are all
on (see `missing_settings`); otherwise it keeps the unlit look. `DOOM_LIGHTING=unlit` forces the classic look,
`DOOM_LIGHTING=lit` asks for the lit mode and logs one warning naming the missing settings when it cannot run.
Needs the lit materials, which the editor's WAD importer creates next to the unlit ones.

What lights the level:
- every lit material emits a little of its texture, scaled by the sector light level, and Lumen bounces
  that emission around, so bright sectors light their dark neighbours and the mood of the map survives;
- switches, computer screens and lamp textures also emit their bright, saturated pixels (`GLOW_CLASSES`),
  so they light the walls and floor around them;
- point lights on torches, lamps, candles, burning barrels and the glowing items;
- flickering/blinking light sectors drive a point light under their ceiling;
- a sun and a sky light, for the sectors whose ceiling is sky;
- short-lived point lights for muzzle flashes, fireballs, plasma, rockets and explosions.

The pause menu has three test sliders while the lit mode is on (see `SLIDERS`): world brightness (the emissive
parameters already on every material instance, scaled), light intensity (point lights, sun, flashes) and an
exposure bias (an unbound post process volume). All are live, kept for the session and neutral by default.

Everything is Python through UnrealPy. Procedural meshes have no distance fields, so Lumen needs hardware
ray tracing with hit lighting (see README.md).
"""

from __future__ import annotations

import fnmatch
import math
import os
from typing import Any

import ue
from doom import wad
from doom.dataset import ASSETS, CONTENT

# The classic look's screen settings, applied on every machine that shows the level (server and clients).
DISPLAY_CVARS = (
    "r.EyeAdaptationQuality 0",  # Doom's fixed exposure: the engine's auto exposure would blow the level out
    "r.AntiAliasingMethod 0",
    "r.MotionBlurQuality 0",
    "r.ScreenPercentage 100",
    "r.DynamicRes.OperationMode 0",
)
# Runtime console variables applied when a level starts in the lit mode (Lumen tuning, not project settings).
RUNTIME_CVARS = (
    "r.Lumen.HardwareRayTracing.LightingMode 2",
    "r.Lumen.TraceMeshSDFs 0",
    "r.LumenScene.DirectLighting.HardwareRayTracing 1",
)
LIT_ASSETS = ("M_WorldLit", "M_MaskedWorldLit", "M_SpriteLit", "M_SpriteBillboardLit")
# console variable -> (value that is required, project setting that sets it)
REQUIRED_SETTINGS: tuple[tuple[str, int, str], ...] = (
    ("r.DynamicGlobalIlluminationMethod", 1, "Dynamic Global Illumination Method = Lumen"),
    ("r.ReflectionMethod", 1, "Reflection Method = Lumen"),
    ("r.RayTracing", 1, "Support Hardware Ray Tracing (needs DirectX 12 with SM6)"),
    ("r.Lumen.HardwareRayTracing", 1, "Use Hardware Ray Tracing when available"),
    ("r.SkinCache.CompileShaders", 1, "Support Compute Skin Cache"),
)

_lit: list[bool | None] = [None]  # the session's choice: decided at the first level start, then the menu's
_problems: list[list[str] | None] = [None]  # missing settings (cached: project settings cannot change)
_startup: dict[str, int] = {}  # Lumen method cvars as the project settings had them, restored when lit
RUNTIME_METHOD_CVARS = ("r.DynamicGlobalIlluminationMethod", "r.ReflectionMethod")


def missing_settings() -> list[str]:
    """Project settings the running engine lacks for the lit mode (empty when it can run)."""
    if _problems[0] is None:
        for name in RUNTIME_METHOD_CVARS:
            _startup[name] = ue.KismetSystemLibrary.get_console_variable_int_value(name)
        _problems[0] = [
            label
            for name, wanted, label in REQUIRED_SETTINGS
            if ue.KismetSystemLibrary.get_console_variable_int_value(name) != wanted
        ]
        if not _problems[0] and not _assets_ready():
            _problems[0] = ["lit materials (import the selected WAD in the editor)"]
    return list(_problems[0])


def supported() -> bool:
    """True when the engine and the imported assets allow the lit mode (whatever is currently shown)."""
    return not missing_settings()


def _assets_ready() -> bool:
    return all(isinstance(ue.load_object(f"{CONTENT}/{n}.{n}"), ue.MaterialInterface) for n in LIT_ASSETS)


def decide() -> bool:
    """Lit mode or not: `DOOM_LIGHTING` (unlit|lit|auto, default auto) and what the engine supports."""
    wanted = os.environ.get("DOOM_LIGHTING", "auto").strip().lower()
    problems = missing_settings()
    if wanted in ("unlit", "off", "flat"):
        return False
    if problems and wanted in ("lit", "lumen", "on"):
        ue.log(
            "Doom: DOOM_LIGHTING=lit needs these project settings, using the unlit look: "
            + "; ".join(problems),
            "warning",
        )
    return not problems


def active() -> bool:
    """True when the game runs in the lit (Lumen) mode."""
    if _lit[0] is None:
        _lit[0] = decide()
    return _lit[0]


def parent_path(name: str, sky: bool = False) -> str:
    """Content path of a base material: its lit variant in lumen mode (the sky is the same unlit M_Sky)."""
    if sky:
        return f"{CONTENT}/M_Sky.M_Sky"
    suffix = "Lit" if active() else ""
    return f"{CONTENT}/{name}{suffix}.{name}{suffix}"


def surface_normals(vertices: list[Any], triangles: list[int]) -> list[Any]:
    """Per-vertex normals of a flat-shaded section (area weighted), facing like the section's winding."""
    sums = [[0.0, 0.0, 0.0] for _ in vertices]
    for i in range(0, len(triangles) - 2, 3):
        a, b, c = (vertices[triangles[i + k]] for k in range(3))
        ux, uy, uz = b.x - a.x, b.y - a.y, b.z - a.z
        vx, vy, vz = c.x - a.x, c.y - a.y, c.z - a.z
        # Unreal is left-handed with clockwise front faces: the front normal is (c - a) x (b - a).
        nx, ny, nz = vy * uz - vz * uy, vz * ux - vx * uz, vx * uy - vy * ux
        for k in range(3):
            s = sums[triangles[i + k]]
            s[0] += nx
            s[1] += ny
            s[2] += nz
    out = []
    for nx, ny, nz in sums:
        length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        out.append(ue.Vector(nx / length, ny / length, nz / length))
    return out


FULLBRIGHT = (
    # Doom draws these frames fullbright: fire, magic, projectiles and explosions, torches, lamps, spheres.
    "BAL1", "BAL2", "BAL7", "MISL", "PLSS", "PLSE", "BFS1", "BFE1", "BFE2", "BEXP", "TFOG", "IFOG",
    "TBLU", "TGRN", "TRED", "SMBT", "SMGT", "SMRT", "CAND", "CBRA", "COLU", "FCAN", "FSKU", "CEYE",
    "SOUL", "PINV", "PINS", "MEGA", "PSTR", "PVIS", "PUFF", "BLUD",
)  # fmt: skip


EMISSIVE_MIN = float(os.environ.get("DOOM_EMISSIVE_MIN", "0.20"))
EMISSIVE_SCALE = float(os.environ.get("DOOM_EMISSIVE_SCALE", "0.70"))
SPRITE_EMISSIVE = float(os.environ.get("DOOM_SPRITE_EMISSIVE", "0.35"))


# Textures that glow in the lit mode (Doom and Freedoom names). A texel glows when its brightest channel plus
# `chroma` times its saturation passes the threshold (smoothstep over `band`), so screens, buttons and lamp
# pixels emit while the grey frame around them stays dark. `strength` multiplies the texture colour.
# (category, strength, chroma weight, threshold, band, name patterns); the first category that matches wins.
GLOW_CLASSES: tuple[tuple[str, float, float, float, float, tuple[str, ...]], ...] = (
    ("switch: wall buttons, both states", 3.0, 1.0, 0.70, 0.30, ("SW1*", "SW2*")),
    ("screen: computers, monitors, panels", 3.0, 1.0, 0.70, 0.30, ("COMP*", "PLANET1", "SPACEW*")),
    (
        "lamp: light strips, fixtures, ceiling and floor lights",
        4.0,
        0.0,
        0.60,
        0.15,
        ("LITE*", "TLITE*", "TEKLITE*", "GRNLITE*", "CEIL1_2", "CEIL1_3", "CEIL3_4", "FLAT2", "FLAT17",
         "FLOOR1_7"),
    ),
)  # fmt: skip
GLOW_MIX = float(os.environ.get("DOOM_GLOW", "1.0"))  # overall multiplier of every strength above and below

# Liquids and fire (flats and walls): glow of the whole texture (threshold < 0) or only of its bright cracks,
# and the surface gloss Lumen reflects. Lava is strong orange, nukage a weaker green, blood dim, water does
# not glow but is a mirror. (category, glow strength, chroma weight, threshold, band, roughness, specular,
# name patterns); the walls (switch/screen/lamp table above) are looked up first.
LIQUIDS: tuple[tuple[str, float, float, float, float, float, float, tuple[str, ...]], ...] = (
    ("lava: strong orange glow, semi-glossy", 3.0, 0.0, -1.0, 0.1, 0.35, 0.5, ("LAVA*",)),
    ("lava rock: bright cracks", 3.0, 1.0, 0.7, 0.3, 1.0, 0.0, ("RROCK0[5-8]", "SLIME09", "SLIME1[0-2]")),
    ("fire walls: glow like lava", 2.5, 0.0, -1.0, 0.1, 1.0, 0.0, ("FIRE*",)),
    ("nukage, acid, slime: weaker glow", 1.2, 0.0, -1.0, 0.1, 0.3, 0.6, ("NUKAGE*", "SLIME0[1-8]")),
    ("blood and its falls: dim red glow", 0.4, 0.0, -1.0, 0.1, 0.45, 0.4, ("BLOOD*", "BFALL*")),
    ("slime falls: dim green glow", 0.8, 0.0, -1.0, 0.1, 1.0, 0.0, ("SFALL*",)),
    ("water: no glow, glossy mirror", 0.0, 0.0, 0.6, 0.15, 0.06, 1.0, ("FWATER*", "SWATER*")),
)  # fmt: skip
DEFAULT_ROUGHNESS, DEFAULT_SPECULAR = 1.0, 0.0  # the walls' matte look (the material parameters' defaults)


def glow_class(key: str) -> tuple[str, float, float, float, float] | None:
    """The glow category of a texture or flat, or None for an ordinary surface."""
    for name, strength, chroma, threshold, band, patterns in GLOW_CLASSES:
        if any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns):
            return name, strength, chroma, threshold, band
    return None


def surface_class(key: str) -> tuple[float, float, float, float, float, float] | None:
    """(glow strength, chroma weight, threshold, band, roughness, specular) of a glowing or glossy surface."""
    if GLOW_MIX <= 0:  # DOOM_GLOW=0: no glow, no gloss, no panel lights
        return None
    glow = glow_class(key)
    if glow is not None:
        return glow[1], glow[2], glow[3], glow[4], DEFAULT_ROUGHNESS, DEFAULT_SPECULAR
    for _, strength, chroma, threshold, band, roughness, specular, patterns in LIQUIDS:
        if any(fnmatch.fnmatchcase(key, pattern) for pattern in patterns):
            return strength, chroma, threshold, band, roughness, specular
    return None


def tune_surface(material: Any, sprite: bool, key: str = "") -> None:
    """Emission of a lit world or sprite material instance: how much of the map's own light survives."""
    gain = world_gain()
    if sprite:
        material.set_scalar_parameter_value("DoomEmissive", SPRITE_EMISSIVE * gain)
        return
    material.set_scalar_parameter_value("DoomEmissiveMin", EMISSIVE_MIN * gain)
    material.set_scalar_parameter_value("DoomEmissiveScale", EMISSIVE_SCALE * gain)
    spec = surface_class(key)
    if spec is not None:  # the instance keeps these when a switch swaps SW1 <-> SW2 or a liquid animates
        strength, chroma, threshold, band, roughness, specular = spec
        material.set_scalar_parameter_value("DoomGlow", strength * GLOW_MIX * gain)
        material.set_scalar_parameter_value("DoomGlowChroma", chroma)
        material.set_scalar_parameter_value("DoomGlowThreshold", threshold)
        material.set_scalar_parameter_value("DoomGlowBand", band)
        material.set_scalar_parameter_value("DoomRoughness", roughness)
        material.set_scalar_parameter_value("DoomSpecular", specular)


def tune_sprite(material: Any, key: str) -> None:
    """Fullbright sprites emit their whole texture, the rest only the modest default."""
    base = 1.0 if key[:4] in FULLBRIGHT else SPRITE_EMISSIVE
    material.set_scalar_parameter_value("DoomEmissive", base * world_gain())


# Test sliders of the pause menu: (menu label, key, values, index of the neutral value). Neutral = the look
# the constants above give; the choice is kept for the whole session (levels, lit/classic switches).
BRIGHTNESS_STEPS = (0.25, 0.35, 0.5, 0.7, 1.0, 1.35, 1.75, 2.2, 2.6, 3.0)
EXPOSURE_STEPS = (-2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0)  # EV
SLIDERS = (
    ("WORLD BRIGHTNESS", "world", BRIGHTNESS_STEPS, 4),
    ("LIGHT INTENSITY", "lights", BRIGHTNESS_STEPS, 4),
    ("EXPOSURE", "exposure", EXPOSURE_STEPS, 4),
)
RESET_ROW = "RESET LIGHTING"
_levels: dict[str, int] = {key: neutral for _, key, _, neutral in SLIDERS}


def slider_rows() -> list[str]:
    """Menu rows of the sliders: only while the lit mode is on."""
    return [*(label for label, *_ in SLIDERS), RESET_ROW] if active() else []


def slider_key(label: str) -> str | None:
    return next((key for name, key, _, _ in SLIDERS if name == label), None)


def slider_value(key: str) -> float:
    return next(steps[_levels[key]] for _, k, steps, _ in SLIDERS if k == key)


def slider_position(key: str) -> tuple[int, int]:
    """(current step, number of steps) of a slider, for drawing."""
    return next((_levels[key], len(steps)) for _, k, steps, _ in SLIDERS if k == key)


def slider_text(key: str) -> str:
    value = slider_value(key)
    return f"{value:+.1f} EV" if key == "exposure" else f"x{value:.2f}"


def world_gain() -> float:
    return slider_value("world")


def light_gain() -> float:
    return slider_value("lights")


def apply_world(mode: Any) -> None:
    """Re-scale the emission of every lit world and sprite material instance (no rebuild)."""
    for cache_key, material in mode.materials.items():
        if len(cache_key) == 4 and not cache_key[3]:
            tune_sprite(material, cache_key[0])
        elif len(cache_key) == 5 and not cache_key[4]:
            tune_surface(material, cache_key[1], cache_key[0])
    apply_lights()  # the panel lights scale with it


def apply_lights() -> None:
    """Re-apply the light gain to every light and the sun."""
    for entry in [*_rig.lights.values(), *_rig.pool, *_rig.sector_lights]:
        if entry["actor"].is_valid():
            entry["comp"].set_intensity(entry["units"] * UNIT * entry_gain(entry))
    if _rig.sun is not None and _rig.sun.is_valid():
        _rig.sun.directional_light_component.set_intensity(SUN_LUX * light_gain())


def apply_exposure() -> None:
    """Exposure compensation (EV) through an unbound post process volume spawned with the lit rig.

    Doom runs with eye adaptation off (`r.EyeAdaptationQuality 0`), which ignores the bias: the lit rig
    turns it on but pins the brightness range to 1, so the exposure stays fixed plus the chosen bias.
    """
    volume = _rig.exposure
    if volume is None or not volume.is_valid():
        return
    settings = volume.settings
    for name in ("min", "max"):
        setattr(settings, f"override_auto_exposure_{name}_brightness", True)
        setattr(settings, f"auto_exposure_{name}_brightness", 1.0)
    settings.override_auto_exposure_bias = True
    settings.auto_exposure_bias = slider_value("exposure")
    volume.settings = settings


def apply_slider(mode: Any, key: str) -> None:
    if key == "world":
        apply_world(mode)
    elif key == "lights":
        apply_lights()
    else:
        apply_exposure()


def adjust(mode: Any, key: str, delta: int) -> None:
    """Move a slider by `delta` steps (clamped) and apply it live."""
    count = slider_position(key)[1]
    _levels[key] = max(0, min(count - 1, _levels[key] + delta))
    apply_slider(mode, key)


def reset(mode: Any, key: str | None = None) -> None:
    """Back to neutral: one slider, or all of them."""
    for _, name, _, neutral in SLIDERS:
        if key in (None, name):
            _levels[name] = neutral
            apply_slider(mode, name)


# Light intensities below are in "units": one unit is UNIT candelas, so the whole rig scales together.
UNIT = float(os.environ.get("DOOM_LIGHT_UNIT", "4"))
SUN_LUX = float(os.environ.get("DOOM_SUN_LUX", "3"))
SKY_INTENSITY = float(os.environ.get("DOOM_SKY_INTENSITY", "1"))
INDIRECT = float(os.environ.get("DOOM_INDIRECT", "3"))  # how much more than physical the lights bounce
SECTOR_PEAK = 6.0  # units of a flickering light sector at light level 255
MAX_SECTOR_LIGHTS = 24
DISTANCE = 4500.0  # lights further than this from the player (cm) are switched off
SWEEP = 0.25  # seconds between visibility sweeps

Color = tuple[float, float, float]
WHITE: Color = (1.0, 1.0, 1.0)
# thing type -> (colour, intensity in units, attenuation radius in cm, flicker 0..1)
THING_LIGHTS: dict[int, tuple[Color, float, float, float]] = {
    2028: ((1.0, 0.93, 0.78), 6.0, 900.0, 0.0),  # floor lamp
    34: ((1.0, 0.72, 0.38), 1.0, 300.0, 0.5),  # candle
    35: ((1.0, 0.72, 0.38), 2.5, 500.0, 0.4),  # candelabra
    44: ((0.35, 0.5, 1.0), 4.0, 750.0, 0.3),  # tall blue torch
    45: ((0.3, 1.0, 0.35), 4.0, 750.0, 0.3),  # tall green torch
    46: ((1.0, 0.3, 0.2), 4.0, 750.0, 0.3),  # tall red torch
    55: ((0.35, 0.5, 1.0), 3.0, 600.0, 0.3),  # short blue torch
    56: ((0.3, 1.0, 0.35), 3.0, 600.0, 0.3),  # short green torch
    57: ((1.0, 0.3, 0.2), 3.0, 600.0, 0.3),  # short red torch
    70: ((1.0, 0.55, 0.2), 5.0, 800.0, 0.5),  # burning barrel
    42: ((1.0, 0.5, 0.2), 2.5, 450.0, 0.5),  # floating skulls
    41: ((0.3, 1.0, 0.8), 1.5, 350.0, 0.2),  # evil eye
    2013: ((0.3, 0.5, 1.0), 1.5, 300.0, 0.2),  # soulsphere
    2022: ((0.4, 1.0, 0.4), 1.5, 300.0, 0.2),  # invulnerability
    2025: ((0.4, 1.0, 0.4), 0.8, 250.0, 0.0),  # radiation suit
    2045: ((0.8, 0.8, 1.0), 0.8, 250.0, 0.0),  # light amplification visor
    5: ((0.3, 0.4, 1.0), 0.8, 250.0, 0.0),  # blue keycard
    6: ((1.0, 0.9, 0.3), 0.8, 250.0, 0.0),  # yellow keycard
    13: ((1.0, 0.3, 0.2), 0.8, 250.0, 0.0),  # red keycard
    38: ((1.0, 0.3, 0.2), 0.8, 250.0, 0.0),  # skull keys
    39: ((1.0, 0.9, 0.3), 0.8, 250.0, 0.0),
    40: ((0.3, 0.4, 1.0), 0.8, 250.0, 0.0),
    3006: ((1.0, 0.55, 0.2), 1.5, 350.0, 0.5),  # lost soul
}
BARREL: tuple[Color, float, float, float] = (
    (0.25, 1.0, 0.3),
    0.9,
    260.0,
    0.15,
)  # explosive barrel: dim green
# projectile sprite prefix -> (colour, intensity, radius); explosions get brighter and fade out
PROJECTILE_LIGHTS: dict[str, tuple[Color, float, float]] = {
    "BAL1": ((1.0, 0.5, 0.15), 4.0, 600.0),  # imp fireball
    "BAL2": ((0.5, 0.5, 1.0), 4.0, 600.0),  # cacodemon ball
    "BAL7": ((0.3, 1.0, 0.3), 5.0, 650.0),  # baron fireball
    "MISL": ((1.0, 0.65, 0.25), 6.0, 700.0),  # rocket
    "PLSS": ((0.3, 0.5, 1.0), 4.0, 550.0),  # plasma
    "PLSE": ((0.3, 0.5, 1.0), 6.0, 700.0),
    "BFS1": ((0.3, 1.0, 0.3), 8.0, 900.0),  # BFG ball
    "BFE1": ((0.4, 1.0, 0.4), 12.0, 1100.0),
    "BFE2": ((0.4, 1.0, 0.4), 12.0, 1100.0),
}
EXPLOSION_PREFIXES = ("PLSE", "BFE1", "BFE2")
MUZZLE: dict[str, tuple[Color, float, float, float]] = {  # weapon -> colour, units, radius, seconds
    "pistol": ((1.0, 0.8, 0.5), 5.0, 650.0, 0.08),
    "shotgun": ((1.0, 0.75, 0.45), 8.0, 800.0, 0.1),
    "chaingun": ((1.0, 0.8, 0.5), 5.0, 650.0, 0.07),
    "rocket": ((1.0, 0.6, 0.25), 6.0, 700.0, 0.12),
    "plasma": ((0.3, 0.5, 1.0), 5.0, 650.0, 0.08),
    "bfg": ((0.3, 1.0, 0.3), 9.0, 900.0, 0.25),
}
SECTOR_FLICKER = (1, 2, 3, 8, 12, 13, 17)  # sector specials that blink or flicker the light
Entry = dict[str, Any]


def hash_noise(seed: float) -> float:
    return abs(math.sin(seed * 12.9898) * 43758.5453) % 1.0


class Rig:
    """Everything this mode spawns: the sun, the sky light, and the registry of local lights."""

    def __init__(self) -> None:
        self.sun: Any = None
        self.sky: Any = None
        self.exposure: Any = None  # unbound post process volume carrying the exposure bias
        self.lights: dict[int, Entry] = {}  # id(owner) -> light that follows (or sits at) a thing
        self.seen: set[int] = set()
        self.pool: list[Entry] = []  # short-lived flashes
        self.level: Any = None
        self.sector_lights: list[Entry] = []
        self.sweep = 0.0
        self.clock = 0.0
        self.frame = 0
        self.recapture: tuple[int, ...] = ()


_rig = Rig()


def _common() -> Any:
    from doom import common  # late: common imports this module

    return common


def shifted(location: Any, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> Any:
    return ue.Vector(float(location[0]) + dx, float(location[1]) + dy, float(location[2]) + dz)


def make_light(location: Any, color: Color, units: float, radius: float) -> Entry:
    actor = ue.spawn_actor(ue.PointLight, location=location)
    comp = actor.point_light_component
    comp.set_mobility(ue.EComponentMobility.Movable)
    comp.set_intensity_units(ue.ELightUnits.Candelas)
    comp.set_attenuation_radius(radius)
    comp.set_light_color(ue.LinearColor(color[0], color[1], color[2], 1.0), True)
    comp.set_source_radius(8.0)
    comp.set_cast_shadows(True)
    comp.set_indirect_lighting_intensity(INDIRECT)
    comp.set_intensity(units * UNIT * light_gain())
    return dict(actor=actor, comp=comp, units=units, base=units, flicker=0.0, on=True)


def entry_gain(entry: Entry) -> float:
    """Panel lights follow WORLD BRIGHTNESS like the glow they back up, the other lights LIGHT INTENSITY."""
    return world_gain() if entry.get("glow") else light_gain()


def set_units(entry: Entry, units: float) -> None:
    entry["units"] = units
    entry["comp"].set_intensity(units * UNIT * entry_gain(entry))


def rescale(unit: float) -> None:
    """Change UNIT live (calibration sweeps): every light is re-applied."""
    global UNIT
    UNIT = unit
    for entry in [*_rig.lights.values(), *_rig.pool, *_rig.sector_lights]:
        if entry["actor"].is_valid():
            entry["comp"].set_intensity(entry["units"] * UNIT * entry_gain(entry))


def apply_cvars(on: bool) -> None:
    """Lumen on (the startup values) or off (method 0: unlit mode does not pay for Lumen)."""
    if not supported():
        return
    for name in RUNTIME_METHOD_CVARS:
        value = _startup.get(name, 1) if on else 0
        ue.KismetSystemLibrary.execute_console_command(f"{name} {value}")
    if on:
        for command in RUNTIME_CVARS:
            ue.KismetSystemLibrary.execute_console_command(command)


def start(mode: Any) -> None:
    """Level start on this machine: screen settings, then Lumen tuning (lit) or off (classic look).

    Local and cosmetic, so every machine that shows the level runs it once: the game mode on the server
    (or the standalone game), the replicated game state on a client. Never both on one machine.
    """
    del mode
    for command in DISPLAY_CVARS:
        ue.KismetSystemLibrary.execute_console_command(command)
    apply_cvars(active())
    _rig.__init__()  # new game mode: drop references to the previous world's actors


def teardown() -> None:
    """Destroy every light this mode spawned (the classic look has none)."""
    for entry in [*_rig.lights.values(), *_rig.pool, *_rig.sector_lights]:
        if entry["actor"].is_valid():
            entry["actor"].destroy_actor()
    if _rig.exposure is not None:
        ue.KismetSystemLibrary.execute_console_command("r.EyeAdaptationQuality 0")  # Doom's fixed exposure
    for actor in (_rig.sun, _rig.sky, _rig.exposure):
        if actor is not None and actor.is_valid():
            actor.destroy_actor()
    _rig.__init__()


def swap_materials(mode: Any) -> None:
    """Re-create every world and sprite material for the current mode and put it on whatever shows it.

    Same creation paths as a level build (`mode.material`, `common.sprite_material`), so the per-section
    parameters (texture, masked, sector) and the fuzz/sky special cases are kept; sections already carry
    normals when the machine supports the lit mode.
    """
    common = _common()
    old = mode.materials
    current = {}
    for cache_key, material in old.items():
        try:
            current[cache_key] = (material, material.get_texture_parameter_value("DoomTexture"))
        except (AttributeError, RuntimeError):
            current[cache_key] = (material, None)
    mode.materials = {}
    mode.animated_materials = []
    swapped: dict[int, Any] = {}  # id(old instance) -> new instance
    by_name: dict[str, Any] = {}
    for cache_key, (material, texture) in current.items():
        if len(cache_key) == 2 or (len(cache_key) == 5 and cache_key[4]):
            mode.materials[cache_key] = material  # fuzz and sky: the same material in both modes
            continue
        if len(cache_key) == 4:
            if cache_key[3]:
                mode.materials[cache_key] = material
                continue
            new = common.sprite_material(mode, cache_key[0], cache_key[2], False)
        else:
            new = mode.material(cache_key[0], cache_key[1], cache_key[2], cache_key[3], False)
        if texture is not None:
            new.set_texture_parameter_value("DoomTexture", texture)
        swapped[id(material)] = new
        by_name[material.get_name()] = new
    for face in getattr(mode, "wall_faces", []):
        face["material"] = swapped.get(id(face["material"]), face["material"])
    mode.scroll_materials = {k: (swapped.get(id(m), m), w) for k, (m, w) in mode.scroll_materials.items()}
    mode.button_materials = {
        k: [(swapped.get(id(m), m), t) for m, t in v] for k, v in mode.button_materials.items()
    }
    for actor in mode.geometry:
        if not actor.is_valid():
            continue
        mesh = actor.mesh
        for index in range(mesh.get_num_materials()):
            material = mesh.get_material(index)
            if material is not None and material.get_name() in by_name:
                mesh.set_material(index, by_name[material.get_name()])
    for obj in mode.things():
        billboard = getattr(obj, "billboard", None)
        if billboard is None or not obj.is_valid():
            continue
        elements = []
        for element in billboard.elements:
            material = element.material
            if material is not None and material.get_name() in by_name:
                element = ue.MaterialSpriteElement(
                    material=by_name[material.get_name()],
                    size_is_in_screen_space=element.size_is_in_screen_space,
                    base_size_x=element.base_size_x,
                    base_size_y=element.base_size_y,
                )
            elements.append(element)
        billboard.set_elements(elements)
    mode.animation_frame = -1  # animated textures re-apply on the next tick


def set_enabled(mode: Any, on: bool) -> bool:
    """Switch the lit mode on or off in the running level; False when the machine cannot do it."""
    if on and not supported():
        ue.log("Doom: lit mode needs " + "; ".join(missing_settings()), "warning")
        return False
    if active() == on:
        return True
    _lit[0] = on
    apply_cvars(on)
    teardown()  # lights, sun and sky light go; the lit mode's tick rebuilds them for the level
    swap_materials(mode)
    return True


def toggle(mode: Any) -> bool:
    return set_enabled(mode, not active())


def build_level(mode: Any) -> None:
    """Sun, sky light and the flickering sector lights for the loaded map (called on a map change)."""
    common = _common()
    for entry in [*_rig.lights.values(), *_rig.pool, *_rig.sector_lights]:
        if entry["actor"].is_valid():
            entry["actor"].destroy_actor()
    _rig.lights, _rig.seen, _rig.pool, _rig.sector_lights = {}, set(), [], []
    _rig.level = mode.data
    if _rig.sun is None or not _rig.sun.is_valid():
        _rig.sun = ue.spawn_actor(ue.DirectionalLight, location=ue.Vector(0, 0, 4000))
        comp = _rig.sun.directional_light_component
        comp.set_mobility(ue.EComponentMobility.Movable)
        comp.set_intensity(SUN_LUX * light_gain())
        comp.set_light_color(ue.LinearColor(0.75, 0.82, 1.0, 1.0), True)
        comp.set_cast_shadows(True)
        comp.set_indirect_lighting_intensity(INDIRECT)
        _rig.sun.set_actor_rotation(ue.Rotator(-48, 35, 0), False)
    if _rig.exposure is None or not _rig.exposure.is_valid():
        _rig.exposure = ue.spawn_actor(ue.PostProcessVolume, location=ue.Vector(0, 0, 0))
        _rig.exposure.unbound = True
        apply_exposure()
        ue.KismetSystemLibrary.execute_console_command("r.EyeAdaptationQuality 2")
    if _rig.sky is None or not _rig.sky.is_valid():
        _rig.sky = ue.spawn_actor(ue.SkyLight, location=ue.Vector(0, 0, 4000))
        comp = _rig.sky.light_component
        comp.set_mobility(ue.EComponentMobility.Movable)
        comp.set_real_time_capture(False)  # real-time capture wants an atmosphere or a tagged sky mesh
        comp.sky_distance_threshold = 15000.0  # the sky sphere (24000 cm away) is what it captures
        comp.set_intensity(SKY_INTENSITY)
        _rig.recapture = (30, 150)
    # Flickering light sectors drive a point light under their ceiling.
    sectors = mode.data["sectors"]
    area: dict[int, float] = {}
    centre: dict[int, list[float]] = {}
    for polygon in mode.data["polygons"]:
        index, points = polygon["sector"], polygon["points"]
        if sectors[index]["special"] not in SECTOR_FLICKER:
            continue
        count = len(points)
        twice = sum(
            points[i][0] * points[(i + 1) % count][1] - points[(i + 1) % count][0] * points[i][1]
            for i in range(count)
        )
        weight = abs(twice) / 2
        acc = centre.setdefault(index, [0.0, 0.0])
        acc[0] += weight * sum(p[0] for p in points) / count
        acc[1] += weight * sum(p[1] for p in points) / count
        area[index] = area.get(index, 0.0) + weight
    for index in sorted(area, key=lambda s: -area[s])[:MAX_SECTOR_LIGHTS]:
        sector = sectors[index]
        x, y = centre[index][0] / area[index], centre[index][1] / area[index]
        z = sector["floor"] + 96 if sector["ceiling_tex"] == "F_SKY1" else sector["ceiling"] - 12
        radius = max(500.0, min(1500.0, math.sqrt(area[index]) * common.SCALE * 1.4))
        entry = make_light(common.vec(x, y, z), (1.0, 0.95, 0.85), 0.0, radius)
        entry.update(special=sector["special"], seed=index * 1.37, peak=SECTOR_PEAK * sector["light"] / 255)
        _rig.sector_lights.append(entry)
    _rig.sector_lights.extend(panel_lights(mode))


MAX_PANEL_LIGHTS = 48
PANEL_SPACING = 160.0  # map units: at most one light per panel texture within this distance
_panel_colours: dict[str, Color | None] = {}


def panel_colour(key: str) -> Color | None:
    """Mean colour of the glowing pixels of a texture (its brightest channel scaled to 1), cached per texture.

    The same score and smoothstep as the material (`importer.glow_emission`), weighted by the mask, so a
    red switch lamp gives red, a green monitor green and a white lamp strip white.
    """
    if key not in _panel_colours:
        _panel_colours[key] = None
        spec = glow_class(key)
        path = ASSETS / "textures" / f"{key}.png"
        if spec is not None and path.is_file():
            _, _, chroma, threshold, band = spec
            width, _, rows = wad.png_rows(path)
            total, weight = [0.0, 0.0, 0.0], 0.0
            for line in rows:
                for x in range(width):
                    if line[x * 4 + 3] < 128:
                        continue
                    rgb = [line[x * 4 + c] / 255 for c in range(3)]
                    high = max(rgb)
                    t = min(1.0, max(0.0, (high + chroma * (high - min(rgb)) - threshold) / band))
                    t = t * t * (3 - 2 * t)
                    weight += t
                    for c in range(3):
                        total[c] += rgb[c] * t
            if weight > 0 and max(total) > 0:
                peak = max(total)
                _panel_colours[key] = (total[0] / peak, total[1] / peak, total[2] / peak)
    return _panel_colours[key]


def panel_lights(mode: Any) -> list[Entry]:
    """A small coloured light in front of each switch and big screen wall (the emissive bounce is faint)."""
    if GLOW_MIX <= 0:
        return []
    common = _common()
    data = mode.data
    found: list[tuple[float, float, float, float, Color, float, float]] = []
    for line in data["lines"]:
        a, b = data["vertices"][line["a"]], data["vertices"][line["b"]]
        length = math.dist(a, b)
        for name in ("right", "left"):
            if line[name] == 65535:
                continue
            side = data["sides"][line[name]]
            for key in (side["middle"], side["upper"], side["lower"]):
                spec = glow_class(key)
                if spec is None or spec[0][:6] not in ("switch", "screen"):
                    continue
                colour = panel_colour(key)
                if colour is None or (spec[0][:6] == "screen" and length < 96):
                    continue
                sign = 1.0 if name == "right" else -1.0
                nx, ny = sign * (b[1] - a[1]) / length, -sign * (b[0] - a[0]) / length
                sector = data["sectors"][side["sector"]]
                units = 0.7 if spec[0][:6] == "switch" else 1.2 + 1.8 * min(length, 512.0) / 512.0
                x, y = (a[0] + b[0]) / 2 + nx * 40, (a[1] + b[1]) / 2 + ny * 40
                found.append(
                    (units, x, y, sector["floor"] + 56.0, colour, 300.0 if units == 0.7 else 450.0, 0.0)
                )
    found.sort(key=lambda f: -f[0])
    chosen: list[tuple[float, float, float, float, Color, float, float]] = []
    for item in found:
        if len(chosen) >= MAX_PANEL_LIGHTS:
            break
        if all(math.dist(item[1:3], other[1:3]) > PANEL_SPACING for other in chosen):
            chosen.append(item)
    entries = []
    for units, x, y, z, colour, radius, _ in chosen:
        entry = make_light(common.vec(x, y, z), colour, units, radius)
        entry.update(static=True, glow=True)
        set_units(entry, units)
        entries.append(entry)
    return entries


def sector_factor(special: int, t: float, seed: float) -> float:
    """Brightness 0..1 of a Doom light special at time t (an approximation of the original timings)."""
    if special == 1:  # random flicker
        return 1.0 if hash_noise(math.floor(t * 12) + seed) > 0.35 else 0.15
    if special in (2, 12):  # blink every half second
        return 0.12 if (t + seed) % 0.5 < 0.12 else 1.0
    if special in (3, 13):  # blink every second
        return 0.12 if (t + seed) % 1.0 < 0.12 else 1.0
    if special == 8:  # glow
        return 0.55 + 0.45 * math.sin((t + seed) * math.tau / 2.4)
    return 0.55 + 0.45 * hash_noise(math.floor(t * 10) + seed)  # 17: fire flicker


def thing_spec(obj: Any) -> tuple[Color, float, float, float] | None:
    name = type(obj).__name__
    if name == "DoomBarrel":
        return BARREL
    kind = getattr(obj, "kind", 0)
    if name == "DoomSprite" and kind in THING_LIGHTS:
        return THING_LIGHTS[kind]
    if name == "DoomDemon" and getattr(obj, "type_id", 0) == 3006:
        return THING_LIGHTS[3006]
    return None


def acquire() -> Entry:
    for entry in _rig.pool:
        if not entry["busy"]:
            return entry
    entry = make_light(ue.Vector(0, 0, -100000), WHITE, 0.0, 600.0)
    entry["busy"] = False
    _rig.pool.append(entry)
    return entry


def flash(location: Any, color: Color, units: float, radius: float, seconds: float) -> None:
    """A short-lived light that fades out: muzzle flashes."""
    entry = acquire()
    entry.update(busy=True, ttl=seconds, life=seconds, peak=units)
    entry["comp"].set_light_color(ue.LinearColor(color[0], color[1], color[2], 1.0), True)
    entry["comp"].set_attenuation_radius(radius)
    entry["actor"].set_actor_location(location, False, True)
    entry["actor"].set_actor_hidden_in_game(False)
    set_units(entry, units)


def muzzle(mode: Any, weapon: str, start: Any, direction: Any) -> None:
    """The player fires: a light just in front of the muzzle."""
    del mode
    spec = MUZZLE.get(weapon)
    if spec is not None:
        flash(shifted(start, *(float(c) * 70 for c in direction)), *spec)


def tick(mode: Any, dt: float) -> None:
    rig = _rig
    if rig.level is not mode.data:
        build_level(mode)
    rig.clock += dt
    rig.frame += 1
    if rig.frame in rig.recapture and rig.sky is not None and rig.sky.is_valid():
        rig.sky.light_component.recapture_sky()  # the dome's shader may not be ready the first time
    player = _common().player_now()
    eye = tuple(float(c) for c in player.get_actor_location()) if player is not None else None
    # Give new things (items, barrels, projectiles) a light.
    for obj in mode.things():
        ident = id(obj)
        if ident in rig.lights:
            continue
        name = type(obj).__name__
        if name == "DoomProjectile":
            spec = PROJECTILE_LIGHTS.get(getattr(obj, "key", "")[:4])
            if spec is not None and obj.is_valid():
                entry = make_light(obj.get_actor_location(), spec[0], spec[1], spec[2])
                entry.update(owner=obj, kind="projectile", spec=spec, offset=0.0)
                rig.lights[ident] = entry
            continue
        if ident in rig.seen:
            continue
        rig.seen.add(ident)
        spec4 = thing_spec(obj)
        if spec4 is not None and obj.is_valid():
            color, units, radius, flicker = spec4
            scale = _common().SCALE
            offset = (24 if name == "DoomBarrel" else 30) * scale
            entry = make_light(shifted(obj.get_actor_location(), dz=offset), color, units, radius)
            entry.update(
                owner=obj, kind=name, flicker=flicker, offset=offset, seed=hash_noise(ident % 9973) * 100
            )
            rig.lights[ident] = entry
    # Update the lights that follow things.
    dead = []
    for ident, entry in rig.lights.items():
        owner = entry["owner"]
        if not owner.is_valid() or not entry["actor"].is_valid():
            dead.append(ident)
            continue
        kind = entry["kind"]
        if kind == "projectile":
            key = getattr(owner, "key", "")
            spec = PROJECTILE_LIGHTS.get(key[:4], entry["spec"])
            units = spec[1]
            if getattr(owner, "stage", "") == "explosion" or key[:4] in EXPLOSION_PREFIXES:
                units = 2.5 * spec[1] * max(0.0, 1.0 - float(getattr(owner, "age", 0.0)) / 0.45)
                entry["comp"].set_attenuation_radius(spec[2] * 1.5)
            entry["comp"].set_light_color(ue.LinearColor(spec[0][0], spec[0][1], spec[0][2], 1.0), True)
            entry["actor"].set_actor_location(owner.get_actor_location(), False, True)
            set_units(entry, units)
        elif kind == "DoomBarrel" and owner.exploded:
            fade = max(0.0, 1.0 - float(getattr(owner, "clock", 0.0)) / 0.9)
            entry["comp"].set_light_color(ue.LinearColor(1.0, 0.6, 0.25, 1.0), True)
            entry["comp"].set_attenuation_radius(1100.0)
            set_units(entry, 14.0 * fade)
        elif getattr(owner, "taken", False):
            dead.append(ident)
        else:
            if kind == "DoomDemon":
                entry["actor"].set_actor_location(
                    shifted(owner.get_actor_location(), dz=entry["offset"]), False, True
                )
            if entry["flicker"] and rig.frame % 3 == 0:
                wobble = 1.0 - entry["flicker"] * hash_noise(math.floor(rig.clock * 14) + entry["seed"])
                set_units(entry, entry["base"] * wobble)
    for ident in dead:
        entry = rig.lights.pop(ident)
        if entry["actor"].is_valid():
            entry["actor"].destroy_actor()
    for entry in rig.pool:
        if entry["busy"]:
            entry["ttl"] -= dt
            if entry["ttl"] <= 0:
                entry["busy"] = False
                set_units(entry, 0.0)
                entry["actor"].set_actor_hidden_in_game(True)
            else:
                set_units(entry, entry["peak"] * entry["ttl"] / entry["life"])
    if rig.frame % 2 == 0:
        for entry in rig.sector_lights:
            if entry.get("static"):
                continue
            set_units(entry, entry["peak"] * sector_factor(entry["special"], rig.clock, entry["seed"]))
    # Switch off lights far from the player.
    rig.sweep -= dt
    if rig.sweep <= 0 and eye is not None:
        rig.sweep = SWEEP
        for entry in [*rig.lights.values(), *rig.sector_lights]:
            if not entry["actor"].is_valid():
                continue
            spot = entry["actor"].get_actor_location()
            far = math.dist((float(spot[0]), float(spot[1]), float(spot[2])), eye) > DISTANCE
            if far == entry["on"]:
                entry["on"] = not far
                entry["actor"].set_actor_hidden_in_game(far)

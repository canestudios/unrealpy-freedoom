"""Import locally owned Doom data using UnrealPy only. Run in editor mode."""

import math
import subprocess
import wave
from array import array
from pathlib import Path
from typing import Any, cast

import ue
from doom import lighting
from doom.dataset import ASSETS, CONTENT, find_fluidsynth, find_soundfont
from doom.wad import extract


def material(tools: ue.AssetTools, masked: bool, world_masked: bool = False) -> None:
    path = (
        CONTENT + "/M_MaskedWorld"
        if world_masked
        else CONTENT + "/M_Sprite"
        if masked
        else CONTENT + "/M_World"
    )
    mat = ue.load_object(path)
    if mat is None:
        mat = tools.create_asset(
            path.rsplit("/", 1)[1],
            CONTENT,
            ue.Material,
            ue.new_object(ue.MaterialFactoryNew),
        )
    assert isinstance(mat, ue.Material)
    mat.two_sided = not world_masked
    mat.blend_mode = ue.EBlendMode.BLEND_Masked if masked or world_masked else ue.EBlendMode.BLEND_Opaque
    mat.shading_model = ue.EMaterialShadingModel.MSM_Unlit
    edit = ue.MaterialEditingLibrary
    edit.delete_all_material_expressions(mat)
    tex = edit.create_material_expression(mat, ue.MaterialExpressionTextureSampleParameter2D, -500, 0)
    assert isinstance(tex, ue.MaterialExpressionTextureSampleParameter2D)
    tex.parameter_name = "DoomTexture"
    tex.texture = cast(ue.Texture, ue.load_object(CONTENT + "/textures/STARTAN3"))
    if not masked:
        coordinates = edit.create_material_expression(mat, ue.MaterialExpressionTextureCoordinate, -800, 200)
        scroll_x = edit.create_material_expression(mat, ue.MaterialExpressionScalarParameter, -800, 400)
        assert isinstance(scroll_x, ue.MaterialExpressionScalarParameter)
        scroll_x.parameter_name = "DoomScrollX"
        scroll_x.default_value = 0.0
        scroll_y = edit.create_material_expression(mat, ue.MaterialExpressionConstant, -800, 600)
        assert isinstance(scroll_y, ue.MaterialExpressionConstant)
        scroll_y.r = 0.0
        offset = edit.create_material_expression(mat, ue.MaterialExpressionAppendVector, -500, 400)
        assert edit.connect_material_expressions(scroll_x, "", offset, "A")
        assert edit.connect_material_expressions(scroll_y, "", offset, "B")
        uv = edit.create_material_expression(mat, ue.MaterialExpressionAdd, -250, 200)
        assert edit.connect_material_expressions(coordinates, "", uv, "A")
        assert edit.connect_material_expressions(offset, "", uv, "B")
        assert edit.connect_material_expressions(uv, "", tex, "")
    assert edit.connect_material_property(tex, "RGB", ue.EMaterialProperty.MP_EmissiveColor)
    if masked or world_masked:
        assert edit.connect_material_property(tex, "A", ue.EMaterialProperty.MP_OpacityMask)
    edit.recompile_material(mat)
    assert ue.EditorAssetLibrary.save_loaded_asset(mat, False)


def sprite_uv(mat: ue.Material) -> tuple[Any, Any]:
    """Texture coordinates remapped by DoomUScale/DoomUOffset on U, plus a 0/1 "inside the sprite" mask.

    A camera-facing billboard is centred on its origin, so the sprite pivot is expressed by drawing the
    patch inside a wider (or mirrored) quad; texels outside U 0..1 are masked out.
    """
    edit = ue.MaterialEditingLibrary

    def node(kind: Any, x: int, y: int) -> Any:
        return edit.create_material_expression(mat, kind, x, y)

    def constant(value: float, x: int, y: int) -> Any:
        c = node(ue.MaterialExpressionConstant, x, y)
        c.r = value
        return c

    def link(a: Any, b: Any, name: str = "") -> None:
        assert edit.connect_material_expressions(a, "", b, name)

    scale = node(ue.MaterialExpressionScalarParameter, -1500, 400)
    scale.parameter_name = "DoomUScale"
    scale.default_value = 1.0
    offset = node(ue.MaterialExpressionScalarParameter, -1500, 600)
    offset.parameter_name = "DoomUOffset"
    offset.default_value = 0.0
    scale_xy = node(ue.MaterialExpressionAppendVector, -1300, 400)
    link(scale, scale_xy, "A")
    link(constant(1.0, -1500, 500), scale_xy, "B")
    offset_xy = node(ue.MaterialExpressionAppendVector, -1300, 600)
    link(offset, offset_xy, "A")
    link(constant(0.0, -1500, 700), offset_xy, "B")
    scaled = node(ue.MaterialExpressionMultiply, -1100, 300)
    link(node(ue.MaterialExpressionTextureCoordinate, -1300, 200), scaled, "A")
    link(scale_xy, scaled, "B")
    uv = node(ue.MaterialExpressionAdd, -900, 300)
    link(scaled, uv, "A")
    link(offset_xy, uv, "B")
    u = node(ue.MaterialExpressionComponentMask, -700, 800)
    u.r, u.g, u.b, u.a = True, False, False, False
    link(uv, u)
    centred = node(ue.MaterialExpressionSubtract, -500, 800)
    link(u, centred, "A")
    link(constant(0.5, -700, 900), centred, "B")
    distance = node(ue.MaterialExpressionAbs, -300, 800)
    link(centred, distance)
    over = node(ue.MaterialExpressionSubtract, -100, 800)
    link(distance, over, "A")
    link(constant(0.5005, -300, 900), over, "B")
    ceil = node(ue.MaterialExpressionCeil, 0, 900)
    link(over, ceil)
    outside = node(ue.MaterialExpressionSaturate, 100, 800)
    link(ceil, outside)
    inside = node(ue.MaterialExpressionOneMinus, 300, 800)
    link(outside, inside)
    return uv, inside


def billboard_material(tools: ue.AssetTools) -> None:
    """Unlit masked sprite for ue.MaterialBillboardComponent (Unreal faces it to the camera)."""
    path = CONTENT + "/M_SpriteBillboard"
    mat = ue.load_object(path)
    if mat is None:
        mat = tools.create_asset(
            "M_SpriteBillboard", CONTENT, ue.Material, ue.new_object(ue.MaterialFactoryNew)
        )
    assert isinstance(mat, ue.Material)
    mat.two_sided = True
    mat.blend_mode = ue.EBlendMode.BLEND_Masked
    mat.shading_model = ue.EMaterialShadingModel.MSM_Unlit
    edit = ue.MaterialEditingLibrary
    edit.delete_all_material_expressions(mat)
    tex = edit.create_material_expression(mat, ue.MaterialExpressionTextureSampleParameter2D, -500, 0)
    assert isinstance(tex, ue.MaterialExpressionTextureSampleParameter2D)
    tex.parameter_name = "DoomTexture"
    tex.texture = cast(ue.Texture, ue.load_object(CONTENT + "/textures/STARTAN3"))
    uv, inside = sprite_uv(mat)
    assert edit.connect_material_expressions(uv, "", tex, "")
    opacity = edit.create_material_expression(mat, ue.MaterialExpressionMultiply, -200, 100)
    assert edit.connect_material_expressions(tex, "A", opacity, "A")
    assert edit.connect_material_expressions(inside, "", opacity, "B")
    assert edit.connect_material_property(tex, "RGB", ue.EMaterialProperty.MP_EmissiveColor)
    assert edit.connect_material_property(opacity, "", ue.EMaterialProperty.MP_OpacityMask)
    edit.recompile_material(mat)
    assert ue.EditorAssetLibrary.save_loaded_asset(mat, False)


SKY_TAN_SCALE = 160.0  # vanilla: texels per unit of tan(elevation) (320-px wide view, 90 degrees)
SKY_HORIZON_ROW = 100.0  # vanilla: the horizon is texture row 100 of 128
SKY_TURNS = 4.0  # the 256-px texture wraps 4 times around 360 degrees (1024 columns)
SKY_HEIGHT = 128.0
SKY_FADE = 0.35  # v units above the top row over which the sky fades to its flat top colour


def sky_material(tools: ue.AssetTools) -> None:
    """`M_Sky`: unlit vanilla sky, UVs from the camera-to-pixel direction (the surface is at "infinity").

    U follows the yaw of the direction (4 wraps per turn, so it scrolls with the view); V is anchored to
    the horizon, linear in tan(elevation) like vanilla's screen rows, and clamped to the texture's first and
    last rows, so looking up never leaves the texture (no black, no seam). Used in the unlit and lit modes
    (a sky light cube capture evaluates `CameraPosition` at the capture point, so it sees the same sky).
    """
    path = CONTENT + "/M_Sky"
    mat = ue.load_object(path)
    if mat is None:
        mat = tools.create_asset("M_Sky", CONTENT, ue.Material, ue.new_object(ue.MaterialFactoryNew))
    assert isinstance(mat, ue.Material)
    edit = ue.MaterialEditingLibrary
    mat.two_sided = True
    mat.blend_mode = ue.EBlendMode.BLEND_Opaque
    mat.shading_model = ue.EMaterialShadingModel.MSM_Unlit
    mat.is_sky = False
    edit.delete_all_material_expressions(mat)

    def node(cls: Any, x: int, y: int) -> Any:
        return edit.create_material_expression(mat, cls, x, y)

    def link(a: Any, b: Any, pin: str = "", out: str = "") -> Any:
        assert edit.connect_material_expressions(a, out, b, pin)
        return b

    def constant(value: float, x: int, y: int) -> Any:
        c = node(ue.MaterialExpressionConstant, x, y)
        c.r = value
        return c

    def mask(source: Any, channel: str, y: int) -> Any:
        m = node(ue.MaterialExpressionComponentMask, -900, y)
        m.r, m.g, m.b, m.a = (channel == "r", channel == "g", channel == "b", False)
        return link(source, m)

    direction = link(
        node(ue.MaterialExpressionWorldPosition, -1400, 0), node(ue.MaterialExpressionSubtract, -1150, 0), "A"
    )
    link(node(ue.MaterialExpressionCameraPositionWS, -1400, 200), direction, "B")
    dx, dy, dz = mask(direction, "r", -200), mask(direction, "g", 0), mask(direction, "b", 200)
    yaw = node(ue.MaterialExpressionArctangent2, -700, -100)
    link(dy, yaw, "Y")
    link(dx, yaw, "X")
    u = node(ue.MaterialExpressionMultiply, -450, -100)
    link(yaw, u, "A")
    link(constant(SKY_TURNS / math.tau, -700, 50), u, "B")
    across = node(ue.MaterialExpressionAppendVector, -900, 400)
    link(dx, across, "A")
    link(dy, across, "B")
    run = node(
        ue.MaterialExpressionAdd, -450, 400
    )  # horizontal distance (+ a hair, so straight up is finite)
    link(link(across, node(ue.MaterialExpressionLength, -700, 400)), run, "A")
    link(constant(0.001, -700, 520), run, "B")
    slope = link(dz, node(ue.MaterialExpressionDivide, -250, 300), "A")
    link(run, slope, "B")
    rows = node(ue.MaterialExpressionMultiply, -50, 300)
    link(slope, rows, "A")
    link(constant(SKY_TAN_SCALE / SKY_HEIGHT, -250, 450), rows, "B")
    v = node(ue.MaterialExpressionSubtract, 150, 300)
    link(constant(SKY_HORIZON_ROW / SKY_HEIGHT, -50, 450), v, "A")
    link(rows, v, "B")
    clamp = node(ue.MaterialExpressionClamp, 350, 300)  # sample inside the first / last texel row
    clamp.min_default = 0.5 / SKY_HEIGHT
    clamp.max_default = 1.0 - 0.5 / SKY_HEIGHT
    link(v, clamp)
    uv = node(ue.MaterialExpressionAppendVector, 550, 100)
    link(u, uv, "A")
    link(clamp, uv, "B")
    tex = node(ue.MaterialExpressionTextureSampleParameter2D, 750, 100)
    tex.parameter_name = "DoomTexture"
    tex.texture = cast(ue.Texture, ue.load_object(CONTENT + "/textures/SKY1"))
    link(uv, tex)
    # Above the texture's top (v < 0) fade to one flat colour over SKY_FADE of v: no edge, no streaks.
    above = node(ue.MaterialExpressionMultiply, 350, 600)
    link(v, above, "A")
    link(constant(-1.0 / SKY_FADE, 150, 700), above, "B")
    fade = link(above, node(ue.MaterialExpressionSaturate, 550, 600))
    top = node(ue.MaterialExpressionVectorParameter, 550, 450)
    top.parameter_name = "SkyTopColor"
    top.default_value = ue.LinearColor(0.5, 0.5, 0.5, 1)
    blend = node(ue.MaterialExpressionLinearInterpolate, 950, 300)
    link(tex, blend, "A", "RGB")
    link(top, blend, "B")
    link(fade, blend, "Alpha")
    assert edit.connect_material_property(blend, "", ue.EMaterialProperty.MP_EmissiveColor)
    edit.recompile_material(mat)
    assert ue.EditorAssetLibrary.save_loaded_asset(mat, False)


def glow_emission(mat: Any, tex: Any, base: Any, scalar: Any) -> Any:
    """`base` plus the glow: texture colour * smoothstep(threshold, threshold + band, score) * DoomGlow.

    The score of a texel is its brightest channel plus `DoomGlowChroma` times its saturation (max - min),
    so the screens, buttons and lamps pass and the grey metal frame around them does not. DoomGlow is 0 on
    ordinary surfaces (see lighting.GLOW_CLASSES for who gets what).
    """
    edit = ue.MaterialEditingLibrary

    def node(cls: Any, x: int, y: int) -> Any:
        return edit.create_material_expression(mat, cls, x, y)

    def link(a: Any, b: Any, pin: str = "", out: str = "") -> None:
        assert edit.connect_material_expressions(a, out, b, pin)

    channels = []
    for index, name in enumerate("rgb"):
        mask = node(ue.MaterialExpressionComponentMask, 0, 1100 + 100 * index)
        for flag in "rgba":
            setattr(mask, flag, flag == name)
        link(tex, mask, "", "RGB")
        channels.append(mask)
    high = node(ue.MaterialExpressionMax, 150, 1100)
    link(channels[0], high, "A")
    link(channels[1], high, "B")
    high2 = node(ue.MaterialExpressionMax, 300, 1100)
    link(high, high2, "A")
    link(channels[2], high2, "B")
    low = node(ue.MaterialExpressionMin, 150, 1300)
    link(channels[0], low, "A")
    link(channels[1], low, "B")
    low2 = node(ue.MaterialExpressionMin, 300, 1300)
    link(low, low2, "A")
    link(channels[2], low2, "B")
    chroma = node(ue.MaterialExpressionSubtract, 450, 1200)
    link(high2, chroma, "A")
    link(low2, chroma, "B")
    weighted = node(ue.MaterialExpressionMultiply, 600, 1200)
    link(chroma, weighted, "A")
    link(scalar("DoomGlowChroma", 0.0, 450, 1350), weighted, "B")
    score = node(ue.MaterialExpressionAdd, 750, 1150)
    link(high2, score, "A")
    link(weighted, score, "B")
    threshold = scalar("DoomGlowThreshold", 0.65, 600, 1450)
    top = node(ue.MaterialExpressionAdd, 800, 1450)
    link(threshold, top, "A")
    link(scalar("DoomGlowBand", 0.15, 600, 1550), top, "B")
    step = node(ue.MaterialExpressionSmoothStep, 950, 1250)
    link(threshold, step, "Min")
    link(top, step, "Max")
    link(score, step, "Value")
    gain = node(ue.MaterialExpressionMultiply, 1100, 1250)
    link(step, gain, "A")
    link(scalar("DoomGlow", 0.0, 950, 1400), gain, "B")
    glow = node(ue.MaterialExpressionMultiply, 1250, 1100)
    link(tex, glow, "A", "RGB")
    link(gain, glow, "B")
    total = node(ue.MaterialExpressionAdd, 1400, 1000)
    link(base, total, "A")
    link(glow, total, "B")
    return total


def lit_material(tools: ue.AssetTools, name: str) -> None:
    """Default-lit variants for the Lumen look (see lighting.py); the unlit ones are untouched.

    Same `DoomTexture` (and scroll / sprite layout) parameters as the unlit materials. The base colour is
    the texture; a modest emission keeps dark sectors readable: world surfaces emit
    `DoomEmissiveMin + DoomEmissiveScale * sector light` of their texture (the sector light is the vertex
    colour the geometry already carries), sprites emit `DoomEmissive` of theirs. World surfaces also have
    the glow of switches, screens and lamps (`glow_emission`).
    """
    kind = {
        "M_WorldLit": "world",
        "M_MaskedWorldLit": "masked",
        "M_SpriteLit": "sprite",
    }.get(name, "billboard")
    path = f"{CONTENT}/{name}"
    mat = ue.load_object(path)
    if mat is None:
        mat = tools.create_asset(name, CONTENT, ue.Material, ue.new_object(ue.MaterialFactoryNew))
    assert isinstance(mat, ue.Material)
    edit = ue.MaterialEditingLibrary
    mat.two_sided = kind != "masked"
    mat.blend_mode = ue.EBlendMode.BLEND_Opaque if kind == "world" else ue.EBlendMode.BLEND_Masked
    mat.shading_model = ue.EMaterialShadingModel.MSM_DefaultLit
    mat.is_sky = False
    edit.delete_all_material_expressions(mat)

    def node(cls: Any, x: int, y: int) -> Any:
        return edit.create_material_expression(mat, cls, x, y)

    def link(a: Any, b: Any, pin: str = "", out: str = "") -> None:
        assert edit.connect_material_expressions(a, out, b, pin)

    def scalar(parameter: str, value: float, x: int, y: int) -> Any:
        p = node(ue.MaterialExpressionScalarParameter, x, y)
        p.parameter_name = parameter
        p.default_value = value
        return p

    def constant(value: float, x: int, y: int) -> Any:
        c = node(ue.MaterialExpressionConstant, x, y)
        c.r = value
        return c

    tex = node(ue.MaterialExpressionTextureSampleParameter2D, -500, 0)
    tex.parameter_name = "DoomTexture"
    tex.texture = cast(ue.Texture, ue.load_object(CONTENT + "/textures/STARTAN3"))
    inside = None
    if kind in ("world", "masked"):
        coordinates = node(ue.MaterialExpressionTextureCoordinate, -800, 200)
        offset = node(ue.MaterialExpressionAppendVector, -500, 400)
        link(scalar("DoomScrollX", 0.0, -800, 400), offset, "A")
        link(constant(0.0, -800, 600), offset, "B")
        uv = node(ue.MaterialExpressionAdd, -250, 200)
        link(coordinates, uv, "A")
        link(offset, uv, "B")
        link(uv, tex)
        vertex = node(ue.MaterialExpressionVertexColor, -800, 800)
        light = node(ue.MaterialExpressionComponentMask, -600, 800)
        light.r, light.g, light.b, light.a = True, False, False, False
        link(vertex, light)
        scaled = node(ue.MaterialExpressionMultiply, -400, 800)
        link(scalar("DoomEmissiveScale", 0.5, -600, 950), scaled, "A")
        link(light, scaled, "B")
        level = node(ue.MaterialExpressionAdd, -250, 800)
        link(scalar("DoomEmissiveMin", 0.06, -400, 950), level, "A")
        link(scaled, level, "B")
    else:
        if kind == "billboard":
            uv, inside = sprite_uv(mat)
            link(uv, tex)
        level = scalar("DoomEmissive", 0.35, -400, 800)
    emission = node(ue.MaterialExpressionMultiply, -100, 300)
    link(tex, emission, "A", "RGB")
    link(level, emission, "B")
    final: Any = emission
    if kind in ("world", "masked"):
        final = glow_emission(mat, tex, emission, scalar)
    assert edit.connect_material_property(tex, "RGB", ue.EMaterialProperty.MP_BaseColor)
    assert edit.connect_material_property(final, "", ue.EMaterialProperty.MP_EmissiveColor)
    # World surfaces take their gloss from per-instance scalars (matte by default; liquids set them).
    rough = (
        scalar("DoomRoughness", 1.0, -100, 500) if kind in ("world", "masked") else constant(1.0, -100, 500)
    )
    shine = (
        scalar("DoomSpecular", 0.0, -100, 600) if kind in ("world", "masked") else constant(0.0, -100, 600)
    )
    assert edit.connect_material_property(rough, "", ue.EMaterialProperty.MP_Roughness)
    assert edit.connect_material_property(shine, "", ue.EMaterialProperty.MP_Specular)
    if kind != "world":
        if inside is not None:
            mask = node(ue.MaterialExpressionMultiply, -200, 100)
            link(tex, mask, "A", "A")
            link(inside, mask, "B")
            assert edit.connect_material_property(mask, "", ue.EMaterialProperty.MP_OpacityMask)
        else:
            assert edit.connect_material_property(tex, "A", ue.EMaterialProperty.MP_OpacityMask)
    edit.recompile_material(mat)
    assert ue.EditorAssetLibrary.save_loaded_asset(mat, False)


def visual_materials(tools: ue.AssetTools) -> None:
    """Darkening fuzz and inverted monochrome invulnerability, both unlit."""
    edit = ue.MaterialEditingLibrary
    for name in ("M_Fuzz", "M_Invulnerability"):
        mat = ue.load_object(CONTENT + "/" + name)
        if mat is None:
            mat = tools.create_asset(name, CONTENT, ue.Material, ue.new_object(ue.MaterialFactoryNew))
        assert isinstance(mat, ue.Material)
        edit.delete_all_material_expressions(mat)
        mat.shading_model = ue.EMaterialShadingModel.MSM_Unlit
        mat.two_sided = True
        if name == "M_Fuzz":
            mat.blend_mode = ue.EBlendMode.BLEND_Translucent
            tex: Any = edit.create_material_expression(
                mat, ue.MaterialExpressionTextureSampleParameter2D, -800, 0
            )
            tex.parameter_name = "DoomTexture"
            tex.texture = ue.load_object(CONTENT + "/sprites/SARGA1")
            # Animated world-space noise breaks the outline into moving fuzzy fragments.
            time = edit.create_material_expression(mat, ue.MaterialExpressionTime, -1000, 400)
            rate: Any = edit.create_material_expression(mat, ue.MaterialExpressionConstant, -1000, 600)
            rate.r = 45.0
            phase = edit.create_material_expression(mat, ue.MaterialExpressionMultiply, -800, 400)
            assert edit.connect_material_expressions(time, "", phase, "A")
            assert edit.connect_material_expressions(rate, "", phase, "B")
            position = edit.create_material_expression(mat, ue.MaterialExpressionWorldPosition, -1000, 800)
            moving = edit.create_material_expression(mat, ue.MaterialExpressionAdd, -600, 500)
            assert edit.connect_material_expressions(position, "", moving, "A")
            assert edit.connect_material_expressions(phase, "", moving, "B")
            noise: Any = edit.create_material_expression(mat, ue.MaterialExpressionNoise, -400, 500)
            noise.scale = 1.8
            noise.quality = 1
            noise.levels = 1
            noise.output_min = 0.3
            noise.output_max = 0.65
            assert edit.connect_material_expressions(moving, "", noise, "")
            # Vanilla fuzz shows the pixels behind the silhouette, darkened (colormap 6). Black (no emissive)
            # at opacity 1 - noise leaves noise x the colour behind, without reading the scene colour, which
            # the mobile forward renderer of the web build cannot do.
            darkness = edit.create_material_expression(mat, ue.MaterialExpressionOneMinus, -200, 500)
            assert edit.connect_material_expressions(noise, "", darkness, "")
            uv, inside = sprite_uv(mat)
            assert edit.connect_material_expressions(uv, "", tex, "")
            silhouette: Any = edit.create_material_expression(mat, ue.MaterialExpressionMultiply, 0, 200)
            assert edit.connect_material_expressions(tex, "A", silhouette, "A")
            assert edit.connect_material_expressions(inside, "", silhouette, "B")
            opacity = edit.create_material_expression(mat, ue.MaterialExpressionMultiply, 200, 300)
            assert edit.connect_material_expressions(silhouette, "", opacity, "A")
            assert edit.connect_material_expressions(darkness, "", opacity, "B")
            assert edit.connect_material_property(opacity, "", ue.EMaterialProperty.MP_Opacity)
        else:
            mat.material_domain = ue.EMaterialDomain.MD_PostProcess
            mat.is_blendable = True
            mat.blendable_location = ue.EBlendableLocation.BL_SceneColorAfterTonemapping
            mat.blendable_priority = 100
            scene: Any = edit.create_material_expression(mat, ue.MaterialExpressionSceneTexture, -600, 0)
            scene.scene_texture_id = ue.ESceneTextureId.PPI_PostProcessInput0
            weights: Any = edit.create_material_expression(
                mat, ue.MaterialExpressionConstant3Vector, -600, 200
            )
            weights.constant = ue.LinearColor(0.2126, 0.7152, 0.0722, 1)
            gray = edit.create_material_expression(mat, ue.MaterialExpressionDotProduct, -400, 0)
            assert edit.connect_material_expressions(scene, "", gray, "A")
            assert edit.connect_material_expressions(weights, "", gray, "B")
            invert = edit.create_material_expression(mat, ue.MaterialExpressionOneMinus, -200, 0)
            assert edit.connect_material_expressions(gray, "", invert, "")
            assert edit.connect_material_property(invert, "", ue.EMaterialProperty.MP_EmissiveColor)
        edit.recompile_material(mat)
        assert ue.EditorAssetLibrary.save_loaded_asset(mat, False)


MUSIC_GAIN = 0.3  # FluidSynth master gain: low enough that no score clips before the peak normalization


MUSIC_PEAK = 29200  # every rendered track is peak-normalized to about -1 dBFS
MUSIC_RATE = 22050  # mono at 22.05 kHz: a quarter of the size of the 44.1 kHz stereo renders


def is_small_render(wav: Path) -> bool:
    try:
        with wave.open(str(wav), "rb") as source:
            return source.getframerate() == MUSIC_RATE and source.getnchannels() == 1
    except (wave.Error, EOFError, OSError):
        return False


def downmix_mono(source: Path, destination: Path) -> None:
    """Average a 16-bit stereo WAV into a peak-normalized mono WAV (the renders are near-mono anyway)."""
    with wave.open(str(source), "rb") as reader:
        channels, width, rate = reader.getnchannels(), reader.getsampwidth(), reader.getframerate()
        assert width == 2, f"unexpected sample width {width}"
        frames = reader.readframes(reader.getnframes())
    samples = array("h")
    samples.frombytes(frames)
    if channels == 2:
        samples = array(
            "h", [(left + right) // 2 for left, right in zip(samples[0::2], samples[1::2], strict=True)]
        )
    peak = max(max(samples, default=0), -min(samples, default=0))
    if peak > 0:  # normalize: the SoundFont renders are quiet, and their level differs per score
        scale = MUSIC_PEAK / peak
        samples = array("h", [round(value * scale) for value in samples])
    with wave.open(str(destination), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(samples.tobytes())


def render_music() -> list[Path]:
    """Render the extracted D_*.mid scores to ASSETS/music/*.wav with FluidSynth (only missing ones)."""
    midis = sorted(ASSETS.glob("D_*.mid"))
    synth, font = find_fluidsynth(), find_soundfont()
    if synth is None or font is None:
        ue.log(
            "Doom music skipped: FluidSynth or a SoundFont was not found "
            "(set FLUIDSYNTH and DOOM_SOUNDFONT, see README.md, Music)."
        )
        return []
    folder = ASSETS / "music"
    folder.mkdir(exist_ok=True)
    wavs = []
    for midi in midis:
        wav = folder / (midi.stem + ".wav")
        if wav.is_file() and not is_small_render(wav):
            wav.unlink()  # an old 44.1 kHz stereo render: redo it (main() reimports its SoundWave)
        if not wav.is_file():
            temporary = wav.with_suffix(".part")
            command = [
                str(synth),
                "-ni",
                "-g",
                str(MUSIC_GAIN),
                "-r",
                str(MUSIC_RATE),
                "-F",
                str(temporary),
                str(font),
                str(midi),
            ]
            done = subprocess.run(command, capture_output=True, check=False)
            if done.returncode != 0 or not temporary.is_file():
                ue.log(f"Doom music: FluidSynth failed on {midi.name}")
                temporary.unlink(missing_ok=True)
                continue
            full = wav.with_suffix(".full")
            temporary.replace(full)
            downmix_mono(full, temporary)
            full.unlink()
            temporary.replace(wav)
        wavs.append(wav)
    return wavs


def main(_args: list[str]) -> dict[str, Any]:
    result = extract()
    tools = ue.AssetToolsHelpers.get_asset_tools()
    assert tools is not None
    tasks = []
    rendered = render_music()
    for folder, extension in (("textures", "png"), ("sprites", "png"), ("sounds", "wav"), ("music", "wav")):
        for source in sorted((ASSETS / folder).glob(f"*.{extension}")):
            destination = f"{CONTENT}/{folder}"
            replace = False
            if ue.EditorAssetLibrary.does_asset_exist(f"{destination}/{source.stem}"):
                if folder == "music":
                    old = ue.load_object(f"{destination}/{source.stem}")
                    replace = (
                        isinstance(old, ue.SoundWave)
                        and (old.num_channels != 1 or round(old.sample_rate) != MUSIC_RATE)
                    )  # fmt: skip
                if extension == "png":
                    existing = ue.load_object(f"{destination}/{source.stem}")
                    assert isinstance(existing, ue.Texture2D)
                    if (
                        existing.filter != ue.TextureFilter.TF_Nearest
                        or existing.mip_gen_settings != ue.TextureMipGenSettings.TMGS_NoMipmaps
                        or not existing.never_stream
                    ):
                        existing.filter = ue.TextureFilter.TF_Nearest
                        existing.mip_gen_settings = ue.TextureMipGenSettings.TMGS_NoMipmaps
                        existing.never_stream = True
                        assert ue.EditorAssetLibrary.save_loaded_asset(existing, False)
                if not replace:
                    continue
            task = ue.new_object(ue.AssetImportTask)
            task.filename = str(source)
            task.destination_path = destination
            task.destination_name = source.stem
            task.automated = True
            task.save = True
            task.replace_existing = replace
            tasks.append(task)
    for start in range(0, len(tasks), 40):
        batch = tasks[start : start + 40]
        tools.import_asset_tasks(batch)
        for task in batch:
            objects = task.get_objects()
            assert objects, f"Import failed: {task.filename}"
            for obj in objects:
                if isinstance(obj, ue.Texture2D):
                    obj.filter = ue.TextureFilter.TF_Nearest
                    obj.mip_gen_settings = ue.TextureMipGenSettings.TMGS_NoMipmaps
                    obj.never_stream = True
                    ue.EditorAssetLibrary.save_loaded_asset(obj, False)
                elif isinstance(obj, ue.SoundWave) and "/music" in task.destination_path:
                    obj.looping = True
                    ue.EditorAssetLibrary.save_loaded_asset(obj, False)
        ue.log(f"Doom data import: {min(start + 40, len(tasks))}/{len(tasks)}")
    visual_materials(tools)  # after the import: M_Fuzz samples SARGA1
    material(tools, False)
    material(tools, True)
    material(tools, False, True)
    billboard_material(tools)
    sky_material(tools)
    for lit in lighting.LIT_ASSETS:
        lit_material(tools, lit)
    result["imported"] = len(tasks)
    result["music"] = len(rendered)
    return result

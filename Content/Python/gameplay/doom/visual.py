"""Sprite selection and layout shared by the native Doom renderer and its checks."""

from __future__ import annotations

import math
from typing import Any, cast

_VIEWS: list[Any] = [None, {}]  # [sprite set, {(stem, rotation): view}]


def sprite_view(sprites: dict[str, Any], stem: str, rotation: int = 0) -> tuple[str, bool]:
    """Resolve packed Doom lumps (A2A8), including their mirrored second view (memoised per sprite set)."""
    if _VIEWS[0] is not sprites:
        _VIEWS[:] = [sprites, {}]
    views = cast("dict[tuple[str, int], tuple[str, bool]]", _VIEWS[1])
    request = (stem, rotation)
    if request not in views:
        views[request] = _sprite_view(sprites, stem, rotation)
    return views[request]


def _sprite_view(sprites: dict[str, Any], stem: str, rotation: int) -> tuple[str, bool]:
    if stem + "0" in sprites:
        return stem + "0", False
    wanted = str(rotation or 1)
    if stem + wanted in sprites:
        return stem + wanted, False
    for key in sprites:
        if key[:5] == stem and key[5:6] == wanted:
            return key, False
        if len(key) == 8 and key[:4] == stem[:4] and key[6:8] == stem[4] + wanted:
            return key, True
    return "", False


def view_rotation(x: float, y: float, camera_x: float, camera_y: float, facing: float) -> int:
    angle = math.degrees(math.atan2(camera_y - y, camera_x - x))
    # Angle here is actor -> camera; Doom's renderer uses camera -> actor.
    return int(math.floor((angle - facing + 22.5) / 45)) % 8 + 1


def hud_layout(width: int, height: int) -> tuple[float, float, float]:
    scale = min(width / 320, height / 240)
    return scale, (width - 320 * scale) / 2, height - 32 * scale


def projectile_family(key: str, weapon: str) -> str:
    if weapon != "monster":
        return weapon
    return {"BAL1": "imp", "BAL2": "caco", "BAL7": "baron", "MISL": "rocket"}.get(key[:4], "imp")

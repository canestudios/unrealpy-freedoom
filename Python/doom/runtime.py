"""Facade over the Doom runtime modules: one namespace for the names callers reach through `game()`."""

from __future__ import annotations

from doom.common import (
    BARREL_EXPLOSION as BARREL_EXPLOSION,
)
from doom.common import (
    CEILING_KEY as CEILING_KEY,
)
from doom.common import (
    DECOR as DECOR,
)
from doom.common import (
    DEMONS as DEMONS,
)
from doom.common import (
    FLOOR_KEY as FLOOR_KEY,
)
from doom.common import (
    FLOOR_SPECIALS as FLOOR_SPECIALS,
)
from doom.common import (
    ITEMS as ITEMS,
)
from doom.common import (
    KEYS as KEYS,
)
from doom.common import (
    MODE as MODE,
)
from doom.common import (
    SCALE as SCALE,
)
from doom.common import (
    TIC as TIC,
)
from doom.common import (
    WALK_SPECIALS as WALK_SPECIALS,
)
from doom.common import (
    WHITE as WHITE,
)
from doom.common import (
    mode_now as mode_now,
)
from doom.common import (
    ray as ray,
)
from doom.common import (
    section as section,
)
from doom.common import (
    segments_cross as segments_cross,
)
from doom.common import (
    vec as vec,
)
from doom.common import (
    weapon_aim_x as weapon_aim_x,
)
from doom.common import (
    weapon_frame as weapon_frame,
)
from doom.common import (
    weapon_time as weapon_time,
)
from doom.common import (
    xy as xy,
)
from doom.game import demo as demo
from doom.game import host as host
from doom.game import join as join
from doom.game import play as play
from doom.hud import DoomHUD as DoomHUD
from doom.mode import DoomHangarMode as DoomHangarMode
from doom.monsters import DoomDemon as DoomDemon
from doom.music import DoomMusic as DoomMusic
from doom.player import DoomController as DoomController
from doom.player import DoomInput as DoomInput
from doom.player import DoomMarine as DoomMarine
from doom.projectiles import DoomFireball as DoomFireball
from doom.projectiles import DoomProjectile as DoomProjectile
from doom.state import DoomGameState as DoomGameState
from doom.state import DoomPlayerState as DoomPlayerState
from doom.world import DoomBarrel as DoomBarrel
from doom.world import DoomEffect as DoomEffect
from doom.world import DoomGeometry as DoomGeometry
from doom.world import DoomSprite as DoomSprite

"""The Doom level on one machine: WAD data, materials, geometry and the queries over them.

`LevelRuntime` is a mixin of the game mode (the server, or the standalone game) and of the game state (the
client, which has no game mode): both build the same native geometry from the same map JSON, and the sound,
effect and sector queries the rest of the example makes through `mode_now()` mean the same on either side.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import TYPE_CHECKING, Any, cast

import ue
from doom import campaign, geometry, lighting, specials, world
from doom.animation import EFFECT_STATES
from doom.common import (
    CEILING_KEY,
    FLOOR_KEY,
    SCALE,
    TIC,
    components,
    player_now,
    ray,
    section,
    vec,
    weapon_aim_x,
)
from doom.dataset import ASSETS, CONTENT
from doom.music import DoomMusic
from doom.rules import COOP, MATCH_RULES, MatchRules
from doom.visual import hud_layout
from doom.wad import png_top_colour

if TYPE_CHECKING:
    from doom.player import DoomMarine

# Per-player values the single-player API (`mode.health`, `mode.weapons`, ...) reads and writes: they live on
# the local player's DoomPlayerState and the mode forwards them, so the HUD, the cheats and the saves stay
# as they were.
PLAYER_FIELDS = (
    "health",
    "armor",
    "armor_type",
    "bullets",
    "shells",
    "rockets",
    "cells",
    "weapon",
    "weapons",
    "keys",
    "key_kinds",
    "backpack",
    "berserk",
    "all_map",
    "god_mode",
    "dead",
    "invulnerability",
    "suit",
    "invisibility",
    "light_visor",
    "cooldown",
    "weapon_action",
    "weapon_clock",
    "weapon_event",
    "flash_variant",
    "fire_held",
    "pain",
    "pickup_flash",
    "berserk_flash",
)
_NEUTRAL: dict[str, Any] = {
    "health": 100,
    "armor": 0,
    "armor_type": 1,
    "weapon": "pistol",
    "backpack": False,
    "berserk": False,
    "all_map": False,
    "god_mode": False,
    "dead": False,
    "weapon_action": "",
    "flash_variant": 0,
    "fire_held": False,
    "weapon_event": 0,
    "bullets": 0,
    "shells": 0,
    "rockets": 0,
    "cells": 0,
}


def _forward(name: str) -> property:
    def get(self: LevelRuntime) -> Any:
        ps = self.primary()
        if ps is None:
            if name in ("weapons", "keys"):
                return set()
            if name == "key_kinds":
                return {}
            return _NEUTRAL.get(name, 0.0)
        return getattr(ps, name)

    def put(self: LevelRuntime, value: Any) -> None:
        ps = self.primary()
        if ps is not None:
            setattr(ps, name, value)

    return property(get, put)


class LevelRuntime:
    """Level state and queries shared by `DoomHangarMode` and `DoomGameState`."""

    if TYPE_CHECKING:
        # What the game mode and the game state set (declared for the type checker); the per-player fields
        # are the forwarded ones of PLAYER_FIELDS.
        skill: int
        testing: bool
        started: bool
        positioned: bool
        loaded: list[ue.Object]
        music: DoomMusic
        enemies: list[Any]
        sound_targets: dict[int, ue.Actor]
        sound_graph: dict[int, list[tuple[int, int, bool]]] | None
        health: int
        armor: int
        armor_type: int
        bullets: int
        shells: int
        rockets: int
        cells: int
        weapon: str
        weapons: set[str]
        keys: set[str]
        key_kinds: dict[str, int]
        backpack: bool
        berserk: bool
        all_map: bool
        god_mode: bool
        dead: bool
        invulnerability: float
        suit: float
        invisibility: float
        light_visor: float
        cooldown: float
        weapon_action: str
        weapon_clock: float
        weapon_event: int
        flash_variant: int
        fire_held: bool
        pain: float
        pickup_flash: float
        berserk_flash: float

    _primary: Any = None
    match_name = "coop"  # the network game mode (rules.MATCH_RULES); the game state replicates it
    networked = False  # a listen server or a client: nothing pauses, and there is more than one player
    ready = True  # the level is built (a client waits for the server's map)

    @property
    def match(self) -> MatchRules:
        """The rules of the network game mode being played (co-op; the deathmatch phase adds its own)."""
        return MATCH_RULES.get(str(self.match_name), COOP)

    @property
    def paused(self) -> bool:
        """The single-player menu stops the game; in a network game nothing can."""
        return bool(self.menu) and not self.networked

    def everyone_dead(self) -> bool:
        from doom import net

        players = net.players()
        return bool(players) and all(ps.dead for ps in players)

    def marines(self) -> list[DoomMarine]:
        from doom import net

        return net.marines()

    def primary(self) -> Any:
        """The DoomPlayerState of the player at this machine (player controller 0)."""
        ps = self._primary
        if ps is not None and ps.is_valid():
            return ps
        controller = ue.GameplayStatics.get_player_controller(0)
        ps = controller.player_state if controller is not None else None
        self._primary = ps if ps is not None and ps.is_valid() else None
        return self._primary

    def init_common(self) -> None:
        """Everything local to this machine's copy of the level (nothing here replicates)."""
        self.menu, self.menu_row = "main", 0
        self.notice, self.notice_timer = "", 0.0
        self.show_map = False
        self.automap_level = 0  # IDDT: 0 as the map is, 1 every line, 2 every line and the things
        self.elapsed = 0.0
        self.level_clock = 0.0  # Doom's leveltime: counts while the marines are dead too
        self.crush_now = False  # this frame is one where crushers hurt (every fourth tic)
        self.objects, self.geometry = [], []
        self.materials, self.textures, self.sounds = {}, {}, {}
        self.animated_materials, self.scroll_materials, self.button_materials = [], {}, {}
        self.animation_frame = -1
        self.effects_seen: dict[str, int] = {}  # how many of each effect this machine spawned (for tests)
        self.switch_timers = {}
        self.doors, self.movers, self.ceilings = {}, {}, {}
        self.switches = set()
        self.sector_cache = {}
        self.data = {}
        self.console_text = ""
        self.console_lines = ["DOOM CONSOLE - F1 / ESC TO CLOSE - HELP FOR COMMANDS"]
        self.console_history = []
        self.console_history_index = 0

    def init_counters(self) -> None:
        """The level's totals and flags (the game mode's; the game state replicates them)."""
        self.won = False
        self.kills = self.item_count = 0
        self.total, self.total_items = 0, 0
        self.secrets: set[int] = set()
        self.secret_exit = False
        self.marker = "E1M1"
        self.level_serial = 0
        self.triggered = set()

    def load_data(self, marker: str) -> None:
        self.marker = marker
        self.data = json.loads((ASSETS / f"{marker}.json").read_text(encoding="utf-8"))

    def things(self) -> list[Any]:
        """The actors the lit mode lights and re-materials: the level's own (the game mode's)."""
        return self.objects

    def clear_level(self) -> None:
        """Forget the built level: destroy its native geometry and every cached material."""
        for actor in [*self.objects, *self.geometry]:
            if actor.is_valid():
                actor.destroy_actor()
        self.objects, self.geometry = [], []
        self.doors, self.movers, self.ceilings = {}, {}, {}
        self.materials = {}
        self.animated_materials, self.scroll_materials, self.button_materials = [], {}, {}
        self.animation_frame = -1

    def build_portals(self) -> None:
        """The monsters' path graph; only the simulation (the game mode) has one."""

    def tell(self, who: Any, text: str, seconds: float = 1.5) -> None:
        """Put a message on a player's screen (everyone's when `who` is None)."""
        if who is None or not hasattr(who, "notify"):
            self.notice, self.notice_timer = text, seconds
        else:
            who.notify(text, seconds)

    def play_sound(self, key: str, volume: float = 0.8) -> ue.AudioComponent | None:
        """Play a one-shot sound on this machine only."""
        if key not in self.sounds:
            sound = ue.load_object(f"{CONTENT}/sounds/{key}.{key}")
            if isinstance(sound, ue.Object):
                self.loaded = [*self.loaded, sound]
            self.sounds[key] = sound
        if self.sounds[key] is not None:
            return ue.GameplayStatics.spawn_sound2d(
                cast(ue.SoundBase, self.sounds[key]), volume, world_context_object=cast(ue.Object, self)
            )
        return None

    def spawn_effect(self, name: str, location: Any) -> world.DoomEffect:
        """Spawn a short-lived effect (puff, blood, teleport flash) on this machine only."""
        effect = ue.spawn_actor(world.DoomEffect, location=location)
        self.effects_seen[name] = self.effects_seen.get(name, 0) + 1
        effect.effect_name = name
        effect.image(EFFECT_STATES[name][0][0])
        self.objects.append(effect)
        return effect

    def update_view(self, delta_seconds: float) -> None:
        """Local screen effects of the player at this machine (the invulnerability tint)."""
        from doom import player as player_mod

        player = player_now()
        ps = self.primary()
        if not isinstance(player, player_mod.DoomMarine) or ps is None:
            return
        if not hasattr(self, "invulnerability_material"):
            parent = ue.load_object(CONTENT + "/M_Invulnerability.M_Invulnerability")
            assert isinstance(parent, ue.MaterialInterface)
            self.invulnerability_material = ue.KismetMaterialLibrary.create_dynamic_material_instance(parent)
            self.loaded = [*self.loaded, self.invulnerability_material]
        invulnerability = ps.invulnerability
        active = invulnerability > 4 or (invulnerability > 0 and bool(int(invulnerability / TIC) & 8))
        player.camera.add_or_update_blendable(self.invulnerability_material, 1.0 if active else 0.0)

    def game_state(self) -> Any:
        return ue.GameplayStatics.get_game_state()

    def sound(
        self, key: str, volume: float = 0.8, at: Any = None, who: Any = None
    ) -> ue.AudioComponent | None:
        """A game sound: heard by everyone (louder near `at`), or only by player `who`."""
        from doom import net

        if not net.networked():
            return self.play_sound(key, volume)
        if who is not None and hasattr(who, "hear"):
            who.hear(key, volume)
        else:
            gs = self.game_state()
            if gs is not None:
                x, y, z = components(at) if at is not None else (0.0, 0.0, 0.0)
                gs.mc_sound(key, volume, x, y, z, at is not None)
        return None

    def effect(self, name: str, location: Any) -> world.DoomEffect | None:
        """A short-lived effect everywhere (a multicast when networked)."""
        from doom import net

        gs = self.game_state()
        if not net.networked() or gs is None:
            return self.spawn_effect(name, location)
        gs.mc_effect(name, *components(location))
        return None

    def texture(self, key: str, sprite: bool = False) -> Any:
        cache_key = (key, sprite)
        if cache_key not in self.textures:
            texture = ue.load_object(f"{CONTENT}/{'sprites' if sprite else 'textures'}/{key}.{key}")
            if isinstance(texture, ue.Object):
                self.loaded = [*self.loaded, texture]
            self.textures[cache_key] = texture
        return self.textures[cache_key]

    def material(
        self, key: str, sprite: bool = False, sector: int = -1, masked: bool = False, sky: bool = False
    ) -> Any:
        cache_key = (key, sprite, -1 if sprite else sector, masked, sky)
        if cache_key not in self.materials:
            parent = ue.load_object(
                lighting.parent_path("M_MaskedWorld")
                if masked
                else lighting.parent_path("M_Sprite")
                if sprite
                else lighting.parent_path("M_World", sky=sky)  # the sky stays flat-bright
            )
            assert isinstance(parent, ue.MaterialInterface), "Run doom.importer:main in editor first"
            mat = ue.KismetMaterialLibrary.create_dynamic_material_instance(parent)
            assert mat is not None
            texture = self.texture(key, sprite)
            assert texture is not None, f"Missing Doom texture {key}"
            mat.set_texture_parameter_value("DoomTexture", texture)
            if sky:  # the flat colour the sky fades to above the texture's top row
                r, g, b = png_top_colour(ASSETS / "textures" / f"{key}.png")
                mat.set_vector_parameter_value("SkyTopColor", ue.LinearColor(r, g, b, 1))
            if lighting.active() and not sky:
                lighting.tune_surface(mat, sprite, key)
            self.materials[cache_key] = mat
            if not sprite:
                campaign.register_animation(self, mat, key)
        return self.materials[cache_key]

    def fuzz_material(self, key: str) -> Any:
        cache_key = (key, "fuzz")
        if cache_key not in self.materials:
            parent = ue.load_object(CONTENT + "/M_Fuzz.M_Fuzz")
            assert isinstance(parent, ue.MaterialInterface), "Run doom.importer:main in editor first"
            mat = ue.KismetMaterialLibrary.create_dynamic_material_instance(parent)
            assert mat is not None
            mat.set_texture_parameter_value("DoomTexture", self.texture(key, True))
            self.materials[cache_key] = mat
        return self.materials[cache_key]

    def sector_at(self, x: float, y: float) -> int:
        key = (round(x), round(y))
        cached = self.sector_cache.get(key)
        if cached is not None and cached[0] == (x, y):
            return cached[1]
        sector = self.locate_sector(x, y)
        if len(self.sector_cache) > 4096:
            self.sector_cache.clear()
        self.sector_cache[key] = ((x, y), sector)
        return sector

    def locate_sector(self, x: float, y: float) -> int:
        index = len(self.data["nodes"]) - 1 if self.data["nodes"] else 0x8000
        while not index & 0x8000:
            node = self.data["nodes"][index]
            side = 0 if node[2] * (y - node[1]) - node[3] * (x - node[0]) <= 0 else 1
            index = node[12 + side]
        _, first = self.data["leaves"][index & 0x7FFF]
        seg = self.data["segs"][first]
        line = self.data["lines"][seg[3]]
        return int(self.data["sides"][line["right" if seg[4] == 0 else "left"]]["sector"])

    def sector_floor(self, index: int) -> float:
        mover = self.movers.get(index)
        return float(self.data["sectors"][index]["floor"]) + float(mover["offset"] if mover else 0.0)

    def floor(self, x: float, y: float) -> float:
        return self.sector_floor(self.sector_at(x, y))

    def neighbours(self, index: int) -> set[int]:
        sides, found = self.data["sides"], set[int]()
        for line in self.data["lines"]:
            if line["left"] != 65535:
                a, b = sides[line["right"]]["sector"], sides[line["left"]]["sector"]
                if index in (a, b):
                    found.add(b if a == index else a)
        found.discard(index)
        return found

    def plan_movers(self) -> None:
        specials.plan(self)

    def lowest_floor(self, index: int) -> float:
        floor = float(self.data["sectors"][index]["floor"])
        mover = self.movers.get(index)
        return floor + min(0.0, float(mover["target"])) if mover else floor

    def build(self) -> None:
        self.sector_cache: dict[tuple[int, int], tuple[tuple[float, float], int]] = {}
        self.sound_graph = None
        # Pathfinding memo, valid for one `geo_version` (bumped when a door or a mover changes).
        self.geo_version = 0
        self.route_version = -1
        self.route_budget = 4
        self.plan_movers()
        self.build_portals()
        geometry.prepare(self)
        self.sky_faces: list[dict[str, Any]]
        self.geo_dirty: set[int]
        buckets = defaultdict(lambda: [[], [], []])
        sectors, sides, vertices = self.data["sectors"], self.data["sides"], self.data["vertices"]

        def add(
            key: tuple[Any, ...],
            points: list[Any],
            coords: list[Any],
            triangles: list[int] | None = None,
            masked: bool = False,
            collision: bool = True,
        ) -> None:
            verts, tris, uv = buckets[(*key, masked, collision)]
            offset = len(verts)
            verts.extend(vec(*p) for p in points)
            uv.extend(ue.Vector2D(*p) for p in coords)
            tris.extend(offset + n for n in (triangles if triangles is not None else [0, 1, 2, 0, 2, 3]))

        for polygon in self.data["polygons"]:
            index, points = polygon["sector"], polygon["points"]
            sector = sectors[index]
            light = (sector["light"] / 255) ** 2.2
            for ceiling in (False, True):
                tex = sector["ceiling_tex" if ceiling else "floor_tex"]
                if tex == "F_SKY1":
                    if ceiling:
                        self.sky_faces.append(dict(sector=index, points=points))
                    continue
                z = sector["ceiling" if ceiling else "floor"]
                moving = index if ceiling and index in self.doors else -1
                if ceiling and index in self.ceilings:
                    moving = CEILING_KEY + index
                if not ceiling and index in self.movers:
                    moving = FLOOR_KEY + index
                triangles = [
                    n
                    for i in range(1, len(points) - 1)
                    for n in ((0, i + 1, i) if ceiling else (0, i, i + 1))
                ]
                add(
                    (tex, light, moving, index, -1),
                    [(p[0], p[1], z) for p in points],
                    [(p[0] / 64, -p[1] / 64) for p in points],
                    triangles,
                )
        for line_index, line in enumerate(self.data["lines"]):
            for side_name, other_name in (("right", "left"), ("left", "right")):
                if line[side_name] == 65535:
                    continue
                side = sides[line[side_name]]
                si = side["sector"]
                sector = sectors[si]
                a, b = vertices[line["a"]], vertices[line["b"]]
                if side_name == "left":
                    a, b = b, a
                length = math.dist(a, b)
                contrast = -16 if a[1] == b[1] else 16 if a[0] == b[0] else 0
                light = (max(0, min(255, sector["light"] + contrast)) / 255) ** 2.2
                spans = []
                if line[other_name] == 65535:
                    # A closed door's own walls (its jambs) have no height: build them up to where it opens.
                    top = sector["ceiling"]
                    if si in self.doors:
                        top = max(sector["ceiling"], sector["ceiling"] + self.doors[si]["target"] + 4)
                    # Lift shafts keep their side walls down to the lowest reachable floor.
                    spans.append((side["middle"], self.lowest_floor(si), top, -1))
                else:
                    oi = sides[line[other_name]]["sector"]
                    other = sectors[oi]
                    geometry.register(self, side, a, b, si, oi, False, line_index, light)
                    geometry.register(self, side, a, b, si, oi, True, line_index, light)
                    if side["middle"] != "-":
                        texture = side["middle"]
                        w, h = self.data["textures"][texture]
                        opening_low = max(sector["floor"], other["floor"])
                        opening_high = min(sector["ceiling"], other["ceiling"])
                        # Doom's masked middle textures occupy one texture height, not a tiled wall.
                        top = (opening_low + h if line["flags"] & 16 else opening_high) + side["y"]
                        low, high = max(opening_low, top - h), min(opening_high, top)
                        if high > low:
                            u0, u1 = side["x"] / w, (side["x"] + length) / w
                            add(
                                (texture, light, -1, si, line_index),
                                [
                                    (a[0], a[1], low),
                                    (b[0], b[1], low),
                                    (b[0], b[1], high),
                                    (a[0], a[1], high),
                                ],
                                [
                                    (u0, (top - low) / h),
                                    (u1, (top - low) / h),
                                    (u1, (top - high) / h),
                                    (u0, (top - high) / h),
                                ],
                                masked=True,
                                collision=False,
                            )
                for texture, low, high, moving in spans:
                    if texture == "-" or high <= low:
                        continue
                    w, h = self.data["textures"][texture]
                    u0, u1 = side["x"] / w, (side["x"] + length) / w
                    v0, v1 = side["y"] / h, (side["y"] + high - low) / h
                    if line[other_name] == 65535 and line["flags"] & 16:
                        # Lower unpegged (door jambs): the texture is anchored to the floor.
                        v1 = (side["y"] + h) / h
                        v0 = v1 - (high - low) / h
                    add(
                        (
                            texture,
                            light,
                            moving,
                            si,
                            line_index if texture.startswith(("SW1", "SW2")) or line["special"] == 48 else -1,
                        ),
                        [
                            (a[0], a[1], low),
                            (b[0], b[1], low),
                            (b[0], b[1], high),
                            (a[0], a[1], high),
                        ],
                        [(u0, v1), (u1, v1), (u1, v0), (u0, v0)],
                    )
        groups = {}
        for (texture, light, moving, si, wall_index, masked, collision), (
            verts,
            triangles,
            uv,
        ) in buckets.items():
            if moving not in groups:
                actor = ue.spawn_actor(world.DoomGeometry)
                actor.mesh.set_collision_profile_name("BlockAll")
                actor.mesh.use_complex_as_simple_collision = True
                groups[moving] = actor
                if moving in self.doors:
                    self.doors[moving]["actor"] = actor
                elif moving >= CEILING_KEY:
                    self.ceilings[moving - CEILING_KEY]["actor"] = actor
                elif moving >= FLOOR_KEY:
                    self.movers[moving - FLOOR_KEY]["actor"] = actor
            actor = groups[moving]
            mat = self.material(
                texture, sector=si if wall_index < 0 else len(sectors) + wall_index, masked=masked
            )
            if wall_index >= 0:
                if texture.startswith(("SW1", "SW2")):
                    geometry.register_button(self, wall_index, mat, texture)
                if self.data["lines"][wall_index]["special"] == 48:
                    self.scroll_materials[(wall_index, texture)] = (
                        mat,
                        self.data["textures"][texture][0],
                    )
            section(
                actor.mesh,
                actor.mesh.get_num_sections(),
                verts,
                triangles,
                uv,
                light,
                mat,
                collision=collision,
            )
        self.geometry = list(groups.values())
        geometry.create(self)
        # Surrounding sky, visible through the actual outdoor sectors.
        for line in self.data["lines"]:
            if line["left"] == 65535 or not line["flags"] & 1:
                continue
            right, left = sides[line["right"]], sides[line["left"]]
            front, back = sectors[right["sector"]], sectors[left["sector"]]
            low = min(self.lowest_floor(right["sector"]), self.lowest_floor(left["sector"]))
            high = max(front["ceiling"], back["ceiling"])
            if high <= low:
                continue
            a, b = vertices[line["a"]], vertices[line["b"]]
            barrier = ue.spawn_actor(world.DoomGeometry)
            barrier.mesh.set_collision_profile_name("BlockAll")
            barrier.mesh.set_collision_response_to_channel(
                ue.ECollisionChannel.ECC_Visibility, ue.ECollisionResponse.ECR_Ignore
            )
            barrier.mesh.use_complex_as_simple_collision = True
            barrier.set_actor_hidden_in_game(True)
            section(
                barrier.mesh,
                0,
                [
                    vec(a[0], a[1], low),
                    vec(b[0], b[1], low),
                    vec(b[0], b[1], high),
                    vec(a[0], a[1], high),
                ],
                [0, 1, 2, 0, 2, 3],
                [ue.Vector2D(0, 0)] * 4,
                1,
                self.material("STARTAN3"),
            )
            self.geometry.append(barrier)

        # The sky: a closed sphere around the map, seen through the sky ceilings and the "sky hack" walls
        # (neither is drawn). Its material ignores UVs and derives them from the view direction, so what
        # it shows is the same at every distance and angle: the vanilla sky.
        sky = ue.spawn_actor(world.DoomGeometry)
        points, coords, triangles = [], [], []
        x0, y0, x1, y1 = self.data["bounds"]
        cx, cy, radius, rings, segments = (x0 + x1) / 2, (y0 + y1) / 2, 12000, 12, 32
        for ring in range(rings + 1):
            pitch = math.pi * (ring / rings - 0.5)
            for i in range(segments + 1):
                angle = i * math.tau / segments
                points.append(
                    vec(
                        cx + radius * math.cos(pitch) * math.cos(angle),
                        cy + radius * math.cos(pitch) * math.sin(angle),
                        radius * math.sin(pitch),
                    )
                )
                coords.append(ue.Vector2D(0, 0))
                if ring < rings and i < segments:
                    j = ring * (segments + 1) + i
                    k = j + segments + 1
                    triangles.extend((j, k, k + 1, j, k + 1, j + 1))
        episode = self.marker[1] if self.marker[1] in "1234" else "1"
        section(sky.mesh, 0, points, triangles, coords, 1, self.material(f"SKY{episode}", sky=True), False)
        self.geometry.append(sky)

    def aim_targets(self) -> list[ue.Actor]:
        """Live monsters and barrels, as this machine sees them (replicas on a client)."""
        from doom import monsters

        found: list[ue.Actor] = []
        for cls in (monsters.DoomDemon, world.DoomBarrel):
            found.extend(
                actor
                for actor in ue.GameplayStatics.get_all_actors_of_class(cls)
                if isinstance(actor, cls) and actor.is_valid()
            )
        return found

    def aim_direction(self, player: Any, weapon: str | None = None) -> Any:
        """Project the HUD weapon's x position through the camera; preserve camera pitch."""
        from doom import monsters

        weapon = weapon or self.weapon
        forward = player.camera.get_forward_vector().copy()
        right = player.camera.get_right_vector()
        screen_x = weapon_aim_x(weapon, self.data["sprites"])
        controller = ue.GameplayStatics.get_player_controller(0)
        assert controller is not None
        width, height = controller.get_viewport_size()
        scale, _, _ = hud_layout(width, height) if width and height else (1, 0, 0)
        offset = (
            (screen_x - 160)
            * scale
            / (width / 2 if width else 160)
            * math.tan(math.radians(player.camera.field_of_view / 2))
        )
        direction = forward + right * offset
        direction /= float(sum(float(v) ** 2 for v in direction)) ** 0.5
        # Classic vertical autoaim, without pulling shots sideways away from the weapon.
        if abs(float(forward[2])) < 0.01:
            origin = player.camera.get_world_location()
            candidates = []
            for target in self.aim_targets():
                if (isinstance(target, monsters.DoomDemon) and target.dead) or (
                    isinstance(target, world.DoomBarrel) and target.exploded
                ):
                    continue
                delta = target.get_actor_location() - origin
                along = float(delta[0] * direction[0] + delta[1] * direction[1])
                across = abs(float(delta[0] * direction[1] - delta[1] * direction[0]))
                radius = (
                    10 * SCALE
                    if isinstance(target, world.DoomBarrel)
                    else cast(ue.Character, target).capsule_component.get_scaled_capsule_radius()
                )
                if along <= 0 or across > radius:
                    continue
                slope = float(delta[2]) / along
                if abs(slope) > 0.625:
                    continue
                hit, _ = ray(origin, target.get_actor_location(), [player])
                if hit == target:
                    candidates.append((along, slope))
            if candidates:
                _, slope = min(candidates)
                direction[2] = slope
                direction /= float(sum(float(v) ** 2 for v in direction)) ** 0.5
        return direction


for _field in PLAYER_FIELDS:
    setattr(LevelRuntime, _field, _forward(_field))

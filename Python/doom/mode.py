from __future__ import annotations

import heapq
import json
import math
import random
from collections import defaultdict
from typing import Any, TypeVar, cast

from typing_extensions import override

import ue
from doom import (
    campaign,
    console,
    geometry,
    hud,
    lighting,
    monsters,
    net,
    projectiles,
    specials,
    state,
    world,
)
from doom import player as player_mod
from doom.animation import WEAPON_EVENTS, WEAPON_REFIRE
from doom.common import (
    DECOR,
    DEMONS,
    ITEMS,
    SCALE,
    TIC,
    clear_cache,
    ray,
    segments_cross,
    vec,
    weapon_time,
    xy,
)
from doom.dataset import ASSETS
from doom.level import LevelRuntime
from doom.music import DoomMusic
from doom.rules import (
    COUNT_ITEMS,
    ITEM_RESPAWN_SECONDS,
    MAX_DEATHMATCH_STARTS,
    MONSTER_INFO,
    NO_RESPAWN_ITEMS,
    SPAWN_TRIES,
    WEAPONS,
    map_heading,
    music_name,
    skill_flag,
)

_A = TypeVar("_A", bound=ue.Actor)
ROUTE_BUDGET = 4  # Path searches the monsters may start per frame; the others retry on their next think.
ADVANCE_DELAY = 8.0  # seconds the co-op intermission lasts before everyone moves on


def spawn_thing(cls: type[_A], location: ue.Vector, rotation: ue.Rotator | None = None) -> _A:
    """Spawn a map thing the way Doom does: always, even overlapping geometry or other things.

    Default collision handling refuses (and destroys) the actor when it overlaps something, which
    happens on maps with tightly packed things such as Freedoom's.
    """
    transform = ue.KismetMathLibrary.make_transform(
        location, rotation if rotation is not None else ue.Rotator(), ue.Vector(1.0, 1.0, 1.0)
    )
    actor = ue.GameplayStatics.begin_deferred_actor_spawn_from_class(
        cls,
        transform,
        ue.ESpawnActorCollisionHandlingMethod.AlwaysSpawn,
        world_context_object=ue.get_world(),
    )
    if actor is None:
        raise RuntimeError(f"could not spawn {cls.__name__}")
    ue.GameplayStatics.finish_spawning_actor(actor, transform)
    return cast(_A, actor)


@ue.uclass
class DoomHangarMode(LevelRuntime, ue.GameMode):
    """The simulation: runs on the server (or in the standalone game) and nowhere else."""

    default_pawn_class = player_mod.DoomMarine
    player_controller_class = player_mod.DoomController
    player_state_class = state.DoomPlayerState
    game_state_class = state.DoomGameState
    hud_class = hud.DoomHUD
    # Explicit native references also preserve the assets across serialized class replacements.
    loaded: list[ue.Object] = ue.uproperty(default_factory=list, transient=True)
    music = ue.component(DoomMusic)

    def post_init(self) -> None:
        # The engine may tick the mode (and other actors may query it) before begin_play has loaded
        # the map, e.g. when this class is merely discovered while a non-Doom map is running.
        self.loaded_map = False
        self.positioned = False
        self.menu = "main"
        self.networked = False
        self.advance_timer = self.ending_timer = 0.0
        self.published: dict[str, Any] = {}

    def end_play(self, end_play_reason: ue.EEndPlayReason) -> None:
        clear_cache()

    def begin_play(self) -> None:
        clear_cache()
        net.invalidate()
        manifest = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))
        self.networked = net.networked()
        self.init_common()
        self.init_counters()
        console.initialize(self)
        self.maps = manifest["maps"]
        options = net.host_options(net.game_options()) if self.networked else net.HostOptions()
        start = options.map
        if start not in self.maps:
            ue.log(f"Doom: unknown map {start!r}: E1M1", "warning")
            start = "E1M1"
        self.match_name, self.fraglimit, self.timelimit = options.match, options.fraglimit, options.timelimit
        self.with_monsters = options.monsters
        self.item_respawn_seconds = ITEM_RESPAWN_SECONDS
        self.respawn_queue: list[tuple[float, Any]] = []
        self.marker, self.skill = start, 3
        self.selected_episode, self.selected_map, self.selected_skill = 1, 1, 3
        # The multiplayer screen's choices (episode and map are the setup screen's).
        self.host_match, self.host_monsters, self.host_fraglimit, self.host_timelimit = "coop", True, 0, 0
        self.join_address, self.typing_address = "127.0.0.1", False
        self.menu, self.menu_row = ("" if self.networked else "main"), 0
        self.started, self.finished_episode, self.secret_exit = self.networked, False, False
        self.load_data(start)
        for key in self.data["sprites"]:
            self.texture(key, True)
        self.last_xy = None
        self.testing, self.positioned = False, False
        self.build()
        self.restart()
        if not self.networked:
            self.music.play("D_INTRO.mid")  # the title screen's score; a co-op game starts in the level
        lighting.start(self)
        self.loaded_map = True
        ue.log(f"Ultimate Doom ready: {len(self.maps)} maps")

    # -- the players ---------------------------------------------------------------------------------------

    def players(self) -> list[state.DoomPlayerState]:
        return net.players()

    def resolve(self, who: Any) -> state.DoomPlayerState | None:
        """The player state of a marine, of a player state, or (None) of the player at this machine."""
        if isinstance(who, state.DoomPlayerState):
            return who
        if isinstance(who, player_mod.DoomMarine):
            return who.doom_state
        return cast("state.DoomPlayerState | None", self.primary())

    def closest_player(self, actor: ue.Actor, alive_only: bool = True) -> player_mod.DoomMarine | None:
        """The marine nearest to `actor` (a living one when any is)."""
        x, y = xy(actor)
        best: player_mod.DoomMarine | None = None
        best_distance = math.inf
        marines = self.marines()
        for pass_alive in (True, False):
            for marine in marines:
                ps = marine.doom_state
                if pass_alive and alive_only and ps is not None and ps.dead:
                    continue
                mx, my = xy(marine)
                distance = math.hypot(mx - x, my - y)
                if distance < best_distance:
                    best, best_distance = marine, distance
            if best is not None or not alive_only:
                break
        return best

    def start_thing(self, ps: state.DoomPlayerState) -> tuple[float, float, float]:
        """Where player `ps` starts: its Doom player start (1-4); a fifth player shares the first."""
        wanted = ps.start_index + 1
        starts = {t[3]: t for t in self.data["things"] if t[3] in (1, 2, 3, 4)}
        x, y, angle, _, _ = starts.get(wanted) or starts[1]
        return float(x), float(y), float(angle)

    def deathmatch_starts(self) -> list[tuple[float, float, float]]:
        """The map's deathmatch starts (thing 11, the first ten); a map without any uses its player starts."""
        things = self.data["things"]
        starts = [t for t in things if t[3] == 11][:MAX_DEATHMATCH_STARTS]
        starts = starts or [t for t in things if t[3] in (1, 2, 3, 4)]
        return [(float(t[0]), float(t[1]), float(t[2])) for t in starts]

    def occupants(self, x: float, y: float, ignore: ue.Actor | None) -> list[ue.Actor]:
        """The living marines and monsters whose bodies overlap a marine standing at (x, y)."""
        found: list[ue.Actor] = []
        for marine in self.marines():
            ps = marine.doom_state
            if marine is ignore or ps is None or ps.dead or not ps.placed:
                continue
            mx, my = xy(marine)
            if abs(mx - x) < 32 and abs(my - y) < 32:
                found.append(marine)
        for enemy in self.enemies:
            if not enemy.is_valid() or enemy.dead:
                continue
            info = MONSTER_INFO.get(enemy.type_id)
            ex, ey = xy(enemy)
            reach = 16 + (info.radius if info is not None and info.radius else 20)
            if abs(ex - x) < reach and abs(ey - y) < reach:
                found.append(enemy)
        return found

    def spawn_spot(self, ps: state.DoomPlayerState) -> tuple[float, float, float]:
        """Where `ps` (re)starts: its player start in co-op; in a deathmatch a random free deathmatch start.

        It tries SPAWN_TRIES random starts for an unoccupied one. When there is none
        the marine arrives on a random start anyway and telefrags whoever stands there.
        """
        if not self.match.random_spawns:
            return self.start_thing(ps)
        starts = self.deathmatch_starts()
        marine = ps.get_pawn()
        for _ in range(SPAWN_TRIES):
            x, y, angle = random.choice(starts)
            if not self.occupants(x, y, marine):
                return x, y, angle
        x, y, angle = random.choice(starts)
        for victim in self.occupants(x, y, marine):
            if isinstance(victim, player_mod.DoomMarine):
                self.hurt(10000, who=victim, source=marine)
            else:
                cast(Any, victim).hurt(10000, source=marine)
        return x, y, angle

    def warp(self, marine: player_mod.DoomMarine, x: float, y: float, angle: float) -> None:
        """Put a marine at map position (x, y) facing `angle` (map degrees), and tell its owner's screen."""
        location = vec(x, y, self.floor(x, y) + 29)
        marine.set_actor_location(location, False, True)
        marine.character_movement.stop_movement_immediately()
        marine.character_movement.set_movement_mode(ue.EMovementMode.MOVE_Walking)
        controller = marine.get_controller()
        if isinstance(controller, player_mod.DoomController):
            controller.yaw = -float(angle)
            controller.set_control_rotation(ue.Rotator(0, -angle, 0))
            controller.owner_warp(x * SCALE, -y * SCALE, (self.floor(x, y) + 29) * SCALE, -float(angle))

    def place(self, ps: state.DoomPlayerState) -> bool:
        """Put the player's marine at its start; False while the marine or its controller is missing."""
        marine = ps.get_pawn()
        if not isinstance(marine, player_mod.DoomMarine) or not isinstance(
            marine.get_controller(), player_mod.DoomController
        ):
            return False
        if not ps.placed:
            taken = {p.start_index for p in self.players() if p is not ps and p.placed}
            ps.start_index = next(i for i in range(net.MAX_PLAYERS) if i not in taken)
            net.invalidate()
        x, y, angle = self.spawn_spot(ps)
        self.warp(marine, x, y, angle)
        ps.placed = True
        ps.last_xy = None
        return True

    def position(self) -> None:
        """(Re)start every player at its start."""
        for ps in self.players():
            ps.placed = False
        self.place_players()

    def place_players(self) -> None:
        """Place the players that have a marine and are not placed yet (joiners included)."""
        players = self.players()
        for ps in players:
            if not ps.placed:
                self.place(ps)
        self.positioned = bool(players) and all(ps.placed for ps in players)

    def respawn(self, ps: state.DoomPlayerState) -> None:
        """Rebirth: back at a start with the pistol, 50 bullets and no keys."""
        marine = ps.get_pawn()
        ps.reset(self.skill)
        if isinstance(marine, player_mod.DoomMarine):
            x, y, angle = self.spawn_spot(ps)
            self.effect("teleport", marine.get_actor_location().copy())
            self.warp(marine, x, y, angle)
            self.effect("teleport", vec(x, y, self.floor(x, y)))
            self.sound("DSTELEPT", at=marine.get_actor_location())
        ps.placed = True
        ps.notify("YOU ARE BACK", 2.0)

    # -- the level -------------------------------------------------------------------------------------------

    def spawn_things(self) -> None:
        self.enemies = []
        self.sound_targets: dict[int, ue.Actor] = {}
        self.total_items = 0
        for thing_id, (x, y, angle, kind, flags) in enumerate(self.data["things"]):
            multiplayer_only = bool(flags & 16)
            if not flags & skill_flag(self.skill) or (multiplayer_only and not self.networked):
                continue
            if kind in (1, 2, 3, 4, 11):
                continue
            floor = self.floor(x, y)
            if kind in DEMONS:
                if not self.with_monsters:
                    continue  # -nomonsters
                enemy = spawn_thing(monsters.DoomDemon, vec(x, y, floor + 29), ue.Rotator(0, -angle, 0))
                enemy.prefix, enemy.health, enemy.attack_sound = DEMONS[kind]
                enemy.facing = float(angle)
                enemy.type_id, enemy.thing_id = kind, thing_id
                enemy.spawn_x, enemy.spawn_y, enemy.spawn_z = x, y, floor + 29
                enemy.spawn_health = enemy.health
                if kind in (3005, 3006):
                    enemy.character_movement.set_movement_mode(ue.EMovementMode.MOVE_Flying)
                enemy.flags, enemy.ambush = flags, bool(flags & 8)
                enemy.reactiontime = MONSTER_INFO[kind].reactiontime
                enemy.character_movement.max_walk_speed = monsters.walk_speed(kind, self.skill == 5)
                enemy.character_movement.max_fly_speed = enemy.character_movement.max_walk_speed
                enemy.image(enemy.prefix + "A1")
                self.enemies.append(enemy)
                self.objects.append(enemy)
            elif kind == 2035:
                barrel = spawn_thing(world.DoomBarrel, vec(x, y, floor + 21))
                barrel.thing_id = thing_id
                barrel.image("BAR1A0")
                self.objects.append(barrel)
            else:
                key = ITEMS.get(kind, DECOR.get(kind))
                if key is None or key not in self.data["sprites"]:
                    continue
                item = spawn_thing(world.DoomSprite, vec(x, y, floor))
                item.kind, item.thing_id = kind, thing_id
                item.image(key)
                self.objects.append(item)
                if kind in COUNT_ITEMS:
                    self.total_items += 1
        self.total = len(self.enemies)

    def restart(self) -> None:
        for obj in self.objects:
            if obj.is_valid():
                obj.destroy_actor()
        self.objects = []
        self.respawn_queue = []
        for ps in self.players():
            ps.reset(self.skill)
            ps.reset_stats()
        self.switches = set()
        self.switch_timers = {}
        self.animation_frame = -1
        for materials in self.button_materials.values():
            for mat, key in materials:
                mat.set_texture_parameter_value("DoomTexture", self.texture(key))
        self.secret_exit = False
        self.elapsed = self.level_clock = 0.0
        self.notice = map_heading(self.marker).upper()
        self.notice_timer = 4.0
        self.show_map = self.won = False
        self.advance_timer = 0.0
        self.kills = self.item_count = 0
        self.secrets = set()
        for door in self.doors.values():
            door["height"], door["timer"], door["opened"] = 0.0, 0.0, False
            door["closed"], door["reopen"] = 0.0, False
            if door["actor"]:
                door["actor"].set_actor_location(ue.Vector(0, 0, 0), False, True)
        for mover in self.movers.values():
            mover["offset"] = mover["goal"] = mover["wait"] = 0.0
            mover["active"] = False
            if mover["actor"]:
                mover["actor"].set_actor_location(ue.Vector(0, 0, 0), False, True)
        for ceiling in self.ceilings.values():
            ceiling.update(offset=0.0, goal=0.0, active=False)
            if ceiling["actor"]:
                ceiling["actor"].set_actor_location(ue.Vector(0, 0, 0), False, True)
        geometry.refresh(self)
        self.triggered = set()
        self.last_xy = None
        self.spawn_things()
        self.positioned = False
        self.position()
        self.music.play(music_name(self.marker))

    # -- what the players do ---------------------------------------------------------------------------------

    def pickup(self, kind: int, dropped: bool = False, who: Any = None) -> bool:
        ps = self.resolve(who)
        return ps is not None and ps.pickup(kind, dropped)

    def hurt(self, damage: int, who: Any = None, source: Any = None, environment: bool = False) -> None:
        """Hurt a marine. `source` is who did it (a marine's frag); `environment` is the level (-1 frag)."""
        ps = self.resolve(who)
        if ps is not None:
            ps.hurt(damage, source, environment)

    def score_frag(self, victim: state.DoomPlayerState, source: Any, environment: bool) -> None:
        """A marine died: its killer gets +1, and a suicide (itself or the level) -1.

        Vanilla counts frags in every network game (co-op included, where the intermission shows them);
        only the deathmatch shows them in the status bar and ends the level on them.
        """
        if not self.networked:
            return
        if isinstance(source, player_mod.DoomMarine):
            killer = source.doom_state
        elif environment:
            killer = victim
        else:
            return  # a monster's kill is nobody's frag
        if killer is not None and killer.is_valid():
            killer.add_frag(int(victim.start_index))
            if self.match.count_frags:
                killer.notify(f"FRAGS {int(killer.frags)}", 1.5)

    def item_taken(self, item: Any) -> None:
        """Altdeath: a taken item returns after 30 seconds in a fog (not the spheres or a drop)."""
        if self.match.item_respawn and not item.dropped and item.kind not in NO_RESPAWN_ITEMS:
            self.respawn_queue.append((self.elapsed + self.item_respawn_seconds, item))

    def respawn_items(self) -> None:
        """Put back the items whose time came (altdeath)."""
        if not self.respawn_queue:
            return
        waiting: list[tuple[float, Any]] = []
        for due, item in self.respawn_queue:
            if not item.is_valid():
                continue
            if due > self.elapsed:
                waiting.append((due, item))
                continue
            where = item.get_actor_location().copy()
            self.effect("item_fog", where)
            self.sound("DSITMBK", at=where)
            item.taken = False
            item.set_actor_hidden_in_game(False)
            item.arm()
        self.respawn_queue = waiting

    def fire(self, who: Any = None) -> None:
        ps = self.resolve(who)
        if ps is None:
            return
        refire_tics = WEAPON_REFIRE.get(ps.weapon)
        refire = (
            refire_tics is not None and ps.weapon_action == ps.weapon and ps.weapon_clock >= refire_tics * TIC
        )
        if (ps.cooldown > 0 and not refire) or ps.dead or self.won or self.paused:
            return
        player = ps.get_pawn()
        if not isinstance(player, player_mod.DoomMarine):
            return
        weapon = WEAPONS[ps.weapon]
        ammo, cost = weapon["ammo"], weapon["cost"]
        if ammo and getattr(ps, ammo) < cost:
            ps.weapon = next(
                (
                    w
                    for w in ("plasma", "chaingun", "shotgun", "pistol", "chainsaw", "fist")
                    if w in ps.weapons
                    and (not WEAPONS[w]["ammo"] or getattr(ps, WEAPONS[w]["ammo"]) >= WEAPONS[w]["cost"])
                ),
                "fist",
            )
            ps.cooldown = 0.3
            return
        ps.cooldown = weapon_time(ps.weapon)
        ps.weapon_action = ps.weapon
        ps.weapon_clock = 0.0
        ps.weapon_event = 0
        ps.flash_variant = random.randrange(2)
        ps.fired_weapon = ps.weapon
        ps.fire_serial += 1
        self.noise_alert(player)  # every weapon makes noise, fist and chainsaw included
        if ps.weapon == "bfg":
            self.sound(weapon["sound"], at=player.get_actor_location())
        self.weapon_events(ps)

    def weapon_events(self, who: Any = None) -> None:
        ps = self.resolve(who)
        if ps is None or not ps.weapon_action or ps.dead or self.won:
            return
        if ps.weapon_action != ps.weapon:
            ps.weapon_action = ""
            return
        events = WEAPON_EVENTS[ps.weapon_action]
        while ps.weapon_event < len(events) and ps.weapon_clock >= events[ps.weapon_event] * TIC:
            ps.weapon_event += 1
            self.weapon_shot(ps)

    def weapon_shot(self, who: Any = None) -> None:
        ps = self.resolve(who)
        if ps is None:
            return
        player = ps.get_pawn()
        if not isinstance(player, player_mod.DoomMarine):
            return
        weapon = WEAPONS[ps.weapon_action]
        ammo, cost = weapon["ammo"], weapon["cost"]
        if ammo:
            if getattr(ps, ammo) < cost:
                return
            setattr(ps, ammo, getattr(ps, ammo) - cost)
        start = player.camera.get_world_location().copy()
        if ps.weapon_action != "bfg":
            self.sound(weapon["sound"], at=start)
        if ps.aim is not None and not player.is_locally_controlled():
            # A remote player aims on its own screen and sends the direction.
            direction = player.camera.get_forward_vector().copy()
            direction[0], direction[1], direction[2] = ps.aim
        else:
            direction = self.aim_direction(player, ps.weapon_action)
        if lighting.active():
            lighting.muzzle(self, ps.weapon_action, start, direction)
        if "projectile" in weapon:
            bolt = ue.spawn_actor(projectiles.DoomProjectile, location=start + direction * 32)
            bolt.configure(
                direction,
                player,
                weapon["projectile"],
                weapon["speed"],
                weapon["damage"],
                weapon["radius"],
                ps.weapon,
            )
            self.objects.append(bolt)
        else:
            yaw = math.atan2(float(direction[1]), float(direction[0]))
            horizontal = math.hypot(float(direction[0]), float(direction[1]))
            for pellet in range(weapon["pellets"]):
                spread = (pellet - 3) * 0.01 if ps.weapon == "shotgun" else 0.0
                end = start.copy()
                end[0] += math.cos(yaw + spread) * horizontal * weapon["length"]
                end[1] += math.sin(yaw + spread) * horizontal * weapon["length"]
                end[2] += float(direction[2]) * weapon["length"]
                hit, result = ray(start, end, [player])
                rival = (
                    isinstance(hit, player_mod.DoomMarine)
                    and self.networked
                    and hit.doom_state is not None
                    and not hit.doom_state.dead
                )
                if rival or isinstance(hit, (monsters.DoomDemon, world.DoomBarrel)):
                    if rival or isinstance(hit, monsters.DoomDemon):
                        self.effect("blood", ue.Vector(*result[2]))
                    damage = random.randint(1, 3) * 5
                    if ps.weapon in ("fist", "chainsaw"):
                        damage = random.randint(1, 10) * 2 * (10 if ps.berserk and ps.weapon == "fist" else 1)
                    if isinstance(hit, player_mod.DoomMarine):
                        self.hurt(damage, who=hit, source=player)
                    else:
                        hit.hurt(damage, source=player)
                elif hit:
                    point = result[2]
                    self.effect("puff", ue.Vector(*point))
                    self.shoot_switch(point, player)

    def move_floors(self, delta_seconds: float) -> None:
        specials.tick(self, delta_seconds)
        geometry.refresh_changed(self)

    def trigger(self, index: int, who: Any = None) -> None:
        specials.activate(self, index, "walk", who)

    def cross_lines(self, start: tuple[float, float], end: tuple[float, float], who: Any = None) -> None:
        if start == end:
            return
        vertices = self.data["vertices"]
        for index, line in enumerate(self.data["lines"]):
            if line["special"] not in specials.WALK:
                continue
            a, b = vertices[line["a"]], vertices[line["b"]]
            if segments_cross(start, end, a, b):
                if line["special"] in (39, 97, 125, 126):
                    # Enter from the front side; walking out must not teleport back.
                    dx, dy = b[0] - a[0], b[1] - a[1]
                    if dx * (start[1] - a[1]) - dy * (start[0] - a[0]) > 0:
                        continue
                    if specials.activate(self, index, "walk", who):
                        return  # The remaining segment belongs to the old position.
                else:
                    self.trigger(index, who)

    def blast(self, source: ue.Actor, radius: float, instigator: ue.Actor | None = None) -> None:
        """Doom radius damage: bounding-box distance, actor radius, and map-only occlusion."""
        x, y = xy(source)
        targets: list[ue.Actor] = [
            obj for obj in self.objects if isinstance(obj, (monsters.DoomDemon, world.DoomBarrel))
        ]
        targets.extend(self.marines())
        for target in targets:
            if target == source or not target.is_valid():
                continue
            if isinstance(target, monsters.DoomDemon) and target.prefix in monsters.SPLASH_IMMUNE:
                continue
            tx, ty = xy(target)
            target_radius = (
                10.0
                if isinstance(target, world.DoomBarrel)
                else cast(ue.Character, target).capsule_component.get_scaled_capsule_radius() / SCALE
            )
            distance = max(abs(tx - x), abs(ty - y)) - target_radius
            damage = int(radius - max(0.0, distance))
            if damage <= 0:
                continue
            # Doom's sight test uses the map: another monster or barrel cannot shield a target.
            ignore = [source, *(obj for obj in targets if obj != target)]
            hit, _ = ray(source.get_actor_location().copy(), target.get_actor_location().copy(), ignore)
            if hit is not None and hit != target:
                continue
            if isinstance(target, player_mod.DoomMarine):
                self.hurt(damage, who=target, source=instigator)
            else:
                cast(Any, target).hurt(damage, source=instigator)

    def open_door(self, index: int) -> None:
        door = self.doors.get(index)
        if door:
            door["opened"] = True
            door["timer"] = 5.0
            self.sound("DSDOROPN")

    def use(self, who: Any = None, yaw: float | None = None) -> None:
        ps = self.resolve(who)
        player = ps.get_pawn() if ps is not None else None
        if ps is None or not isinstance(player, player_mod.DoomMarine) or ps.dead or self.won:
            return
        if yaw is None:
            controller = player.get_controller()
            assert controller is not None
            yaw = float(controller.get_control_rotation()[1])
        px, py = xy(player)
        yaw = -math.radians(yaw)
        choices = []
        for i, line in enumerate(self.data["lines"]):
            if not line["special"] or line["special"] in specials.WALK | specials.SHOOT | {
                48,
                65535,
            }:
                continue
            a, b = self.data["vertices"][line["a"]], self.data["vertices"][line["b"]]
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / max(1, dx * dx + dy * dy)))
            x, y = a[0] + t * dx, a[1] + t * dy
            dist = math.hypot(x - px, y - py)
            if dist < 70 and (x - px) * math.cos(yaw) + (y - py) * math.sin(yaw) > -4:
                choices.append((dist, i))
        if not choices or not specials.activate(self, min(choices)[1], "use", player):
            self.sound("DSNOWAY", who=ps)
        else:
            self.sound("DSSWTCHN", at=player.get_actor_location())

    def noise_graph(self) -> dict[int, list[tuple[int, int, bool]]]:
        """Sector -> (neighbour sector, line, blocks sound) for every two-sided line."""
        graph = self.sound_graph
        if graph is None:
            graph: dict[int, list[tuple[int, int, bool]]] = defaultdict(list)
            sides = self.data["sides"]
            for index, line in enumerate(self.data["lines"]):
                if line["left"] == 65535 or not line["flags"] & 4:
                    continue
                a, b = sides[line["right"]]["sector"], sides[line["left"]]["sector"]
                graph[a].append((b, index, bool(line["flags"] & 64)))
                graph[b].append((a, index, bool(line["flags"] & 64)))
            self.sound_graph = graph
        return graph

    def noise_alert(self, source: ue.Actor) -> None:
        """Wake the monsters that hear `source`: its sound spreads from sector to sector through open
        two-sided lines, and only one sound-blocking line may lie on the way."""
        graph, sides = self.noise_graph(), self.data["sides"]
        lines = self.data["lines"]
        seen = {self.sector_at(*xy(source)): 0}  # sector -> sound-blocking lines crossed to reach it
        stack = [(next(iter(seen)), 0)]
        while stack:
            sector, blocks = stack.pop()
            self.sound_targets[sector] = source
            for other, index, blocks_sound in graph[sector]:
                line = lines[index]
                front, back = sides[line["right"]]["sector"], sides[line["left"]]["sector"]
                opening = min(geometry.ceiling(self, front), geometry.ceiling(self, back)) - max(
                    self.sector_floor(front), self.sector_floor(back)
                )
                if opening <= 0:
                    continue
                if blocks_sound and blocks:
                    continue
                reached = blocks + (1 if blocks_sound else 0)
                if other in seen and seen[other] <= reached:
                    continue
                seen[other] = reached
                stack.append((other, reached))

    def shoot_switch(self, point: Any, who: Any = None) -> None:
        px, py = float(point[0]) / SCALE, -float(point[1]) / SCALE
        for i, line in enumerate(self.data["lines"]):
            if line["special"] not in specials.SHOOT:
                continue
            a, b = self.data["vertices"][line["a"]], self.data["vertices"][line["b"]]
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / max(1, dx * dx + dy * dy)))
            if math.hypot(a[0] + t * dx - px, a[1] + t * dy - py) < 4:
                specials.activate(self, i, "shoot", who)

    @override
    def build_portals(self) -> None:
        """Sector graph for the monsters' path search, built once per level from the two-sided linedefs."""
        # A monster fits through a line only if it is wider than its diameter; portal = line midpoint.
        narrowest = 2 * min((info.radius for info in MONSTER_INFO.values() if info.radius), default=16)
        vertices, sides = self.data["vertices"], self.data["sides"]
        portals: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
        for line in self.data["lines"]:
            if line["left"] == 65535 or line["right"] == 65535:
                continue
            front, back = int(sides[line["right"]]["sector"]), int(sides[line["left"]]["sector"])
            (ax, ay), (bx, by) = vertices[line["a"]][:2], vertices[line["b"]][:2]
            if front == back or math.hypot(bx - ax, by - ay) < narrowest:
                continue
            portals[front].append((back, (ax + bx) / 2, (ay + by) / 2))
            portals[back].append((front, (ax + bx) / 2, (ay + by) / 2))
        self.portals = portals
        self.route_version = -1
        self.route_cache: dict[tuple[int, int], list[tuple[float, float]] | None] = {}

    def portal_open(self, a: int, b: int) -> bool:
        """Can a monster walk between two adjacent sectors right now (live floors and ceilings)?"""
        floor_a, floor_b = self.sector_floor(a), self.sector_floor(b)
        if abs(floor_a - floor_b) > 24:
            return False
        return min(geometry.ceiling(self, a), geometry.ceiling(self, b)) - max(floor_a, floor_b) >= 56

    def route(self, start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
        """Portal points from start to end over the sector graph, then the goal; [] when unreachable."""
        # The graph search is only used by the Python enemy AI; level geometry stays exact.
        if self.route_version != self.geo_version:
            self.route_version = self.geo_version
            self.route_cache.clear()
        origin, goal = self.sector_at(*start), self.sector_at(*end)
        if origin == goal:
            return [end]
        key = (origin, goal)
        if key not in self.route_cache:
            self.route_cache[key] = self.search_portals(origin, goal, start, end)
        cached = self.route_cache[key]
        return [] if cached is None else [*cached, end]

    def search_portals(
        self, origin: int, goal: int, start: tuple[float, float], end: tuple[float, float]
    ) -> list[tuple[float, float]] | None:
        points: dict[int, tuple[float, float]] = {origin: start}
        costs, parents = {origin: 0.0}, dict[int, int]()
        queue = [(0.0, origin)]
        closed = set[int]()
        while queue:
            _, sector = heapq.heappop(queue)
            if sector in closed:
                continue
            closed.add(sector)
            if sector == goal:
                path: list[tuple[float, float]] = []
                while sector != origin:
                    path.append(points[sector])
                    sector = parents[sector]
                return path[::-1]
            px, py = points[sector]
            for other, x, y in self.portals.get(sector, ()):
                if other in closed or not self.portal_open(sector, other):
                    continue
                cost = costs[sector] + math.hypot(x - px, y - py)
                if cost < costs.get(other, math.inf):
                    costs[other], parents[other], points[other] = cost, sector, (x, y)
                    heapq.heappush(queue, (cost + math.hypot(end[0] - x, end[1] - y), other))
        return None

    # -- the frame ---------------------------------------------------------------------------------------

    def publish(self) -> None:
        """Mirror what clients need into the replicated game state (only what changed is sent)."""
        gs = self.game_state()
        if not isinstance(gs, state.DoomGameState) or not gs.has_authority():
            return
        values: dict[str, Any] = {
            "marker": self.marker,
            "level_serial": self.level_serial,
            "skill": self.skill,
            "kills": self.kills,
            "item_count": self.item_count,
            "total": self.total,
            "total_items": self.total_items,
            "secret_count": len(self.secrets),
            "won": self.won,
            "finished_episode": self.finished_episode,
            "match_name": self.match_name,
            "secret_exit": self.secret_exit,
            "switch_state": sorted(self.switches),
            "mover_state": geometry.mover_values(self),
        }
        for name, value in values.items():
            if self.published.get(name) != value:
                self.published[name] = value
                setattr(gs, name, value)
        if abs(self.elapsed - self.published.get("server_elapsed", -9.0)) >= 0.25 or (
            self.won and self.elapsed != self.published.get("server_elapsed")
        ):  # the intermission shows the exact time
            self.published["server_elapsed"] = self.elapsed
            gs.server_elapsed = self.elapsed

    def tick(self, delta_seconds: float) -> None:
        if not self.loaded_map:
            return
        net.invalidate()
        self.route_budget = ROUTE_BUDGET
        self.place_players()
        self.notice_timer = max(0.0, self.notice_timer - delta_seconds)
        if self.paused:
            return
        players = self.players()
        for ps in players:
            ps.sync()
            ps.advance(delta_seconds)
        self.update_view(delta_seconds)
        for ps in players:
            if ps.fire_held and (ps.weapon_action == "plasma" or not ps.is_local()):
                # With the trigger held the rifle fires again at its refire tic, before its cool-down frame
                # (and no frame waits for the next input).
                self.fire(ps)
            self.weapon_events(ps)
        if self.networked:
            playing = any(not ps.dead for ps in players)
        else:
            primary = self.primary()
            playing = primary is None or not primary.dead
        if playing and not self.won:
            self.elapsed += delta_seconds
        # leveltime: runs always (the time limit ends a level of dead marines too) and times the crushers.
        self.level_clock += delta_seconds
        self.crush_now = specials.hurt_tic(self, delta_seconds)
        if int(self.elapsed) != getattr(self, "cleanup_tick", -1):
            self.cleanup_tick = int(self.elapsed)
            self.objects = [obj for obj in self.objects if obj.is_valid()]
        campaign.tick_materials(self, delta_seconds)
        if lighting.active():
            lighting.tick(self, delta_seconds)
        for index, door in self.doors.items():
            target = door["target"] if door["opened"] else door["closed"]
            old = door["height"]
            delta = door["speed"] * delta_seconds
            door["height"] = min(target, old + delta) if target > old else max(target, old - delta)
            if door["height"] < old and specials.squeeze(
                self, index, float(self.data["sectors"][index]["ceiling"]) + door["height"], False
            ):
                door["height"] = old  # a thing in the way holds a closing door back...
                if not door.get("stays"):
                    door["opened"], door["timer"], door["reopen"] = True, 4.0, False  # ...and reopens it
                    self.sound("DSDOROPN")
            if old != door["height"]:
                self.geo_dirty.add(index)
            if door["actor"] and old != door["height"]:
                door["actor"].set_actor_location(ue.Vector(0, 0, door["height"] * SCALE), False, True)
            if door["height"] == target and door["opened"]:
                door["timer"] -= delta_seconds
                if door["timer"] <= 0:
                    door["opened"] = False
            elif door["height"] == target and door.get("reopen"):
                door["timer"] -= delta_seconds
                if door["timer"] <= 0:
                    door["opened"], door["timer"], door["reopen"] = True, math.inf, False
        self.move_floors(delta_seconds)
        for ps in players:
            player = ps.get_pawn()
            if not isinstance(player, player_mod.DoomMarine) or ps.dead or self.won:
                continue
            x, y = xy(player)
            if ps.last_xy is not None:
                self.cross_lines(ps.last_xy, (x, y), player)
                x, y = xy(player)  # A crossed teleporter may have relocated the pawn.
            ps.last_xy = (x, y)
            sector = self.sector_at(x, y)
            if self.data["sectors"][sector]["special"] == 9 and sector not in self.secrets:
                self.secrets.add(sector)  # the first marine in finds it: that marine gets the credit
                ps.secret_found += 1
            if self.data["sectors"][sector]["special"] in (4, 5, 7, 11, 16) and int(
                self.elapsed / 0.9
            ) != int((self.elapsed - delta_seconds) / 0.9):
                special = self.data["sectors"][sector]["special"]
                if ps.suit <= 0 or special == 11:
                    self.hurt(
                        20 if special in (4, 11, 16) else 10 if special == 5 else 5, who=ps, environment=True
                    )
                if special == 11 and ps.health <= 10:
                    campaign.finish_level(self)
        if self.networked:
            self.respawn_items()
            self.network_rules(players, delta_seconds)
        self.publish()

    def network_rules(self, players: list[state.DoomPlayerState], delta_seconds: float) -> None:
        """Network rules: the dead are reborn; an exit, or a deathmatch limit, moves everyone on."""
        if self.match.count_frags and not self.won:
            top = max((int(ps.frags) for ps in players), default=0)
            if (self.fraglimit and top >= self.fraglimit) or (
                self.timelimit and self.level_clock >= self.timelimit * 60
            ):
                campaign.finish_level(self)
        for ps in players:
            if ps.dead and not self.won:
                ps.respawn_timer -= delta_seconds
                if ps.respawn_timer <= 0:
                    self.respawn(ps)
        if self.finished_episode:
            self.ending_timer -= delta_seconds
            if self.ending_timer <= 0:
                campaign.next_episode(self)
        elif self.won:
            self.advance_timer = self.advance_timer or ADVANCE_DELAY
            self.advance_timer -= delta_seconds
            if self.advance_timer <= 0:
                self.advance_timer = 0.0
                campaign.advance(self)

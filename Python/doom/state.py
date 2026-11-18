"""Replicated Doom state: what each player carries (`DoomPlayerState`) and what the level shows.

The game mode only exists on the server. Both classes (`DoomGameState` is the level's) exist on every machine
and replicate, so clients can draw the HUD and build the level from them. The server (or the standalone
game) owns and mutates all of it.
"""

from __future__ import annotations

import math
from typing import Any

from typing_extensions import override

import ue
from doom import campaign, geometry, lighting, monsters, projectiles, world
from doom.common import SCALE, clear_cache, mode_now, player_now, weapon_time
from doom.level import LevelRuntime
from doom.music import DoomMusic
from doom.net import NET_FREQUENCY
from doom.rules import (
    AMMO_PICKUPS,
    COUNT_ITEMS,
    KEY_PICKUPS,
    WEAPON_PICKUPS,
    WEAPONS,
    music_name,
)

WEAPON_ORDER = ("fist", "chainsaw", "pistol", "shotgun", "chaingun", "rocket", "plasma", "bfg")
KEY_COLOURS = ("blue", "yellow", "red")
POWERUPS = ("invulnerability", "invisibility", "suit", "light_visor")
RESPAWN_DELAY = 3.0  # seconds a dead co-op player waits before coming back


def _clock() -> float:
    mode = mode_now()
    return float(mode.elapsed) if mode is not None else 0.0


def _power(index: int) -> property:
    """A powerup's seconds left, kept as an expiry time on the level clock (nothing replicates per frame)."""

    def get(self: DoomPlayerState) -> float:
        return max(0.0, float(self.power_until[index]) - _clock())

    def put(self: DoomPlayerState, seconds: float) -> None:
        until = list(self.power_until)
        until[index] = _clock() + float(seconds) if seconds > 0 else 0.0
        self.power_until = until

    return property(get, put)


@ue.uclass
class DoomPlayerState(ue.PlayerState):
    """One marine's inventory. The server owns it; every client gets a replica (the owner's HUD reads it)."""

    health: int = ue.uproperty(100, replicated=True)
    armor: int = ue.uproperty(0, replicated=True)
    armor_type: int = ue.uproperty(1, replicated=True)
    bullets: int = ue.uproperty(50, replicated=True)
    shells: int = ue.uproperty(0, replicated=True)
    rockets: int = ue.uproperty(0, replicated=True)
    cells: int = ue.uproperty(0, replicated=True)
    weapon: str = ue.uproperty("pistol", replicated=True)
    weapon_bits: int = ue.uproperty(0, rep_notify="on_weapon_bits")
    key_kinds_rep: list[int] = ue.uproperty(default_factory=lambda: [0, 0, 0], rep_notify="on_keys")
    backpack: bool = ue.uproperty(False, replicated=True)
    berserk: bool = ue.uproperty(False, replicated=True)
    all_map: bool = ue.uproperty(False, replicated=True)
    dead: bool = ue.uproperty(False, replicated=True)
    god_mode: bool = ue.uproperty(False, replicated=True)
    kills: int = ue.uproperty(0, replicated=True)  # this level's score, credited to the marine that earned it
    items: int = ue.uproperty(0, replicated=True)
    secret_found: int = ue.uproperty(0, replicated=True)
    frags: int = ue.uproperty(0, replicated=True)  # 0 in co-op; deathmatch: kills of others minus suicides
    # Deathmatch: how often this marine killed each marine (by start index); its own entry is suicides.
    frag_table: list[int] = ue.uproperty(default_factory=lambda: [0, 0, 0, 0], replicated=True)
    noclip: bool = ue.uproperty(False, rep_notify="on_noclip")
    start_index: int = ue.uproperty(0, replicated=True)
    power_until: list[float] = ue.uproperty(default_factory=lambda: [0.0] * 4, replicated=True)
    fire_serial: int = ue.uproperty(0, rep_notify="on_fire")
    fired_weapon: str = ue.uproperty("pistol", replicated=True)
    flash_variant: int = ue.uproperty(0, replicated=True)
    pain_serial: int = ue.uproperty(0, rep_notify="on_pain")
    pickup_serial: int = ue.uproperty(0, rep_notify="on_pickup_flash")
    berserk_serial: int = ue.uproperty(0, rep_notify="on_berserk_flash")

    def post_init(self) -> None:
        self.weapons: set[str] = {"fist", "pistol"}
        self.keys: set[str] = set()
        self.key_kinds: dict[str, int] = {}
        self.cooldown = self.weapon_clock = 0.0
        self.weapon_action = ""
        self.weapon_event = 0
        self.fire_held = False
        self.aim: tuple[float, float, float] | None = None  # a remote client's aim, sent with its input
        self.pain = self.pickup_flash = self.berserk_flash = 0.0
        self.last_xy: tuple[float, float] | None = None
        self.respawn_timer = 0.0
        self.placed = False

    def begin_play(self) -> None:
        if self.has_authority():
            self.net_update_frequency = NET_FREQUENCY  # Unreal's default for player states is once a second

    invulnerability = _power(0)
    invisibility = _power(1)
    suit = _power(2)
    light_visor = _power(3)

    # -- replication callbacks (clients) ---------------------------------------------------------------------

    def on_weapon_bits(self) -> None:
        self.weapons = {name for i, name in enumerate(WEAPON_ORDER) if self.weapon_bits >> i & 1}

    def on_keys(self) -> None:
        kinds = list(self.key_kinds_rep)
        self.keys = {name for name, kind in zip(KEY_COLOURS, kinds, strict=False) if kind}
        self.key_kinds = {name: kind for name, kind in zip(KEY_COLOURS, kinds, strict=False) if kind}

    def on_fire(self) -> None:
        """The server fired this player's weapon: play the same animation here."""
        self.weapon_action = self.fired_weapon
        self.weapon_clock, self.weapon_event = 0.0, 0
        self.cooldown = weapon_time(self.fired_weapon)

    def on_pain(self) -> None:
        self.pain = 0.25

    def on_noclip(self) -> None:
        marine = self.get_pawn()
        apply = getattr(marine, "apply_noclip", None)
        if apply is not None:
            apply()

    def on_pickup_flash(self) -> None:
        self.pickup_flash = 0.3

    def on_berserk_flash(self) -> None:
        self.berserk_flash = 4.0

    # -- the owner's screen ----------------------------------------------------------------------------------

    def player_controller(self) -> Any:
        owner = self.get_owner()
        return owner if isinstance(owner, ue.PlayerController) else None

    def notify(self, text: str, seconds: float = 1.5) -> None:
        controller = self.player_controller()
        if controller is not None:
            controller.owner_notice(text, seconds)

    def hear(self, key: str, volume: float) -> None:
        controller = self.player_controller()
        if controller is not None:
            controller.owner_sound(key, volume)

    def is_local(self) -> bool:
        controller = self.player_controller()
        return controller is not None and bool(controller.is_local_controller())

    def advance(self, delta_seconds: float) -> None:
        """Local timers of the screen and the weapon animation."""
        self.cooldown = max(0.0, self.cooldown - delta_seconds)
        self.weapon_clock += delta_seconds
        for field in ("pain", "pickup_flash", "berserk_flash"):
            value = getattr(self, field)
            if value > 0:
                setattr(self, field, max(0.0, value - delta_seconds))

    def tick(self, delta_seconds: float) -> None:
        """A client's replica keeps its own timers; the server's copy is advanced by the game mode."""
        if not self.has_authority():
            self.advance(delta_seconds)

    # -- the server's side -----------------------------------------------------------------------------------

    def sync(self) -> None:
        """Encode the Python-side sets into their replicated forms (the server calls this every frame)."""
        bits = sum(1 << i for i, name in enumerate(WEAPON_ORDER) if name in self.weapons)
        if bits != self.weapon_bits:
            self.weapon_bits = bits
        kinds = [int(self.key_kinds.get(name, 0)) or (1 if name in self.keys else 0) for name in KEY_COLOURS]
        if kinds != list(self.key_kinds_rep):
            self.key_kinds_rep = kinds

    def reset_stats(self) -> None:
        """A new level starts the score again (a rebirth in the middle of a level keeps it)."""
        self.kills = self.items = self.secret_found = self.frags = 0
        self.frag_table = [0, 0, 0, 0]

    def add_frag(self, victim_index: int) -> None:
        """This marine killed the marine with start index `victim_index` (itself: a suicide, -1 frag)."""
        table = [int(n) for n in self.frag_table]
        table[victim_index % len(table)] += 1
        self.frag_table = table
        own = int(self.start_index) % len(table)
        self.frags = sum(n for i, n in enumerate(table) if i != own) - table[own]

    def reset(self, skill: int) -> None:
        """Doom's player start of a level: pistol, 50 bullets, 100 health."""
        self.health, self.armor, self.bullets, self.shells = 100, 0, 50, 0
        self.god_mode = False
        self.weapon = "pistol"
        self.rockets, self.cells, self.armor_type = 0, 0, 1
        self.keys, self.key_kinds = set(), {}
        self.backpack, self.berserk, self.all_map = False, False, False
        self.power_until = [0.0] * 4
        self.weapons = {"fist", "pistol"}
        self.cooldown = self.pain = 0.0
        self.pickup_flash = self.berserk_flash = 0.0
        self.weapon_action = ""
        self.weapon_clock = 0.0
        self.weapon_event = 0
        self.fire_held = False
        self.flash_variant = 0
        self.dead = False
        self.last_xy = None
        self.respawn_timer = 0.0
        self.sync()

    def flash(self, kind: str) -> None:
        """Tell the owner's screen: the counters replicate, the host's own screen reads the fields."""
        if kind == "pain":
            self.pain = 0.25
            self.pain_serial += 1
        elif kind == "pickup":
            self.pickup_flash = 0.3
            self.pickup_serial += 1
        elif kind == "berserk":
            self.berserk_flash = 4.0
            self.berserk_serial += 1

    def pickup(self, kind: int, dropped: bool = False) -> bool:
        from doom.common import ITEMS
        from doom.net import networked

        mode = mode_now()
        assert mode is not None
        netgame = networked()
        stay = netgame and mode.match.weapons_stay
        multiplier = 2 if mode.skill in (1, 5) else 1
        if kind in KEY_PICKUPS:
            colour = KEY_PICKUPS[kind]
            if netgame and colour in self.keys:
                return False
            self.keys.add(colour)
            self.key_kinds[colour] = kind
        elif kind in WEAPON_PICKUPS:
            weapon = WEAPON_PICKUPS[kind]
            ammo = WEAPONS[weapon]["ammo"]
            new_weapon = weapon not in self.weapons
            if stay and not dropped and not new_weapon:
                return False  # Weapons that stay on the floor: each marine takes one, once per life.
            if not new_weapon and (not ammo or getattr(self, ammo) >= campaign.ammo_limit(self, ammo)):
                return False
            self.weapons.add(weapon)
            if new_weapon:
                self.weapon = weapon
            if ammo:
                clips = 1 if dropped else mode.match.stay_clips if stay else 2
                amount = {"bullets": 10, "shells": 4, "rockets": 1, "cells": 20}[ammo]
                amount *= clips * multiplier
                setattr(self, ammo, min(campaign.ammo_limit(self, ammo), getattr(self, ammo) + amount))
        elif kind in AMMO_PICKUPS:
            ammo, amount = AMMO_PICKUPS[kind]
            if kind == 2007 and dropped:
                amount //= 2
            if getattr(self, ammo) >= campaign.ammo_limit(self, ammo):
                return False
            setattr(
                self,
                ammo,
                min(campaign.ammo_limit(self, ammo), getattr(self, ammo) + amount * multiplier),
            )
        elif kind == 8:
            self.backpack = True
            for ammo, amount in (("bullets", 10), ("shells", 4), ("rockets", 1), ("cells", 20)):
                setattr(
                    self,
                    ammo,
                    min(campaign.ammo_limit(self, ammo), getattr(self, ammo) + amount * multiplier),
                )
        elif kind in (2011, 2012):
            if self.health >= 100:
                return False
            self.health = min(100, self.health + (10 if kind == 2011 else 25))
        elif kind == 2014:
            self.health = min(200, self.health + 1)
        elif kind == 2015:
            self.armor = min(200, self.armor + 1)
        elif kind in (2018, 2019):
            if self.armor >= (100 if kind == 2018 else 200):
                return False
            self.armor_type = 1 if kind == 2018 else 2
            self.armor = 100 * self.armor_type
        elif kind == 2013:
            self.health = min(200, self.health + 100)
        elif kind == 2023:
            self.health, self.berserk, self.weapon = max(100, self.health), True, "fist"
            self.flash("berserk")
        elif kind in (2022, 2024, 2025, 2045):
            field = {
                2022: "invulnerability",
                2024: "invisibility",
                2025: "suit",
                2045: "light_visor",
            }[kind]
            setattr(self, field, 30.0 if kind == 2022 else 60.0 if kind != 2045 else 120.0)
        elif kind == 2026:
            self.all_map = True
        else:
            return False
        if kind in COUNT_ITEMS:
            mode.item_count += 1
            self.items += 1
        self.pickup_audio = mode.sound("DSWPNUP" if kind in WEAPON_PICKUPS else "DSITEMUP", 1.0, who=self)
        self.notify("PICKED UP " + ITEMS.get(kind, "ITEM"), 1.5)
        self.flash("pickup")
        return True

    def hurt(self, damage: int, source: Any = None, environment: bool = False) -> None:
        """Damage from `source` (a marine, a monster...); `environment` for the level (nukage, crushers).

        In a deathmatch the marine that brings this one to 0 health gets a frag; the level, or the marine
        itself, costs one. Telefrags (10000) go through invulnerability and god mode.
        """
        mode = mode_now()
        assert mode is not None
        if self.dead or mode.won:
            return
        if (self.invulnerability > 0 or self.god_mode) and damage < 1000:
            return
        if mode.skill == 1:
            damage = max(1, damage // 2)
        absorb = min(self.armor, damage // (2 if self.armor_type == 2 else 3))
        self.armor -= absorb
        self.health = max(0, self.health - damage + absorb)
        self.flash("pain")
        pawn = self.get_pawn()
        at = pawn.get_actor_location() if pawn is not None else None
        mode.sound("DSPLPAIN", at=at)
        if self.health == 0:
            self.dead = True
            self.respawn_timer = RESPAWN_DELAY
            mode.sound("DSPLDETH", at=at)
            mode.score_frag(self, source, environment)
            from doom.net import networked

            if not networked():
                mode.music.stop()


@ue.uclass
class DoomGameState(LevelRuntime, ue.GameState):
    """What every machine needs to show the level: which map, the moving sectors, the switches, the totals.

    On the server the game mode writes it each frame; on a client it builds the level from the replicated
    map and applies the moving sectors to its own native geometry.
    """

    loaded: list[ue.Object] = ue.uproperty(default_factory=list, transient=True)
    music = ue.component(DoomMusic)
    marker: str = ue.uproperty("", rep_notify="on_level")
    level_serial: int = ue.uproperty(0, rep_notify="on_level")
    skill: int = ue.uproperty(3, replicated=True)
    mover_state: list[float] = ue.uproperty(default_factory=list, rep_notify="on_movers")
    switch_state: list[int] = ue.uproperty(default_factory=list, rep_notify="on_switches")
    kills: int = ue.uproperty(0, replicated=True)
    item_count: int = ue.uproperty(0, replicated=True)
    total: int = ue.uproperty(0, replicated=True)
    total_items: int = ue.uproperty(0, replicated=True)
    secret_count: int = ue.uproperty(0, replicated=True)
    won: bool = ue.uproperty(False, replicated=True)
    finished_episode: bool = ue.uproperty(False, replicated=True)
    match_name: str = ue.uproperty("coop", replicated=True)
    secret_exit: bool = ue.uproperty(False, replicated=True)
    server_elapsed: float = ue.uproperty(0.0, replicated=True)

    def post_init(self) -> None:
        self.init_common()
        self.networked = True
        self.menu = ""
        self.started = True
        self.testing = False
        self.positioned = True
        self.ready = False
        self.built = (-1, "")
        self.synced = False
        self.intermission_music = self.ending_music = False
        self.local_switches: set[int] = set()
        self.maps: list[str] = []
        self.things_scan = -9.0
        self.thing_actors: list[Any] = []

    @property
    def loaded_map(self) -> bool:
        return self.ready

    @property
    @override
    def secrets(self) -> set[int]:
        return set(range(self.secret_count))

    @secrets.setter
    @override
    def secrets(self, _value: Any) -> None:  # the server's set lives on the game mode
        return

    def begin_play(self) -> None:
        if self.has_authority():
            self.net_update_frequency = NET_FREQUENCY
        else:
            lighting.start(self)  # a client's screen settings and lighting; the server's mode did its own

    def end_play(self, end_play_reason: ue.EEndPlayReason) -> None:
        clear_cache()

    @override
    def things(self) -> list[Any]:
        """A client has no object list: the replicated things in the world (rescanned twice a second)."""
        if self.elapsed - self.things_scan >= 0.5 or self.elapsed < self.things_scan:
            self.things_scan = self.elapsed
            self.thing_actors = [
                actor
                for cls in (
                    world.DoomSprite,
                    world.DoomBarrel,
                    monsters.DoomDemon,
                    projectiles.DoomProjectile,
                )
                for actor in ue.GameplayStatics.get_all_actors_of_class(cls)
                if actor is not None and actor.is_valid()
            ]
        return self.thing_actors

    # -- level on a client -----------------------------------------------------------------------------------

    def on_level(self) -> None:
        self.synced = False  # tick() rebuilds as soon as both the map and its serial arrived

    def rebuild(self) -> None:
        self.ready = False
        self.clear_level()
        self.switches, self.local_switches = set(), set()
        self.switch_timers = {}
        self.load_data(self.marker)
        self.build()
        self.ready = True
        self.built = (self.level_serial, self.marker)
        self.intermission_music = self.ending_music = False
        self.music.play(music_name(self.marker))  # music is local: each machine plays its own
        self.on_movers()
        self.on_switches()
        for actor in ue.GameplayStatics.get_all_actors_of_class(ue.Actor):
            apply = getattr(actor, "apply_replicated", None)
            if apply is not None:
                apply()

    def on_movers(self) -> None:
        """The moving sectors arrived: put the doors, floors and ceilings where the server has them."""
        if not self.ready:
            return
        values = list(self.mover_state)
        if not values:
            return
        order = geometry.mover_order(self)
        if len(values) != len(order):
            return
        for (kind, index), value in zip(order, values, strict=True):
            geometry.set_mover(self, kind, index, float(value))
        geometry.refresh_changed(self)

    def on_switches(self) -> None:
        if not self.ready:
            return
        wanted = {int(i) for i in self.switch_state}
        for index in wanted - self.local_switches:
            campaign.set_switch(self, index, False)
        for index in self.local_switches - wanted:
            for material, key in self.button_materials.get(index, []):
                material.set_texture_parameter_value("DoomTexture", self.texture(key))
        self.local_switches = wanted
        self.switches = set(wanted)

    def tick(self, delta_seconds: float) -> None:
        if self.has_authority():
            return  # the server's game mode drives everything; this is only its replicated mirror
        if self.marker and self.built != (self.level_serial, self.marker):
            self.rebuild()
        if not self.ready:
            return
        if not self.synced or abs(self.elapsed - self.server_elapsed) > 0.5:
            self.elapsed = float(self.server_elapsed)
            self.synced = True
        if self.won:
            self.elapsed = float(self.server_elapsed)  # the clock stops at the exit
        else:
            self.elapsed += delta_seconds
        self.notice_timer = max(0.0, self.notice_timer - delta_seconds)
        if self.finished_episode and not self.ending_music:
            self.ending_music = True
            self.music.play(campaign.ending_music(self.marker))
        elif self.won and not self.finished_episode and not self.intermission_music:
            self.intermission_music = True
            self.music.play("D_INTER.mid")
        campaign.tick_materials(self, delta_seconds, local=True)
        if lighting.active():
            lighting.tick(self, delta_seconds)
        self.update_view(delta_seconds)

    # -- multicast events ------------------------------------------------------------------------------------

    @ue.ufunction(multicast=True, reliable=False)
    def mc_sound(self, key: str, volume: float, x: float, y: float, z: float, positional: bool) -> None:
        """A one-shot sound, played on every machine; quieter the farther the listener is from `(x, y, z)`."""
        mode = mode_now()
        if mode is None or not getattr(mode, "ready", True):
            return
        if positional:
            listener = player_now()
            if listener is not None:
                p = listener.get_actor_location()
                distance = math.dist((float(p[0]), float(p[1]), float(p[2])), (x, y, z)) / SCALE
                volume *= max(0.0, min(1.0, 1.0 - (distance - 160.0) / 1040.0))
        if volume > 0.01:
            mode.play_sound(key, volume)

    @ue.ufunction(multicast=True, reliable=False)
    def mc_effect(self, name: str, x: float, y: float, z: float) -> None:
        mode = mode_now()
        if mode is None or not getattr(mode, "ready", True):
            return
        mode.spawn_effect(name, ue.Vector(x, y, z))


__all__ = ["DoomGameState", "DoomPlayerState", "WEAPON_ORDER"]

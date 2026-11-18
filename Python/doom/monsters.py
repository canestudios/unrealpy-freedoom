from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING

import ue
from doom import net, projectiles, specials, world
from doom import player as player_mod
from doom.animation import (
    ATTACK_FRAMES,
    DEATH_STATES,
    IDLE_STATES,
    PAIN,
    PAIN_FRAMES,
    WALK_STATES,
    state_frame,
)
from doom.common import ITEMS, SCALE, TIC, mode_now, player_now, ray, show_sprite, vec, xy
from doom.rules import MONSTER_INFO, MonsterInfo
from doom.visual import sprite_view, view_rotation

if TYPE_CHECKING:
    from doom.mode import DoomHangarMode

SARGS = (3002, 58)
SPLASH_IMMUNE = ("CYBR", "SPID")
BARONS = (3003, 69)  # Baron of Hell and Hell Knight share one species.

GRUDGE_SECONDS = 9.0  # how long a monster fights another monster that hurt it, deaf to other attackers
MELEE_GAP = 24  # map units between two bodies' edges within which a melee attack lands
CLOSE_SENSE = 64  # map units within which a sleeping monster notices a visible player even behind it
LEG_SECONDS = 1.6  # longest walk between two ranged-attack decisions (below Nightmare)
HESITATION_SPAN = 400  # map units beyond `eager` over which the chance to hold fire grows to its cap

# How readily each ranged attacker fires, by sprite prefix: (eager, cap). Within `eager` map units it always
# fires; farther away, the chance that it holds fire grows with the distance, up to `cap`. Long-range monsters
# are eager from farther away, and the Cyberdemon holds back least.
TEMPERAMENT: dict[str, tuple[int, float]] = {
    "POSS": (160, 0.8),
    "SPOS": (160, 0.8),
    "TROO": (64, 0.8),
    "HEAD": (160, 0.8),
    "SKUL": (320, 0.8),
    "BOSS": (64, 0.8),
    "CYBR": (320, 0.6),
    "SPID": (320, 0.8),
}


def chase_tics(kind: int, fast: bool) -> int:
    """Tics between two thinks of a hunting monster; on Nightmare the demons think twice as often."""
    tics = MONSTER_INFO[kind].chase_tics
    return max(1, tics >> 1) if fast and kind in SARGS else tics


def walk_speed(kind: int, fast: bool) -> float:
    """Unreal max speed for a monster that walks `speed` map units every think."""
    return MONSTER_INFO[kind].speed / chase_tics(kind, fast) / TIC * SCALE


def same_species(a: DoomDemon, b: DoomDemon) -> bool:
    return a.type_id == b.type_id or (a.type_id in BARONS and b.type_id in BARONS)


@ue.uclass
class DoomDemon(ue.Character):
    sprite = ue.component(ue.MaterialBillboardComponent, parent="capsule_component")
    # What clients need to draw it: which monster, which sprite frame, where it faces, whether it is dead.
    type_id: int = ue.uproperty(3004, replicated=True)
    pose: str = ue.uproperty("", rep_notify="on_pose")
    facing_rep: float = ue.uproperty(0.0, replicated=True)
    dead: bool = ue.uproperty(False, rep_notify="on_dead")

    @property
    def facing(self) -> float:
        """Where it looks, in map degrees (clients read the replicated copy)."""
        return self._facing if self.has_authority() else float(self.facing_rep)

    @facing.setter
    def facing(self, value: float) -> None:
        self._facing = float(value)
        if self.is_valid():
            self.facing_rep = self._facing

    def post_init(self) -> None:
        self._facing = 0.0
        self.prefix = "POSS"
        self.thing_id = -1
        self.spawn_x = self.spawn_y = self.spawn_z = 0.0
        self.spawn_health = 20
        self.health = 20
        self.attack_sound = "DSPISTOL"
        self.frame = ""
        self.view: tuple[str, int] = ("", 0)
        self.clock = 0.0
        self.flags = 0
        self.ambush = False  # Thing flag 8 ("deaf"): sound alone only wakes it when it can see the target.
        self.reactiontime = 8
        self.leg = (
            0.0  # seconds left of the current walk; a ranged attacker decides whether to fire when it ends
        )
        self.provoked = False  # hurt into pain: fires back at its next chance
        self.winded = False  # fired at its last think: the next one only walks
        self.chase_clock = random.random() * 4 * TIC  # Stagger the monsters' first think.
        self.look_clock = random.randint(1, 10) * TIC  # sleepers do not all look up on the same tic
        self.awake = False
        self.path = []
        self.path_timer = 0.0
        self.anim: list[tuple[str, int, bool]] = []
        self.anim_time = 0.0
        self.gibbed = False  # crushed corpse: POL5 (the pool of gibs), no longer in the way
        self.fired = False
        self.action_event = -1
        self.charge_time = 0.0
        self.charge_direction = [0.0, 0.0, 0.0]
        self.target: DoomDemon | None = None
        self.grudge = 0.0
        self.sprite.set_mobility(ue.EComponentMobility.Movable)
        self.sprite.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
        self.capsule_component.set_capsule_size(36, 56, True)
        self.capsule_component.set_collision_response_to_channel(
            ue.ECollisionChannel.ECC_Visibility, ue.ECollisionResponse.ECR_Block
        )
        movement = self.character_movement
        movement.run_physics_with_no_controller = True
        movement.set_movement_mode(ue.EMovementMode.MOVE_Walking)
        movement.max_walk_speed = 160
        movement.max_step_height = 48

    @property
    def info(self) -> MonsterInfo:
        return MONSTER_INFO.get(self.type_id) or MONSTER_INFO[3004]

    def begin_play(self) -> None:
        if net.networked() and self.has_authority():
            net.replicate(self, movement=True)
        self.apply_replicated()

    # -- replication ---------------------------------------------------------------------------------------

    def on_pose(self) -> None:
        self.apply_replicated()

    def on_dead(self) -> None:
        """A client's replica dies (or, for a Nightmare respawn, comes back) with the server's monster."""
        movement = self.character_movement
        if self.dead:
            movement.stop_movement_immediately()
            movement.set_movement_mode(ue.EMovementMode.MOVE_None)
            self.capsule_component.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
        else:
            self.capsule_component.set_collision_enabled(ue.ECollisionEnabled.QueryAndPhysics)
            movement.set_movement_mode(ue.EMovementMode.MOVE_Walking)

    def apply_replicated(self) -> None:
        if not self.has_authority():
            self.refresh_view()

    def image(self, key: str) -> None:
        """Show a frame (a Doom lump name; the server also tells the clients, through `pose`)."""
        stem = key[:5]
        if self.pose != stem:
            self.pose = stem
        self.refresh_view()

    def refresh_view(self) -> None:
        """Pick the rotation of the current frame as seen from the camera of this machine, and show it."""
        mode = mode_now()
        if mode is None or not mode.ready or not self.pose:
            return
        viewer = player_now()
        rotation = view_rotation(*xy(self), *xy(viewer), self.facing) if viewer else 1
        key = self.pose
        if self.frame and (key, rotation) == self.view:
            return
        self.view = (key, rotation)
        key, flipped = sprite_view(mode.data["sprites"], key[:5], rotation)
        if not key:
            return
        if key == self.frame and flipped == getattr(self, "flipped", False):
            return
        self.flipped = flipped
        self.frame = key
        show_sprite(self.sprite, mode, key, flipped, -56, fuzz=self.type_id == 58)

    def current_target(self) -> ue.Pawn | None:
        """The live monster this one is fighting, else the player."""
        target = self.target
        if target is not None and (not target.is_valid() or target.dead):
            self.target, self.grudge, target = None, 0.0, None
        mode = mode_now()
        return target or (mode.closest_player(self) if mode is not None else player_now())

    def retarget(self, source: ue.Actor | None) -> None:
        """Who it fights after `source` hurt it. A hurt from another monster starts a grudge: it turns on
        that monster for GRUDGE_SECONDS and ignores other attackers meanwhile. Outside a grudge, a hurt from a
        player sends it back after the players."""
        if self.grudge > 0 or source is None or source is self or not source.is_valid():
            return
        if isinstance(source, DoomDemon):
            if not source.dead:
                self.target, self.grudge = source, GRUDGE_SECONDS
        elif isinstance(source, player_mod.DoomMarine):
            self.target = None

    def hurt(self, damage: int, source: ue.Actor | None = None) -> None:
        if self.dead or not self.has_authority():
            return
        self.health -= damage
        self.awake = True
        if self.health > 0:
            self.retarget(source)
        if self.health <= 0:
            self.dead = True
            self.clock = 0
            self.character_movement.stop_movement_immediately()
            # Without collision a walking character would fall through the floor.
            self.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
            self.capsule_component.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
            mode = mode_now()
            if mode:
                mode.kills += 1
                if isinstance(source, player_mod.DoomMarine) and source.doom_state is not None:
                    source.doom_state.kills += 1
                specials.boss_death(mode, self)
                if self.type_id in (3004, 9):
                    x, y = xy(self)
                    drop = ue.spawn_actor(world.DoomSprite, location=vec(x, y, mode.floor(x, y)))
                    drop.kind = 2007 if self.type_id == 3004 else 2001
                    drop.dropped = True
                    drop.image(ITEMS[drop.kind])
                    mode.objects.append(drop)
                mode.sound("DSPODTH1" if self.prefix != "TROO" else "DSBGDTH1", at=self.get_actor_location())
        elif self.charge_time > 0:
            # A hit stops a charging skull; it is not in pain.
            self.charge_time = 0.0
            self.anim = []
        elif random.randrange(256) < self.info.painchance:  # painchance is out of 256
            self.provoked = True
            self.act(PAIN_FRAMES[self.prefix])
            mode = mode_now()
            if mode:
                mode.sound(PAIN[self.prefix], 0.5, at=self.get_actor_location())

    def nightmare_respawn(self, mode: DoomHangarMode) -> None:
        """Nightmare: the corpse vanishes in a teleport fog and the monster stands again at its spawn point.

        The same actor moves, so the clients see its `dead` flag and position change; the fog (both ends)
        and the sound are multicast like the other effects.
        """
        corpse = self.get_actor_location().copy()
        spawn = vec(self.spawn_x, self.spawn_y, self.spawn_z)
        self.health, self.dead, self.awake = self.spawn_health, False, False
        self.gibbed = False
        self.reactiontime, self.provoked, self.winded, self.leg = 18, False, False, 0.0
        self.grudge, self.target = 0.0, None
        self.anim, self.charge_time = [], 0.0
        self.set_actor_location(spawn, False, True)
        self.set_actor_hidden_in_game(False)  # a lost soul hides when its death animation ends
        self.capsule_component.set_collision_enabled(ue.ECollisionEnabled.QueryAndPhysics)
        self.character_movement.set_movement_mode(
            ue.EMovementMode.MOVE_Flying if self.type_id in (3005, 3006) else ue.EMovementMode.MOVE_Walking
        )
        self.clock = 0
        self.image(self.prefix + "A1")
        mode.effect("teleport", corpse)
        mode.effect("teleport", spawn)
        mode.sound("DSTELEPT", at=spawn)

    def gib(self) -> None:
        """A corpse that no longer fits under a ceiling becomes a pool of blood and gibs (POL5)."""
        if not self.dead or self.gibbed:
            return
        self.gibbed = True
        self.set_actor_hidden_in_game(False)
        self.image("POL5A0")
        mode = mode_now()
        if mode is not None:
            mode.sound("DSSLOP", at=self.get_actor_location())

    def act(self, frames: list[tuple[str, int, bool]]) -> None:
        """Play an action (attack, pain): the monster stands still until it ends."""
        self.anim, self.anim_time, self.fired = frames, 0.0, False
        self.action_event = -1
        self.charge_time = 0.0

    def tempo(self, mode: DoomHangarMode) -> float:
        return 2.0 if mode.skill == 5 and self.type_id in SARGS else 1.0

    def sees(self, target: ue.Actor) -> bool:
        hit, _ = ray(self.get_actor_location().copy(), target.get_actor_location().copy(), [self])
        return hit == target

    def in_reach(self, target: ue.Actor, visible: bool | None = None) -> bool:
        """Whether a melee attack would land: the bodies' edges within MELEE_GAP, and the target in sight."""
        target_radius = target.info.radius if isinstance(target, DoomDemon) else 16  # a marine's radius
        (x, y), (tx, ty) = xy(self), xy(target)
        if math.hypot(tx - x, ty - y) > self.info.radius + target_radius + MELEE_GAP:
            return False
        return self.sees(target) if visible is None else visible

    def decides_to_fire(
        self, target: ue.Actor, visible: bool | None = None, roll: float | None = None
    ) -> bool:
        """Whether a ranged attacker fires now (see TEMPERAMENT). It needs sight of the target; once
        provoked it answers at once; while it is still waking up (reactiontime) it holds. `visible` and `roll`
        (a random number from 0 to 1) can be forced."""
        if not (self.sees(target) if visible is None else visible):
            return False
        if self.provoked:
            self.provoked = False
            return True
        if self.reactiontime > 0:
            return False
        eager, cap = TEMPERAMENT.get(self.prefix, (160, 0.8))
        (x, y), (tx, ty) = xy(self), xy(target)
        hesitation = min(cap, max(0.0, math.hypot(tx - x, ty - y) - eager) / HESITATION_SPAN)
        return (random.random() if roll is None else roll) >= hesitation

    def look(self, mode: DoomHangarMode, player: ue.Pawn) -> bool:
        """Does this sleeper notice the player (a sound in its sector, or sight in its front 180 degrees)?"""
        ps = player.doom_state if isinstance(player, player_mod.DoomMarine) else None
        if ps is not None and ps.dead:
            return False
        x, y = xy(self)
        if mode.sound_targets.get(mode.sector_at(x, y)) is not None and (
            not self.ambush or self.sees(player)
        ):
            return True
        if not self.sees(player):
            return False
        px, py = xy(player)
        turn = (math.degrees(math.atan2(py - y, px - x)) - self.facing + 180) % 360 - 180
        return abs(turn) <= 90 or math.hypot(px - x, py - y) <= CLOSE_SENSE

    def attack_decision(self, mode: DoomHangarMode, target: ue.Pawn) -> None:
        (x, y), (tx, ty) = xy(self), xy(target)
        self.facing = math.degrees(math.atan2(ty - y, tx - x))
        self.act(ATTACK_FRAMES[self.prefix])
        self.play_action(0.0, mode, target)

    def new_leg(self) -> None:
        self.leg = random.uniform(0.0, LEG_SECONDS)
        self.path_timer = 0.0  # and a fresh route

    def think(self, mode: DoomHangarMode, player: ue.Pawn) -> bool:
        """A hunting monster's periodic decision: strike, fire or walk on. True when it attacks; the walking
        itself runs every frame in tick.

        A melee attacker strikes whenever its target is in reach. A ranged attacker considers firing when its
        walk leg ends (on Nightmare, at every think), and after firing it walks for a think before the next
        decision."""
        target = self.current_target() or player
        self.reactiontime = max(0, self.reactiontime - 1)
        (x, y), (tx, ty) = xy(self), xy(target)
        self.facing = math.degrees(math.atan2(ty - y, tx - x))
        fast = mode.skill == 5
        visible = self.sees(target)
        if self.winded:
            self.winded = False
            if not fast:
                self.new_leg()
        elif self.info.melee and self.in_reach(target, visible):
            self.attack_decision(mode, target)
            return True
        elif self.info.missile and (fast or self.leg <= 0) and self.decides_to_fire(target, visible):
            self.attack_decision(mode, target)
            self.winded = True
            return True
        if self.leg <= 0:
            self.new_leg()
        else:
            self.leg -= chase_tics(self.type_id, fast) * TIC
        if visible:
            self.path = []
        elif self.path_timer <= 0 and mode.route_budget > 0:
            mode.route_budget -= 1
            self.path_timer = 0.8
            self.path = mode.route((x, y), (tx, ty))
        return False

    def play_action(self, delta_seconds: float, mode: DoomHangarMode, target: ue.Pawn) -> None:
        self.anim_time += delta_seconds * self.tempo(mode)
        end = 0.0
        for index, (letter, tics, attacks) in enumerate(self.anim):
            start = end
            end += tics * TIC
            if attacks and self.anim_time >= start and index > self.action_event:
                self.action_event = index
                self.fired = True
                self.shoot(mode, target)
            if self.anim_time < end:
                self.image(self.prefix + letter + "1")
                return
        self.anim = []

    def shoot(self, mode: DoomHangarMode, target: ue.Pawn) -> None:
        x, y = xy(self)
        px, py = xy(target)
        self.facing = math.degrees(math.atan2(py - y, px - x))
        if self.prefix == "SKUL":
            direction = target.get_actor_location() - self.get_actor_location()
            direction /= max(1.0, math.sqrt(sum(float(v) ** 2 for v in direction)))
            self.charge_direction = [float(v) for v in direction]
            self.charge_time = 2.0
            return
        hit, _ = ray(self.get_actor_location().copy(), target.get_actor_location().copy(), [self])
        if self.prefix in ("TROO", "SARG", "BOSS", "HEAD") and self.in_reach(target, hit == target):
            # Imps, demons, barons and cacodemons bite or claw when in reach, and shoot otherwise.
            dice, size = {"TROO": (8, 3), "SARG": (10, 4), "BOSS": (8, 10), "HEAD": (6, 10)}[self.prefix]
            self.damage_target(mode, target, random.randint(1, dice) * size)
            mode.sound("DSCLAW", 0.35, at=self.get_actor_location())
        elif self.prefix in ("POSS", "SPOS", "SPID"):
            mode.sound(self.attack_sound, 0.35, at=self.get_actor_location())
            if hit == target:
                self.damage_target(
                    mode, target, random.randint(1, 5) * 3 * (3 if self.prefix in ("SPOS", "SPID") else 1)
                )
        elif self.prefix != "SARG":
            key = {"TROO": "BAL1A0", "HEAD": "BAL2A0", "BOSS": "BAL7A1", "CYBR": "MISLA1"}[self.prefix]
            bolt = ue.spawn_actor(projectiles.DoomProjectile, location=self.get_actor_location().copy())
            aim = target.get_actor_location().copy()
            direction = aim - self.get_actor_location()
            direction /= max(1.0, math.sqrt(sum(float(v) ** 2 for v in direction)))
            # Missile speeds, map units a tic: imp and cacodemon balls 10, baron 15 (doubled on Nightmare),
            # rocket 20.
            speed = 700 if self.prefix == "CYBR" else (525 if self.prefix == "BOSS" else 350)
            bolt.configure(
                direction,
                self,
                key,
                speed * (2 if mode.skill == 5 and self.prefix != "CYBR" else 1),
                20 if self.prefix == "CYBR" else 8 if self.prefix == "BOSS" else 3,
                128 if self.prefix == "CYBR" else 0,
                "monster",
            )
            mode.objects.append(bolt)
            mode.sound(self.attack_sound, 0.35, at=self.get_actor_location())

    def damage_target(self, mode: DoomHangarMode, target: ue.Actor, damage: int) -> None:
        if isinstance(target, player_mod.DoomMarine):
            mode.hurt(damage, who=target)
        elif isinstance(target, (DoomDemon, world.DoomBarrel)):
            target.hurt(damage, source=self)

    def tick(self, delta_seconds: float) -> None:
        mode = mode_now()
        if mode is None:
            return
        if not self.has_authority():
            self.refresh_view()  # a replica only turns towards the local camera: the server runs the monster
            return
        player = mode.closest_player(self)
        if player is None:
            return
        if mode.paused:
            return
        self.clock += delta_seconds
        if self.grudge > 0:
            self.grudge = max(0.0, self.grudge - delta_seconds)
        x, y = xy(self)
        px, py = xy(player)
        if self.dead and self.gibbed:
            self.image("POL5A0")  # gibs can still come back on Nightmare, below
            if (
                mode.skill == 5
                and self.clock > 12
                and int(self.clock / (32 * TIC)) != int((self.clock - delta_seconds) / (32 * TIC))
                and random.randrange(256) < 4
            ):
                self.nightmare_respawn(mode)
            return
        if self.dead:
            # Normal death frames: H-L (imp I-M); the letters after them are the gib animation.
            frames = DEATH_STATES[self.prefix]
            if self.prefix == "SKUL" and self.clock >= sum(t for _, t in frames) * TIC:
                self.set_actor_hidden_in_game(True)
                return
            letter = state_frame(frames, self.clock)
            self.image(self.prefix + letter + "0")
            # Nightmare: every 32 tics a corpse has a 4 in 256 chance to come back.
            if (
                mode.skill == 5
                and self.clock > 12
                and int(self.clock / (32 * TIC)) != int((self.clock - delta_seconds) / (32 * TIC))
                and random.randrange(256) < 4
            ):
                self.nightmare_respawn(mode)
            return
        if mode.testing or mode.everyone_dead() or mode.won:
            self.image(self.prefix + "A1")
            return
        if self.charge_time > 0:
            self.charge_time = max(0.0, self.charge_time - delta_seconds)
            start = self.get_actor_location().copy()
            end = start.copy()
            for axis in range(3):
                end[axis] += self.charge_direction[axis] * 700 * SCALE * delta_seconds
            hit, _ = ray(start, end, [self])
            if hit is not None:
                self.damage_target(mode, hit, random.randint(1, 8) * 3)
                self.charge_time = 0
                self.anim = []
            else:
                self.set_actor_location(end, True, True)
            self.image(self.prefix + "CD"[int(self.clock / (4 * TIC)) % 2] + "1")
            return
        if self.anim:
            self.play_action(delta_seconds, mode, self.current_target() or player)
            return
        if not self.awake:
            self.image(self.prefix + state_frame(IDLE_STATES[self.prefix], self.clock, True) + "1")
            self.look_clock -= delta_seconds
            if self.look_clock <= 0:
                self.look_clock += 10 * TIC  # a sleeper looks around every 10 tics
                if any(self.look(mode, marine) for marine in mode.marines()):
                    self.awake, self.chase_clock = True, 0.0
            return
        self.image(
            self.prefix + state_frame(WALK_STATES[self.prefix], self.clock * self.tempo(mode), True) + "1"
        )
        self.path_timer -= delta_seconds
        self.chase_clock -= delta_seconds
        if self.chase_clock <= 0:
            self.chase_clock = chase_tics(self.type_id, mode.skill == 5) * TIC
            if self.think(mode, player):
                return
        tx, ty = xy(self.current_target() or player)
        goal = self.path[0] if self.path else (tx, ty)
        x, y = xy(self)
        dx, dy = goal[0] - x, goal[1] - y
        length = math.hypot(dx, dy)
        if length < 20 and self.path:
            self.path.pop(0)
        if length > 36:
            self.add_movement_input(ue.Vector(dx / length, -dy / length, 0), 1)

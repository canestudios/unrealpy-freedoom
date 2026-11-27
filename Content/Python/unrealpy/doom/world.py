from __future__ import annotations

import math
from typing import Any

from typing_extensions import override

import ue
from doom import net
from doom import player as player_mod
from doom.animation import EFFECT_STATES, ITEM_STATES, state_frame
from doom.common import (
    BARREL_EXPLOSION,
    ITEMS,
    SCALE,
    TIC,
    mode_now,
    player_now,
    show_sprite,
    vec,
    xy,
)
from doom.rules import KEY_PICKUPS, WEAPON_PICKUPS
from doom.visual import sprite_view


@ue.uclass
class DoomGeometry(ue.Actor):
    mesh = ue.component(ue.ProceduralMeshComponent)


ANIMATION_STEP = 0.05
DROP_LIFT = 2.0  # map units
FLOOR_ITEMS: dict[int, list[DoomSprite]] = {}


def follow_floor(mode: Any, sector: int) -> None:
    """Called by the floor mover: pickups standing in the sector ride its floor."""
    items = FLOOR_ITEMS.get(sector)
    if not bool(items):
        return
    items[:] = [item for item in items if item.is_valid()]
    floor = mode.sector_floor(sector)
    for item in items:
        if not item.taken:
            x, y = xy(item)
            item.set_actor_location(vec(x, y, floor), False, True)


def sprite_image(actor: Any, key: str, flipped: bool, base_z: float = 0.0) -> bool:
    """Show a sprite lump on the actor's camera-facing billboard; True when the picture changed."""
    mode = mode_now()
    if mode is None or not mode.ready:
        return False
    if key not in mode.data["sprites"]:
        rotation = int(key[5:6]) if key[5:6].isdigit() else 0
        key, flipped = sprite_view(mode.data["sprites"], key[:5], rotation)
    if not key or (key == actor.key and flipped == getattr(actor, "image_flipped", False)):
        return False
    actor.image_flipped = flipped
    actor.key = key
    show_sprite(
        actor.billboard,
        mode,
        key,
        flipped,
        base_z,
        floor_clip=getattr(actor, "kind", 0) in ITEMS or key.startswith("BAR1"),
    )
    return True


@ue.uclass
class DoomSprite(ue.Actor):
    """Item, decoration or effect drawn as a camera-facing billboard (Unreal turns it, not Python).

    Static sprites never tick. A pickup wakes up only while the player is inside its trigger box
    (the exact reach check stays in tick); animated pickups and pickups on moving floors always tick.
    """

    replicates = True
    pickup_zone = ue.component(ue.BoxComponent, box_extent=ue.Vector(36 * SCALE, 36 * SCALE, 60 * SCALE))
    billboard = ue.component(ue.MaterialBillboardComponent, parent="pickup_zone")
    TICKS = False
    # Replicated: which pickup it is, which picture it shows, and whether a player took it.
    kind: int = ue.uproperty(0, replicated=True)
    pose: str = ue.uproperty("", rep_notify="on_pose")
    taken: bool = ue.uproperty(False, rep_notify="on_taken")
    dropped: bool = ue.uproperty(False, replicated=True)

    def post_init(self) -> None:
        self.key = ""
        self.thing_id = -1
        self.prepared = False
        self.always_tick = False
        self.lift = (0.0, 0.0, 0.0)
        self.floor_sector = -1
        self.billboard.set_mobility(ue.EComponentMobility.Movable)
        self.billboard.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
        self.pickup_zone.set_collision_profile_name("OverlapAllDynamic")
        self.pickup_zone.set_collision_enabled(ue.ECollisionEnabled.NoCollision)

    def begin_play(self) -> None:
        if net.networked() and self.has_authority():
            net.replicate(self, movement=True)
        # Unreal starts every ticking class enabled; only moving sprites keep it.
        self.set_actor_tick_enabled(self.TICKS or self.always_tick)
        self.apply_replicated()

    # -- replication ---------------------------------------------------------------------------------------

    def on_pose(self) -> None:
        self.apply_replicated()

    def on_taken(self) -> None:
        self.set_actor_hidden_in_game(self.taken)

    def apply_replicated(self) -> None:
        """A client's replica shows what the server says (once its level is built)."""
        if self.has_authority():
            return
        mode = mode_now()
        if mode is None or not mode.ready:
            return
        if self.pose:
            self.show(self.pose)
        self.set_actor_hidden_in_game(self.taken)
        self.set_actor_tick_enabled(self.dropped and not self.taken)

    def prepare(self, mode: Any) -> None:
        """Once the sprite has its kind: decide what, if anything, has to run each frame."""
        self.prepared = True
        if self.kind in ITEMS:
            self.floor_sector = mode.sector_at(*xy(self))
            # A dropped item stands on its corpse: it needs the per-frame pull towards the camera (see tick).
            self.always_tick = self.kind in ITEM_STATES or self.dropped
            # Sprites on a floor that can move are repositioned by the mover code (follow_floor).
            FLOOR_ITEMS.setdefault(self.floor_sector, [])
            items = FLOOR_ITEMS[self.floor_sector]
            items[:] = [item for item in items if item.is_valid()]
            items.append(self)

    def arm(self) -> None:
        """(Re)arm a pickup: trigger box on, ticking when always needed or a player already stands in it."""
        self.pickup_zone.set_collision_enabled(ue.ECollisionEnabled.QueryOnly)
        if self.always_tick:
            # Animated pickups only need a frame change every 6 tics; every frame once the player is close.
            self.set_actor_tick_interval(ANIMATION_STEP)
        self.set_actor_tick_enabled(
            self.always_tick or any(self.is_overlapping_actor(marine) for marine in net.marines())
        )

    def image(self, key: str, flipped: bool = False) -> None:
        """Show a picture (the server also tells the clients, through `pose`)."""
        if self.pose != key:
            self.pose = key
        self.show(key, flipped)

    def show(self, key: str, flipped: bool = False) -> None:
        mode = mode_now()
        if mode is None or not mode.ready:
            return
        if not self.prepared:
            self.prepare(mode)
        changed = sprite_image(self, key, flipped)
        if changed:
            self.lift = (0.0, 0.0, 0.0)  # show_sprite put the billboard back at its rest position
        if (
            changed
            and self.has_authority()
            and self.kind in ITEMS
            and not self.taken
            and not self.is_actor_tick_enabled()
        ):
            self.arm()

    def actor_begin_overlap(self, other_actor: ue.Actor | None) -> None:
        if isinstance(other_actor, player_mod.DoomMarine) and not self.taken and self.has_authority():
            self.set_actor_tick_interval(0.0)
            self.set_actor_tick_enabled(True)

    def actor_end_overlap(self, other_actor: ue.Actor | None) -> None:
        if not isinstance(other_actor, player_mod.DoomMarine):
            return
        try:
            authority = self.has_authority()
        except ue.StaleObjectError:
            # A sprite destroyed while a marine overlaps it gets this event during its destruction, when its
            # functions can no longer be called; its tick no longer matters then.
            return
        if authority:
            if self.always_tick:
                self.set_actor_tick_interval(ANIMATION_STEP)
            else:
                self.set_actor_tick_enabled(False)

    def face_camera(self, player: player_mod.DoomMarine) -> None:
        """Keep a dropped item's billboard DROP_LIFT map units nearer the camera than its corpse's.

        Both camera-facing quads stand at the same spot, so they have the same depth and z-fight (flicker).
        Masked sprites cannot be sorted, and a depth bias in the billboard material does not compile for
        material billboards; moving the quad towards the viewer is the only thing that always wins.
        """
        offset = player.camera.get_world_location() - self.get_actor_location()
        length = math.sqrt(float(offset[0]) ** 2 + float(offset[1]) ** 2 + float(offset[2]) ** 2)
        k = DROP_LIFT * SCALE / length if length > 1 else 0.0
        lift = (float(offset[0]) * k, float(offset[1]) * k, float(offset[2]) * k)
        delta = ue.Vector(lift[0] - self.lift[0], lift[1] - self.lift[1], lift[2] - self.lift[2])
        self.billboard.add_relative_location(delta, False, True)
        self.lift = lift

    def tick(self, delta_seconds: float) -> None:
        mode = mode_now()
        viewer = player_now()
        if mode is None or not isinstance(viewer, player_mod.DoomMarine) or mode.paused:
            return
        if not self.has_authority():
            if self.dropped and not self.taken:
                self.face_camera(viewer)
            return
        if self.taken:
            self.set_actor_tick_enabled(False)
            return
        x, y = xy(self)
        if self.kind in ITEM_STATES:
            self.image(state_frame(ITEM_STATES[self.kind], mode.elapsed, True))
        if self.dropped:
            self.face_camera(viewer)
        if self.kind not in ITEMS:
            return
        for marine in net.marines():
            ps = marine.doom_state
            if ps is None or ps.dead:
                continue
            px, py = xy(marine)
            height_delta = (
                float(self.get_actor_location()[2])
                - float(marine.get_actor_location()[2])
                + marine.capsule_component.get_scaled_capsule_half_height()
            )
            if (
                # Original PIT_CheckThing overlaps square XY bounds: player16 + pickup20.
                abs(px - x) < 36
                and abs(py - y) < 36
                and -8 * SCALE <= height_delta <= 56 * SCALE
                and mode.pickup(self.kind, self.dropped, who=marine)
            ):
                if (
                    net.networked()
                    and not self.dropped
                    and (
                        self.kind in KEY_PICKUPS or (self.kind in WEAPON_PICKUPS and mode.match.weapons_stay)
                    )
                ):
                    continue  # Keys, and the weapons of co-op and deathmatch, stay for the others.
                self.taken = True
                mode.item_taken(self)
                self.pickup_zone.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
                self.set_actor_hidden_in_game(True)
                self.set_actor_tick_enabled(False)
                break


@ue.uclass
class DoomBarrel(ue.Actor):
    """Explodes when shot: damages what is around it (128 - distance), including other barrels."""

    replicates = True
    body = ue.component(ue.BoxComponent, box_extent=ue.Vector(10 * SCALE, 10 * SCALE, 21 * SCALE))
    billboard = ue.component(ue.MaterialBillboardComponent, parent="body")
    pose: str = ue.uproperty("", rep_notify="on_pose")
    exploded: bool = ue.uproperty(False, rep_notify="on_exploded")

    def post_init(self) -> None:
        self.key = ""
        self.thing_id = -1
        self.health = 20
        self.clock = 0.0
        self.billboard.set_mobility(ue.EComponentMobility.Movable)
        self.billboard.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
        self.body.set_collision_profile_name("BlockAll")

    def begin_play(self) -> None:
        if net.networked() and self.has_authority():
            net.replicate(self)
        # The idle flicker changes 3 times a second; only the explosion needs every frame.
        self.set_actor_tick_interval(0.05)
        self.apply_replicated()

    def on_pose(self) -> None:
        self.apply_replicated()

    def on_exploded(self) -> None:
        if self.exploded:
            self.body.set_collision_enabled(ue.ECollisionEnabled.NoCollision)

    def apply_replicated(self) -> None:
        if self.has_authority():
            return
        mode = mode_now()
        if mode is not None and mode.ready and self.pose:
            self.show(self.pose)

    def image(self, key: str, flipped: bool = False) -> None:
        if self.pose != key:
            self.pose = key
        self.show(key, flipped)

    def show(self, key: str, flipped: bool = False) -> None:
        if sprite_image(self, key, flipped, -21 * SCALE) and not self.exploded and self.has_authority():
            self.set_actor_tick_enabled(True)
            self.set_actor_tick_interval(0.05)

    def hurt(self, damage: int, source: ue.Actor | None = None) -> None:
        if self.exploded or not self.has_authority():
            return
        self.health -= damage
        if self.health <= 0:
            self.exploded = True
            self.clock = 0.0
            self.body.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
            self.set_actor_tick_interval(0.0)
            mode = mode_now()
            if mode:
                mode.sound("DSBAREXP", at=self.get_actor_location())
                mode.blast(self, 128, source)

    def tick(self, delta_seconds: float) -> None:
        mode = mode_now()
        if mode is None or mode.paused or not self.has_authority():
            return
        if not self.exploded:
            self.image("BAR1" + "AB"[int(mode.elapsed * 3) % 2] + "0")
            return
        self.clock += delta_seconds
        end = 0.0
        for frame, tics in BARREL_EXPLOSION:
            end += tics * TIC
            if self.clock < end:
                self.image(frame)
                return
        self.set_actor_hidden_in_game(True)
        self.set_actor_tick_enabled(False)


@ue.uclass
class DoomEffect(DoomSprite):
    """A short-lived effect (puff, blood, teleport flash): each machine spawns its own, none replicates."""

    replicates = False
    TICKS = True

    @override
    def post_init(self) -> None:
        super().post_init()
        # Builds with older ScriptCore versions can still infer replication from DoomSprite.
        self.set_replicates(False)
        self.effect_name = "teleport"
        self.age = 0.0

    @override
    def begin_play(self) -> None:
        self.set_actor_tick_enabled(True)

    @override
    def image(self, key: str, flipped: bool = False) -> None:
        self.show(key, flipped)

    @override
    def tick(self, delta_seconds: float) -> None:
        mode = mode_now()
        if mode is None or mode.paused:
            return
        self.age += delta_seconds
        states = EFFECT_STATES[self.effect_name]
        if self.age >= sum(t for _, t in states) * TIC:
            self.destroy_actor()
        else:
            self.image(state_frame(states, self.age))

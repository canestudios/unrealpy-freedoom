from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Any

from typing_extensions import override

import ue
from doom import monsters, world
from doom import player as player_mod
from doom.animation import PROJECTILE_STATES, state_frame
from doom.common import SCALE, TIC, mode_now, player_now, ray, xy
from doom.visual import projectile_family, sprite_view, view_rotation
from doom.world import DoomSprite

if TYPE_CHECKING:
    from doom import mode as mode_mod


@ue.uclass
class DoomProjectile(DoomSprite):
    TICKS = True

    dx: float = ue.uproperty(1.0, replicated=True)  # where it flies (map plane): clients turn its sprite
    dy: float = ue.uproperty(0.0, replicated=True)

    @override
    def post_init(self) -> None:
        super().post_init()
        self.owner = None
        self.friendly = False
        self.age = 0.0
        self.stage = "flight"
        self.sprayed = False

    @override
    def show(self, key: str, flipped: bool = False) -> None:
        mode = mode_now()
        player = player_now()
        if mode is not None and mode.ready and player is not None:
            facing = math.degrees(math.atan2(-self.dy, self.dx))
            rotation = view_rotation(*xy(self), *xy(player), facing)
            key, flipped = sprite_view(mode.data["sprites"], key[:5], rotation)
        super().show(key, flipped)

    def configure(
        self,
        direction: Any,
        owner: ue.Actor,
        key: str,
        speed: float,
        damage: int,
        radius: float,
        weapon: str,
    ) -> None:
        self.dx, self.dy, self.dz = (float(v) for v in direction)  # dx, dy replicate
        self.owner, self.friendly = owner, isinstance(owner, player_mod.DoomMarine)
        self.speed, self.damage, self.radius, self.weapon = speed, damage, radius, weapon
        self.family = projectile_family(key, weapon)
        self.image(key)

    @override
    def tick(self, delta_seconds: float) -> None:
        mode = mode_now()
        if not self.has_authority():
            if mode is not None and mode.ready and self.pose:
                self.show(self.pose)  # a replica only turns towards the local camera
            return
        if mode is None or mode.paused or not hasattr(self, "speed"):
            return
        self.age += delta_seconds
        flight, impact = PROJECTILE_STATES[self.family]
        if self.stage == "explosion":
            if self.weapon == "bfg" and not self.sprayed and self.age >= 16 * TIC:
                self.sprayed = True
                self.bfg_spray(mode)
            if self.age >= sum(t for _, t in impact) * TIC:
                self.destroy_actor()
            else:
                self.image(state_frame(impact, self.age))
            return
        self.image(state_frame(flight, self.age, True))
        start = self.get_actor_location().copy()
        distance = self.speed * SCALE * delta_seconds
        end = start.copy()
        end[0] += self.dx * distance
        end[1] += self.dy * distance
        end[2] += self.dz * distance
        owner = self.owner or (player_now() if self.friendly else None)
        ignore = [self, owner] if owner and owner.is_valid() else [self]
        hit, _ = ray(start, end, ignore)
        if hit is None and self.age < 8:
            self.set_actor_location(end, False, True)
            return
        if (
            isinstance(hit, monsters.DoomDemon)
            and isinstance(owner, monsters.DoomDemon)
            and monsters.same_species(owner, hit)
        ):
            pass  # Same species: the missile explodes without hurting.
        elif isinstance(hit, (monsters.DoomDemon, world.DoomBarrel)):
            hit.hurt(self.damage * random.randint(1, 8), source=owner)
        elif isinstance(hit, player_mod.DoomMarine):
            mode.hurt(self.damage * random.randint(1, 8), who=hit, source=owner)
        if self.radius:
            mode.blast(self, self.radius, owner)
        self.stage, self.age = "explosion", 0.0
        self.image(impact[0][0])
        mode.sound("DSBAREXP" if self.radius else "DSFIRXPL", 0.6, at=self.get_actor_location())

    def bfg_spray(self, mode: mode_mod.DoomHangarMode) -> None:
        owner = self.owner
        if owner and owner.is_valid():
            # Original BFG spray: forty hitscan rays in a 90-degree fan from the shooter.
            origin = owner.get_actor_location().copy()
            yaw = math.atan2(self.dy, self.dx)
            for i in range(40):
                angle = yaw - math.pi / 4 + i * math.pi / 80
                target = origin.copy()
                target[0] += math.cos(angle) * 4096
                target[1] += math.sin(angle) * 4096
                victim, _ = ray(origin, target, [self, owner])
                rival = isinstance(victim, player_mod.DoomMarine) and mode.networked
                if rival or isinstance(victim, (monsters.DoomDemon, world.DoomBarrel)):
                    mode.effect("bfg_hit", victim.get_actor_location().copy())
                    damage = sum(random.randint(1, 8) for _ in range(15))
                    if isinstance(victim, player_mod.DoomMarine):
                        mode.hurt(damage, who=victim, source=owner)
                    else:
                        victim.hurt(damage, source=owner)

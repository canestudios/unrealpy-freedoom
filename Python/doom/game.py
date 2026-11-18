"""Ultimate Doom rebuilt from the user's IWAD using UnrealPy, not a Doom source port.

First run doom.importer:main in the editor. Launch with doom.game:play.
WASD, mouse, click, E, 1-7 weapons, Shift run, Tab automap, Escape menu,
F5/F9 quick save/load. Locally owned assets only.
"""

from __future__ import annotations

import math
import os
from typing import Any

import ue
from doom import campaign, console, lighting, monsters, net, projectiles, world
from doom import mode as mode_mod  # noqa: F401  # defines DoomHangarMode before play()
from doom import player as player_mod
from doom import specials as specials_mod
from doom.animation import ATTACK_FRAMES
from doom.common import ITEMS, MODE, SCALE, WALK_SPECIALS, mode_now, section, vec, xy
from doom.dataset import CONTENT
from ue import agent


def play(_args: list[str]) -> None:
    ue.GameplayStatics.open_level(
        "/Engine/Maps/Entry", True, f"game={MODE}", world_context_object=ue.get_world()
    )


def host(args: list[str]) -> None:
    """Listen server for this player and for the clients that run `join`.

    Options, as `key=value` arguments or env: match (`DOOM_MATCH`: coop, deathmatch, altdeath), fraglimit
    (`DOOM_FRAGLIMIT`), timelimit in minutes (`DOOM_TIMELIMIT`), monsters (`DOOM_MONSTERS`: 0 or 1, default
    1 in co-op and 0 otherwise) and map (`DOOM_MAP`, default E1M1).
    """
    net.apply_args(args)
    ue.GameplayStatics.open_level(
        "/Engine/Maps/Entry", True, f"game={MODE}?listen", world_context_object=ue.get_world()
    )


def join(args: list[str]) -> None:
    """Join a co-op game: the address is the first argument, else env DOOM_SERVER, else 127.0.0.1."""
    address = (args[0] if args else os.environ.get("DOOM_SERVER", "")) or "127.0.0.1"
    ue.KismetSystemLibrary.execute_console_command(f"open {address}")


def sector_spots(mode: Any, sector: int, count: int) -> list[tuple[float, float]]:
    """Points well inside a sector, at least 40 map units apart."""
    xs, ys = [], []
    for line in mode.data["lines"]:
        for side in (line["right"], line["left"]):
            if side != 65535 and mode.data["sides"][side]["sector"] == sector:
                for vertex in (line["a"], line["b"]):
                    xs.append(mode.data["vertices"][vertex][0])
                    ys.append(mode.data["vertices"][vertex][1])
    found: list[tuple[float, float]] = []
    for x in range(int(min(xs)) + 20, int(max(xs)) - 19, 8):
        for y in range(int(min(ys)) + 20, int(max(ys)) - 19, 8):
            around = ((x, y), (x + 20, y), (x - 20, y), (x, y + 20), (x, y - 20))
            if all(mode.sector_at(px, py) == sector for px, py in around) and all(
                math.dist((x, y), spot) >= 40 for spot in found
            ):
                found.append((float(x), float(y)))
                if len(found) == count:
                    return found
    raise AssertionError(f"no room in sector {sector}")


async def check_crushers(mode: Any) -> None:
    """Crushers hurt: the marine takes 10 per 4 tics, corpses become gibs, drops vanish.

    E2M2 has a silent crusher (73, slows to 1/8 speed) and a fast one (77, does not).
    """
    for marker, special, slows in (("E2M2", 73, True), ("E2M2", 77, False)):
        campaign.load_level(mode, marker, 3)
        mode.testing = True
        await agent.frames(20)
        player = ue.GameplayStatics.get_player_pawn(0)
        assert isinstance(player, player_mod.DoomMarine)
        index = next(i for i, line in enumerate(mode.data["lines"]) if line["special"] == special)
        sector = next(s for s in specials_mod.targets(mode, mode.data["lines"][index]) if s in mode.ceilings)
        spots = sector_spots(mode, sector, 4)
        mode.armor, mode.health, mode.god_mode, mode.invulnerability = 0, 100, False, 0
        mode.warp(player, *spots[0], 0.0)
        player.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)

        def thing(spot: tuple[float, float], prefix: str, kind: int, health: int) -> Any:
            demon = ue.spawn_actor(monsters.DoomDemon, location=vec(*spot, mode.floor(*spot) + 29))
            assert demon
            demon.prefix, demon.type_id, demon.health = prefix, kind, health
            demon.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
            mode.objects.append(demon)
            return demon

        corpse = thing(spots[1], "POSS", 3004, 20)
        victim = thing(spots[2], "TROO", 3001, 60)
        corpse.hurt(1000)
        victim.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
        drop = ue.spawn_actor(world.DoomSprite, location=vec(*spots[3], mode.floor(*spots[3])))
        assert drop
        drop.kind, drop.dropped = 2007, True
        drop.image(ITEMS[2007])
        mode.objects.append(drop)
        await agent.frames(45)
        assert corpse.dead and not corpse.gibbed and drop.is_valid()
        ceiling = mode.ceilings[sector]
        assert specials_mod.activate(mode, index, "walk"), f"{marker}: crusher {special} did not start"
        base_speed = ceiling["speed"]
        health = 100
        for _ in range(2400):
            await agent.frames(1)
            if mode.dead and victim.dead and corpse.gibbed and not drop.is_valid():
                break
            assert (100 - mode.health) % 10 == 0 and mode.health <= health, (
                f"{marker}: crush damage is 10 a hit"
            )
            health = mode.health
            if health < 100:
                assert ceiling["speed"] == (base_speed / 8 if slows else base_speed), (
                    f"{marker}: crusher speed"
                )
        assert mode.dead, f"{marker}: crusher {special} did not kill the marine"
        assert victim.dead, f"{marker}: crusher did not kill a monster"
        assert corpse.gibbed and corpse.pose == "POL5A", f"{marker}: corpse not crushed into gibs"
        assert not drop.is_valid(), f"{marker}: dropped item not crushed"
        player.character_movement.set_movement_mode(ue.EMovementMode.MOVE_Walking)


async def demo(_args: list[str]) -> dict[str, Any]:
    agent.set_fixed_timestep(1 / 60)
    play([])
    for _ in range(120):
        await agent.frames(1)
        mode = mode_now()
        player = ue.GameplayStatics.get_player_pawn(0)
        if mode is not None and isinstance(player, player_mod.DoomMarine) and mode.positioned:
            break
    else:
        raise AssertionError("E1M1 did not start")
    mode.testing = True
    mode.menu, mode.started = "", True
    controller = ue.GameplayStatics.get_player_controller(0)
    assert isinstance(controller, player_mod.DoomController)
    controller.automated = True
    await agent.frames(40)
    assert len(mode.data["sectors"]) == 88 and len(mode.data["lines"]) == 486
    assert abs(float(player.get_actor_location()[2]) / SCALE - mode.floor(*xy(player)) - 28) < 3, (
        "Starting floor collision"
    )
    assert mode.music.ready, f"Original music could not start: {mode.music.error}"
    assert mode.total > 0 and mode.texture("STBAR", True) is not None
    assert mode.sounds.get("DSITEMUP") is not None or ue.load_object(CONTENT + "/sounds/DSITEMUP") is not None
    before = player.get_actor_location().copy()
    for _ in range(20):
        player.add_movement_input(ue.Vector(0, -1, 0), 1)
        await agent.frames(1)
    assert float(player.get_actor_location()[1]) < float(before[1]) - 10, "Native movement"
    # The runtime lighting switch: refused cleanly (and not in the menu) where Lumen cannot run.
    shown_menu, mode.menu = mode.menu, "main"
    has_row = any(row.startswith("LIGHTING") for row in campaign.menu_rows(mode))
    mode.menu = shown_menu
    assert has_row == lighting.supported(), "Lighting menu row only when supported"
    if not lighting.supported():
        assert not lighting.active() and not lighting.set_enabled(mode, True), "Lighting refused"
        assert not lighting.active() and not lighting.toggle(mode), "Lighting stays unlit"
    else:
        was = lighting.active()
        assert lighting.set_enabled(mode, not was) and lighting.active() != was
        assert lighting.set_enabled(mode, was) and lighting.active() == was
        await agent.frames(5)
    # The lighting test sliders: rows only in the lit mode, clamped steps, reset to neutral.
    assert (len(lighting.slider_rows()) == 4) == lighting.active(), "Slider rows only in the lit mode"
    if lighting.supported():
        initial = lighting.active()
        lighting.set_enabled(mode, True)
        await agent.frames(5)
        shown_menu, mode.menu = mode.menu, "main"
        assert [
            r for r in campaign.menu_rows(mode) if bool(lighting.slider_key(r))
        ] == lighting.slider_rows()[:3]
        lighting.adjust(mode, "world", 99)
        lighting.adjust(mode, "lights", -99)
        lighting.adjust(mode, "exposure", 1)
        assert lighting.slider_value("world") == 3.0 and lighting.slider_value("lights") == 0.25
        assert lighting.slider_value("exposure") == 0.5
        lighting.set_enabled(mode, False)
        assert not lighting.slider_rows() and lighting.slider_value("world") == 3.0, "Kept in classic"
        lighting.set_enabled(mode, True)
        lighting.reset(mode)
        assert [lighting.slider_value(k) for k in ("world", "lights", "exposure")] == [1.0, 1.0, 0.0]
        mode.menu = shown_menu
        await agent.frames(5)
        lighting.set_enabled(mode, initial)
    mode.health = 50
    assert mode.pickup(2012) and mode.health == 75
    assert mode.pickup(2001) and mode.weapon == "shotgun" and mode.shells == 8
    door_index = next(iter(mode.doors))
    mode.open_door(door_index)
    await agent.frames(100)
    assert mode.doors[door_index]["height"] > 40
    # The sector graph routes through a door only while it is open.
    held = {index: door["height"] for index, door in mode.doors.items()}
    routed = False
    for index, door in mode.doors.items():
        ends = [(o, x, y) for o, x, y in mode.portals.get(index, ()) if o not in mode.doors]
        for first, second in ((p, q) for p in ends for q in ends if p[0] < q[0]):
            door["height"] = door["closed"]
            blocked = mode.search_portals(first[0], second[0], first[1:], second[1:])
            door["height"] = door["target"]
            opened = mode.search_portals(first[0], second[0], first[1:], second[1:])
            if blocked is None and opened:
                routed = True
                break
        if routed:
            break
    for index, height in held.items():
        mode.doors[index]["height"] = height
    assert routed, "Sector route passes a door only when it is open"
    enemy = mode.enemies[0]
    enemy.hurt(100)
    await agent.frames(45)
    assert enemy.dead and mode.kills == 1
    # A monster's attack plays its frames and strikes on the firing frame; pain makes it flinch.
    shooter = next(e for e in mode.enemies if not e.dead)
    shooter.act(ATTACK_FRAMES[shooter.prefix])
    shown = set()
    for _ in range(70):
        shooter.play_action(1 / 60, mode, player)
        shown.add(shooter.frame)
    assert {shooter.prefix + letter for letter, _, _ in ATTACK_FRAMES[shooter.prefix]} <= {
        frame[:5] for frame in shown
    }
    assert shooter.fired and not shooter.anim, "Monster attack animation"
    # Barrels explode when shot, with Doom's explosion frames.
    barrel = next(obj for obj in mode.objects if isinstance(obj, world.DoomBarrel))
    barrel.hurt(25)
    assert barrel.exploded
    await agent.frames(3)
    assert barrel.key.startswith("BEXP"), barrel.key
    await agent.frames(60)
    assert barrel.hidden, "Barrel explosion ends"
    exit_line = next(line for line in mode.data["lines"] if line["special"] == 11)
    a, b = mode.data["vertices"][exit_line["a"]], mode.data["vertices"][exit_line["b"]]
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    x, y = (a[0] + b[0]) / 2 + dy / length * 30, (a[1] + b[1]) / 2 - dx / length * 30
    player.set_actor_location(vec(x, y, mode.floor(x, y) + 29), False, True)
    controller.set_control_rotation(ue.Rotator(0, -math.degrees(math.atan2(dx, -dy)), 0))
    mode.use()
    assert mode.won, "Original exit switch"
    mode.won = False
    floors = {}
    for line in mode.data["lines"]:
        if line["special"] not in WALK_SPECIALS:
            continue
        a, b = mode.data["vertices"][line["a"]], mode.data["vertices"][line["b"]]
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        normal = ((b[1] - a[1]), -(b[0] - a[0]))
        size = math.hypot(*normal)
        mode.cross_lines(
            (mid[0] - normal[0] / size * 8, mid[1] - normal[1] / size * 8),
            (mid[0] + normal[0] / size * 8, mid[1] + normal[1] / size * 8),
        )
        for si, sector in enumerate(mode.data["sectors"]):
            if line["tag"] and sector["tag"] == line["tag"]:
                floors[(line["special"], si)] = sector["floor"]
    lift = next(si for (special, si) in floors if special == 88)
    lowest = mode.movers[lift]["target"]
    for _ in range(240):
        await agent.frames(1)
        if mode.movers[lift]["offset"] == lowest:
            break
    assert mode.movers[lift]["offset"] == lowest, "Lift lowers"
    for (special, si), floor in floors.items():
        if special in (36, 38):
            for _ in range(300):
                if mode.movers[si]["offset"] == mode.movers[si]["target"]:
                    break
                await agent.frames(1)
            assert mode.sector_floor(si) == floor + mode.movers[si]["target"], f"Floor {special} lowers"
        if special == 109:
            assert mode.doors[si]["opened"], "Walk-over door opens"
    for _ in range(420):
        await agent.frames(1)
        if mode.movers[lift]["offset"] == 0.0:
            break
    assert mode.movers[lift]["offset"] == 0.0, "Lift returns"
    # Weapon HUD alignment projects the weapon's original sprite centre onto the camera ray.
    controller.set_control_rotation(ue.Rotator(20, 30, 0))
    for weapon, expected_x in (("pistol", 154.5), ("shotgun", 160.5)):
        mode.weapon = weapon
        await agent.frames(2)
        direction = mode.aim_direction(player)
        forward = player.camera.get_forward_vector().copy()
        right = player.camera.get_right_vector().copy()
        actual = float(sum(float(direction[i]) * float(right[i]) for i in range(3))) / float(
            sum(float(direction[i]) * float(forward[i]) for i in range(3))
        )
        expected = (expected_x / 160 - 1) * math.tan(math.radians(player.camera.field_of_view / 2))
        assert abs(actual - expected) < 0.001, f"{weapon} weapon aim offset: {actual} != {expected}"

    # Isolate a barrel chain and verify radius damage plus map-only sight blocking.
    for obj in mode.objects:
        if isinstance(obj, (monsters.DoomDemon, world.DoomBarrel)):
            obj.set_actor_location(vec(10000, 10000, 1000), False, True)
            if isinstance(obj, monsters.DoomDemon):
                obj.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
                obj.capsule_component.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
            else:
                obj.body.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
    source = ue.spawn_actor(world.DoomBarrel, location=vec(1056, -3616, 21))
    chain = ue.spawn_actor(world.DoomBarrel, location=vec(1096, -3616, 21))
    near = ue.spawn_actor(monsters.DoomDemon, location=vec(1136, -3616, 28))
    far = ue.spawn_actor(monsters.DoomDemon, location=vec(856, -3616, 28))
    assert source and chain and near and far
    mode.objects.extend((source, chain, near, far))
    near.health = far.health = 500
    near.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
    far.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
    player.set_actor_location(vec(1156, -3616, 28), False, True)
    mode.health, mode.armor = 500, 0
    source.hurt(25)
    assert source.exploded and chain.exploded, "Barrel chain reaction"
    assert near.health < 500 and far.health == 500, "Barrel radius damage"
    assert mode.health < 500, "Barrel damages player"

    chain.set_actor_location(vec(10000, 10000, 1000), False, True)
    chain.body.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
    near.set_actor_location(vec(10000, 10000, 1000), False, True)
    near.capsule_component.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
    protected = ue.spawn_actor(monsters.DoomDemon, location=vec(976, -3616, 28))
    wall = ue.spawn_actor(world.DoomGeometry, location=vec(1016, -3616, 0))
    assert protected and wall
    protected.health = 500
    protected.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
    mode.objects.extend((protected, wall))
    wall.mesh.set_collision_profile_name("BlockAll")
    wall.mesh.use_complex_as_simple_collision = True
    section(
        wall.mesh,
        0,
        [
            ue.Vector(0, -160 * SCALE, 0),
            ue.Vector(0, 160 * SCALE, 0),
            ue.Vector(0, 160 * SCALE, 128 * SCALE),
            ue.Vector(0, -160 * SCALE, 128 * SCALE),
        ],
        [0, 1, 2, 0, 2, 3],
        [ue.Vector2D(0, 0), ue.Vector2D(1, 0), ue.Vector2D(1, 1), ue.Vector2D(0, 1)],
        1,
        mode.material("STARTAN3", sector=mode.sector_at(1016, -3616)),
    )
    await agent.frames(1)
    wall_source = ue.spawn_actor(world.DoomBarrel, location=vec(1056, -3616, 21))
    assert wall_source
    mode.objects.append(wall_source)
    wall_source.hurt(25)
    assert wall_source.exploded and protected.health == 500, "Map wall blocks barrel radius damage"

    # Infighting: damage from a monster retargets the victim, same-species missiles do not hurt,
    # Cyberdemons ignore splash, and barrel explosions credit whoever set them off.
    def isolated(prefix: str, kind: int, x: float, y: float) -> Any:
        demon = ue.spawn_actor(monsters.DoomDemon, location=vec(x, y, 1000))
        assert demon
        demon.prefix, demon.type_id, demon.health = prefix, kind, 500
        demon.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
        mode.objects.append(demon)
        return demon

    imp = isolated("TROO", 3001, 10000, 10000)
    zombie = isolated("POSS", 3004, 10000, 10300)
    assert imp.current_target() is player, "Monsters target the player by default"
    imp.hurt(10, source=zombie)
    assert imp.current_target() is zombie and imp.grudge > 0, "Infighting retarget"
    imp.hurt(10, source=player)
    assert imp.current_target() is zombie, "A grudge keeps the target"
    imp.grudge = 0.0
    imp.hurt(10, source=imp)
    assert imp.current_target() is zombie and imp.grudge == 0.0, "Never targets itself"
    victim = isolated("TROO", 3001, 10000, 10600)
    imp.hurt(10, source=victim)
    assert imp.current_target() is victim
    victim.hurt(1000)
    assert imp.current_target() is player and imp.grudge == 0.0, "Dead target returns to the player"
    imp.hurt(10, source=player)
    assert imp.current_target() is player, "Player damage keeps the player as target"

    imp_a = isolated("TROO", 3001, 10400, 10000)
    imp_b = isolated("TROO", 3001, 10500, 10000)
    bolt = ue.spawn_actor(projectiles.DoomProjectile, location=vec(10400, 10000, 1000))
    assert bolt
    bolt.configure((1.0, 0.0, 0.0), imp_a, "BAL1A0", 350, 3, 0, "monster")
    mode.objects.append(bolt)
    for _ in range(60):
        await agent.frames(1)
        if bolt.stage == "explosion":
            break
    assert bolt.stage == "explosion" and imp_b.health == 500, "Same-species missile deals no damage"

    cyber = isolated("CYBR", 16, 10700, 10300)
    grunt = isolated("TROO", 3001, 10700, 10360)
    shooter = isolated("POSS", 3004, 10900, 10300)
    barrel = ue.spawn_actor(world.DoomBarrel, location=vec(10750, 10330, 1000))
    assert barrel
    mode.objects.append(barrel)
    barrel.hurt(25, source=shooter)
    assert barrel.exploded and cyber.health == 500, "Cyberdemon takes no splash damage"
    assert grunt.health < 500 and grunt.current_target() is shooter, "Barrel splash credits its source"

    # Waking up and the choice to fire.
    probe = isolated("POSS", 3004, 10000, 11000)
    probe.reactiontime = 8
    assert not probe.decides_to_fire(player, visible=True, roll=0.99), "No missile before reactiontime ends"
    probe.reactiontime = 0
    assert probe.decides_to_fire(player, visible=True, roll=0.99), (
        "Far targets are shot at when the roll is high"
    )
    assert not probe.decides_to_fire(player, visible=True, roll=0.39), "A low roll holds fire"
    assert not probe.decides_to_fire(player, visible=False, roll=0.99), "No missile without sight"
    probe.reactiontime, probe.provoked = 5, True
    assert probe.decides_to_fire(player, visible=True, roll=0.0) and not probe.provoked, (
        "Provoked fires back once"
    )

    mode.position()
    player = ue.GameplayStatics.get_player_pawn(0)
    assert player is not None
    # The start is crowded with earlier test actors: move to an open spot at a pickup far from it.
    start = xy(player)
    spot = next(
        t for t in mode.data["things"] if t[3] in (2007, 2008, 2011, 2012) and math.dist(start, t[:2]) > 800
    )
    player.set_actor_location(vec(spot[0], spot[1], mode.floor(spot[0], spot[1]) + 29), False, True)
    await agent.frames(2)
    px, py = xy(player)
    mode.sound_targets = {}

    def spawn_at(x: float, y: float, facing: float, ambush: bool = False) -> Any:
        demon = ue.spawn_actor(monsters.DoomDemon, location=vec(x, y, mode.floor(x, y) + 29))
        assert demon
        demon.facing, demon.ambush = facing, ambush
        mode.objects.append(demon)
        return demon

    for degrees in range(0, 360, 30):
        dx, dy = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
        behind = spawn_at(px + dx * 100, py + dy * 100, degrees)  # Faces away from the player.
        await agent.frames(2)
        if behind.is_valid() and behind.sees(player):
            break
        if behind.is_valid():
            behind.destroy_actor()
    else:
        raise AssertionError("No open spot next to the player start")
    assert not behind.look(mode, player), "A monster behind the player stays asleep"
    behind.facing = degrees + 180
    assert behind.look(mode, player), "A monster facing the player sees it"
    behind.destroy_actor()
    close = spawn_at(px + dx * 56, py + dy * 56, degrees)
    await agent.frames(2)
    assert close.is_valid() and close.sees(player)
    assert close.look(mode, player), "A monster within melee range notices the player from any side"
    close.destroy_actor()

    def alert(open_doors: bool) -> set[int]:
        for door in mode.doors.values():
            door["height"] = door["target"] if open_doors else door["closed"]
        mode.sound_targets = {}
        mode.noise_alert(player)
        return set(mode.sound_targets)

    def hidden_spawn(sectors: list[int], ambush: bool = False) -> Any:
        for sector in sectors:
            for line in mode.data["lines"]:
                a, b = mode.data["vertices"][line["a"]], mode.data["vertices"][line["b"]]
                for side in (8, -8):
                    x = (a[0] + b[0]) / 2 + (b[1] - a[1]) / max(
                        1.0, math.hypot(b[0] - a[0], b[1] - a[1])
                    ) * side
                    y = (a[1] + b[1]) / 2 - (b[0] - a[0]) / max(
                        1.0, math.hypot(b[0] - a[0], b[1] - a[1])
                    ) * side
                    if mode.sector_at(x, y) != sector:
                        continue
                    demon = spawn_at(x, y, 0.0, ambush)
                    if demon.is_valid() and not demon.sees(player):
                        return demon
                    if demon.is_valid():
                        demon.destroy_actor()
        return None

    start_sector = mode.sector_at(px, py)
    closed = alert(False)
    assert start_sector in closed and len(closed) > 1, "Noise floods the player's sector and its neighbours"
    opened = alert(True)
    assert closed < opened, "Open doors let the noise through"
    awake_candidates = [sector for sector in closed if sector != start_sector]
    hidden = [sector for sector in opened - closed]
    sleeper = hidden_spawn(awake_candidates)
    ambusher = hidden_spawn(awake_candidates, True)
    behind_door = hidden_spawn(hidden)
    await agent.frames(2)
    assert sleeper and ambusher and behind_door, "Test monsters placed out of sight"
    alert(False)
    assert sleeper.look(mode, player), "Noise wakes a monster in a connected sector"
    assert not ambusher.look(mode, player), "An ambush monster out of sight ignores the noise"
    assert not behind_door.look(mode, player), "A closed door blocks the noise"
    alert(True)
    assert behind_door.look(mode, player), "The noise passes once the door is open"
    mode.sound_targets = {}
    assert not sleeper.look(mode, player), "Monsters sleep without noise"

    # The console cheats of every mode (IDCLIP, IDBEHOLD, IDCHOPPERS, IDMYPOS, IDDT, IDMUS).
    mode.restart()
    mode.testing = True
    ps = mode.primary()
    assert ps is not None
    run = lambda text: console.execute(mode, text, controller)  # noqa: E731
    assert run("idclip") == "NOCLIP ON" and ps.noclip
    await agent.frames(3)
    player = ue.GameplayStatics.get_player_pawn(0)
    assert isinstance(player, player_mod.DoomMarine) and player.noclip_applied, "IDCLIP applies to the marine"
    assert player.character_movement.movement_mode == ue.EMovementMode.MOVE_Flying
    assert run("idclip") == "NOCLIP OFF" and not ps.noclip
    await agent.frames(3)
    assert (
        not player.noclip_applied and player.character_movement.movement_mode == ue.EMovementMode.MOVE_Walking
    )
    for letter, power, seconds in (
        ("v", "invulnerability", 30),
        ("i", "invisibility", 60),
        ("r", "suit", 60),
    ):
        assert run("idbehold" + letter).endswith("ON") and abs(getattr(ps, power) - seconds) < 1, power
        assert run("idbehold" + letter).endswith("OFF") and getattr(ps, power) == 0, power
    assert run("idbeholdl").endswith("ON") and ps.light_visor > 100
    assert run("idbeholdl").endswith("OFF") and ps.light_visor == 0
    assert run("idbeholds") == "BERSERK ON" and ps.berserk and ps.weapon == "fist"
    assert run("idbeholds") == "BERSERK OFF" and not ps.berserk
    assert run("idbeholda") == "ALL MAP ON" and ps.all_map
    assert run("idbeholda") == "ALL MAP OFF" and not ps.all_map
    assert "IDBEHOLD" in run("idbehold") and "IDBEHOLD" in run("idbeholdz")
    ps.weapons.discard("chainsaw")
    assert run("idchoppers") == "CHAINSAW" and "chainsaw" in ps.weapons
    controller.set_control_rotation(ue.Rotator(0, -90, 0))
    here = run("idmypos")
    assert here.startswith("ANG=90 X=") and abs(float(here.split("X=")[1].split()[0]) - xy(player)[0]) <= 1, (
        here
    )
    assert run("iddt") == "MAP SHOWS EVERY LINE" and mode.automap_level == 1
    assert run("iddt") == "MAP SHOWS EVERY LINE AND THING" and mode.automap_level == 2
    assert run("iddt") == "MAP AS IT IS" and mode.automap_level == 0
    assert run("idmus13") == "CHANGING MUSIC TO E1M3" and mode.music.current == "D_E1M3.mid"
    assert run("idmus99").startswith("USAGE") and run("idmus").startswith("USAGE")
    assert run("iddqd") == "GOD MODE ON" and ps.god_mode and run("iddqd") == "GOD MODE OFF"
    assert run("idfa") == "FULL ARSENAL" and ps.weapons >= {"bfg", "chainsaw"} and not ps.keys
    assert run("idkfa") == "FULL ARSENAL AND KEYS" and ps.keys == {"blue", "yellow", "red"}
    assert run("idxyz").startswith("UNKNOWN")
    await check_crushers(mode)
    campaign.load_level(mode, "E1M1", 3)
    mode.testing = True
    await agent.frames(20)
    mode.music.stop()
    mode.restart()
    mode.testing = True
    assert mode.health == 100 and not mode.won and mode.kills == 0
    mode.music.stop()
    return dict(
        map="E1M1",
        sectors=88,
        lines=486,
        enemies=mode.total,
        textures=len(mode.data["textures"]),
        original_music=True,
        native_collision=True,
        doors=True,
        lifts_and_floors=True,
        monster_actions=True,
        barrels=True,
        vanilla_wake_up=True,
        exit=True,
        restart=True,
        weapon_aim=True,
        radius_damage=True,
        unlit=True,
        crushers=True,
    )

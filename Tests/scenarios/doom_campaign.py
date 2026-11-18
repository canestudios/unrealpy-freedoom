"""Native Unreal Engine integration check for the full Ultimate Doom campaign.

Run in the game with `-UnrealPySelfHost -UnrealPyRun=Tests/scenarios/doom_campaign.py:demo` (README.md, Test).
It needs the extracted Doom data and its rendered music, and skips cleanly, reporting `skipped`, when no data
is available.
"""

from __future__ import annotations

from typing import Any

import ue
from doom import campaign, geometry, rules, specials
from doom import runtime as g
from doom.dataset import ASSETS, NAME, extracted, save_root
from ue import agent


def _enemy_count(data: dict[str, Any], skill: int) -> int:
    flag = rules.skill_flag(skill)
    return sum(
        1
        for _, _, _, kind, flags in data["things"]
        if flags & flag and not flags & 16 and kind in rules.MONSTERS
    )


def _missing_playable_types(data: dict[str, Any]) -> set[int]:
    missing = set()
    starts = {1, 2, 3, 4, 11, 14}
    for _, _, _, kind, flags in data["things"]:
        if kind in starts or not flags & 7 or flags & 16:
            continue
        if kind in rules.MONSTERS or kind == 2035:
            continue
        sprite = g.ITEMS.get(kind, g.DECOR.get(kind))
        if sprite is None or sprite not in data["sprites"]:
            missing.add(int(kind))
    return missing


def _check_live_walls(mode: Any, player: ue.Actor) -> int:
    """Trace real collision after changing floors and doors in every campaign map."""
    lower = [f for f in mode.wall_faces if not f["upper"] and mode.movers[f["oi"]]["actor"]]
    upper = [
        f
        for f in mode.wall_faces
        if f["upper"]
        and f["oi"] in mode.doors
        and mode.doors[f["oi"]]["actor"]
        and f["bounds"][1] - f["bounds"][0] > 16
    ]
    checks = 0
    for face in [*lower[:2], *upper[:1]]:
        sector = face["oi"]
        state = mode.doors[sector] if face["upper"] else mode.movers[sector]
        field = "height" if face["upper"] else "offset"
        original = state[field]
        if face["upper"]:
            state[field] = original + 16
        else:
            state[field] = mode.sector_floor(face["si"]) + 32 - mode.data["sectors"][sector]["floor"]
        try:
            state["actor"].set_actor_location(ue.Vector(0, 0, state[field] * g.SCALE), False, True)
            geometry.refresh(mode)
            low, high, _ = face["bounds"]
            assert high > low, (mode.marker, "wall has no extent", face["line"])
            a, b = face["a"], face["b"]
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = (dx * dx + dy * dy) ** 0.5
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            nx, ny = -dy / length * 2, dx / length * 2
            hit, _ = g.ray(
                g.vec(mx + nx, my + ny, (low + high) / 2),
                g.vec(mx - nx, my - ny, (low + high) / 2),
                [player, *mode.objects],
            )
            assert hit == mode.wall_geometry, (mode.marker, "live wall gap", face["line"])
            checks += 1
        finally:
            state[field] = original
            state["actor"].set_actor_location(ue.Vector(0, 0, original * g.SCALE), False, True)
            geometry.refresh(mode)
    return checks


async def demo(_args: list[str]) -> dict[str, Any]:
    if not extracted():
        return dict(skipped=f"no extracted Doom data for data set {NAME!r} in {ASSETS}; see README.md")
    slots = (0, 4)
    save_dir = save_root() / "saves"
    backups = {
        slot: (save_dir / f"slot-{slot}.json").read_bytes()
        if (save_dir / f"slot-{slot}.json").exists()
        else None
        for slot in slots
    }
    missing_thing_types: set[int] = set()
    live_wall_checks = 0
    try:
        agent.set_fixed_timestep(1 / 60)
        g.play([])
        for _ in range(120):
            await agent.frames(1)
            mode = g.mode_now()
            player = ue.GameplayStatics.get_player_pawn(0)
            if mode is not None and isinstance(player, g.DoomMarine) and mode.positioned:
                break
        else:
            raise AssertionError("Doom campaign mode did not position the player")

        assert mode.menu == "main", f"Expected main menu, got {mode.menu!r}"
        assert len(mode.maps) == 36, f"Expected all 36 maps, got {len(mode.maps)}"
        controller = ue.GameplayStatics.get_player_controller(0)
        assert isinstance(controller, g.DoomController)
        controller.automated = True
        mode.testing = True

        markers = ["E1M1"] if "quick" in _args else mode.maps
        for marker in markers:
            campaign.load_level(mode, marker, 3)
            await agent.frames(20)
            player = ue.GameplayStatics.get_player_pawn(0)
            assert isinstance(player, g.DoomMarine)
            assert mode.marker == marker and mode.health == 100, f"{marker}: marker or starting health"
            x, y = g.xy(player)
            floor = mode.floor(x, y)
            player_height = float(player.get_actor_location()[2]) / g.SCALE
            assert abs(player_height - floor - 28) <= 4, (
                f"{marker}: player height {player_height}, floor {floor}"
            )

            expected_enemies = _enemy_count(mode.data, 3)
            assert len(mode.enemies) == expected_enemies, (
                f"{marker}: spawned {len(mode.enemies)} enemies, expected {expected_enemies}"
            )
            for enemy in mode.enemies:
                assert all(
                    hasattr(enemy, field)
                    for field in ("type_id", "health", "spawn_health", "attack_sound", "prefix")
                ), f"{marker}: incomplete enemy stats for {getattr(enemy, 'type_id', '?')}"
            for weapon in rules.WEAPONS.values():
                assert weapon["idle"] in mode.data["sprites"], (
                    f"{marker}: missing weapon sprite {weapon['idle']}"
                )
            assert mode.music.ready, f"{marker}: music failed: {mode.music.error}"

            supported = (
                set(specials.ACTIONS) | set(rules.EXIT_SPECIALS) | set(rules.MANUAL_DOORS) | {48, 65535}
            )
            missing_specials = sorted(
                {
                    line["special"]
                    for line in mode.data["lines"]
                    if line["special"] and line["special"] not in supported
                }
            )
            assert not missing_specials, f"{marker}: unsupported linedef specials {missing_specials}"
            missing_thing_types.update(_missing_playable_types(mode.data))
            live_wall_checks += _check_live_walls(mode, player)

        # Every skill must spawn exactly the things selected by its Doom skill flags.
        for skill in range(1, 6):
            campaign.load_level(mode, "E1M1", skill)
            await agent.frames(20)
            assert len(mode.enemies) == _enemy_count(mode.data, skill), f"skill {skill}: enemy count"
            assert mode.health == 100
            mode.armor = 0
            mode.hurt(10)
            expected_health = 95 if skill == 1 else 90
            assert mode.health == expected_health, f"skill {skill}: damage gave health {mode.health}"

        ue.log(
            f"Campaign checked {len(markers)} maps and 5 skills; "
            f"missing thing types: {sorted(missing_thing_types)}"
        )
        campaign.load_level(mode, "E1M1", 3)
        await agent.frames(20)
        player = ue.GameplayStatics.get_player_pawn(0)
        assert isinstance(player, g.DoomMarine)
        mode.weapons = set(rules.WEAPONS)
        mode.bullets, mode.shells, mode.rockets, mode.cells = 500, 500, 500, 500
        original_location = player.camera.get_world_location().copy()
        for weapon in rules.WEAPONS:
            mode.weapon = weapon
            mode.cooldown = 0
            mode.invulnerability = 30
            mode.health = 500
            distance = 30 if weapon in ("fist", "chainsaw") else 80
            # Shots leave along the weapon sprite's x position, which differs per data set.
            aim = mode.aim_direction(player)
            barrel_location = original_location.copy()
            for axis in range(3):
                barrel_location[axis] += float(aim[axis]) * distance * g.SCALE
            barrel_location[2] -= 8 * g.SCALE
            barrel = ue.spawn_actor(g.DoomBarrel, location=barrel_location)
            assert barrel
            barrel.image("BAR1A0")
            mode.objects.append(barrel)
            mode.fire()
            await agent.frames(60)
            assert barrel.exploded or barrel.health < 20, f"{weapon}: shot did not hit its barrel"
            mode.objects.remove(barrel)
            barrel.destroy_actor()

        # Save and reload a representative state, including objects and moving geometry.
        campaign.load_level(mode, "E1M1", 3)
        await agent.frames(20)
        player = ue.GameplayStatics.get_player_pawn(0)
        assert isinstance(player, g.DoomMarine) and mode.enemies and mode.objects
        mode.weapons = set(rules.WEAPONS)
        mode.weapon = "plasma"
        mode.health, mode.armor = 73, 100
        mode.bullets, mode.shells, mode.rockets, mode.cells = 31, 9, 7, 90
        mode.keys = {"blue"}
        enemy = mode.enemies[0]
        enemy.hurt(7)
        expected_enemy_health = enemy.health
        item = next(
            (obj for obj in mode.objects if isinstance(obj, g.DoomSprite) and hasattr(obj, "taken")), None
        )
        assert item is not None
        item.taken = True
        item.set_actor_hidden_in_game(True)
        door_index = next((index for index, door in mode.doors.items() if door["actor"]), None)
        assert door_index is not None
        mode.open_door(door_index)
        await agent.frames(10)
        expected_door_height = mode.doors[door_index]["height"]
        expected_player_location = [float(value) for value in player.get_actor_location()]
        item_id = item.thing_id
        assert campaign.save_game(mode, 4), "Could not save slot 4"

        campaign.load_level(mode, "E2M1", 3)
        assert campaign.load_game(mode, 4), "Could not reload slot 4"
        player = ue.GameplayStatics.get_player_pawn(0)
        assert mode.marker == "E1M1" and mode.health == 73 and mode.armor == 100
        assert (mode.bullets, mode.shells, mode.rockets, mode.cells) == (31, 9, 7, 90)
        assert mode.weapon == "plasma" and mode.weapons == set(rules.WEAPONS) and mode.keys == {"blue"}
        restored_enemy = next(obj for obj in mode.enemies if obj.thing_id == enemy.thing_id)
        assert restored_enemy.health == expected_enemy_health
        restored_item = next(obj for obj in mode.objects if obj.thing_id == item_id)
        assert restored_item.taken and restored_item.hidden
        restored_door = mode.doors[door_index]
        assert abs(restored_door["height"] - expected_door_height) < 0.001
        assert restored_door["actor"] is not None
        geometry_z = float(restored_door["actor"].get_actor_location()[2])
        assert abs(geometry_z - expected_door_height * g.SCALE) < 0.01, (
            "Door geometry offset was not restored"
        )
        assert player is not None and all(
            abs(float(player.get_actor_location()[i]) - expected_player_location[i]) < 0.01 for i in range(3)
        )

        campaign.finish_level(mode, secret=True)
        campaign.advance(mode)
        assert mode.marker == "E1M9"
        campaign.finish_level(mode)
        campaign.advance(mode)
        assert mode.marker == "E1M4"
        campaign.load_level(mode, "E2M8", 3)
        campaign.finish_level(mode)
        campaign.advance(mode)
        assert mode.menu == "ending" and mode.finished_episode
        return dict(
            maps=len(markers),
            difficulties=5,
            weapons=len(rules.WEAPONS),
            live_wall_checks=live_wall_checks,
            save_restore=True,
            secret_progression=True,
            missing_thing_types=sorted(missing_thing_types),
        )
    finally:
        for slot, data in backups.items():
            path = save_dir / f"slot-{slot}.json"
            if data is None:
                if path.exists():
                    path.unlink()
            else:
                save_dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

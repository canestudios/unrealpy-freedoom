"""Vanilla Doom linedef actions, implemented through native procedural mesh movement."""

from __future__ import annotations

import math
from typing import Any

import ue
from doom.common import TIC, xy
from doom.rules import (
    BARREL_HEIGHT,
    CRUSHERS,
    EXIT_SPECIALS,
    ITEM_HEIGHT,
    LOCKS,
    MANUAL_DOORS,
    MARINE_HEIGHT,
    MONSTER_HEIGHT,
    SECRET_EXITS,
    SLOWING_CRUSHERS,
)

# Activation is kept separate from the action: a walk trigger is not a use switch.
WALK = {
    2,
    3,
    4,
    5,
    8,
    10,
    12,
    13,
    16,
    17,
    19,
    22,
    25,
    30,
    35,
    36,
    37,
    38,
    39,
    40,
    44,
    52,
    53,
    54,
    56,
    57,
    58,
    59,
    72,
    73,
    74,
    75,
    76,
    77,
    79,
    80,
    81,
    82,
    83,
    84,
    86,
    87,
    88,
    89,
    90,
    91,
    92,
    93,
    94,
    95,
    96,
    97,
    98,
    100,
    104,
    105,
    106,
    107,
    108,
    109,
    110,
    119,
    120,
    121,
    124,
    125,
    126,
    128,
    129,
    130,
    141,
}
SHOOT = {24, 46, 47}
REPEAT = {
    1,
    26,
    27,
    28,
    42,
    43,
    45,
    46,
    60,
    61,
    62,
    63,
    64,
    65,
    66,
    67,
    68,
    69,
    70,
    72,
    73,
    74,
    75,
    76,
    77,
    79,
    80,
    81,
    82,
    83,
    84,
    86,
    87,
    88,
    89,
    90,
    91,
    92,
    93,
    94,
    95,
    96,
    97,
    98,
    99,
    105,
    106,
    107,
    114,
    115,
    116,
    117,
    120,
    123,
    126,
    128,
    129,
    132,
    134,
    136,
    138,
    139,
}
GROUPS = {
    "door_open": {
        2,
        31,
        32,
        33,
        34,
        46,
        61,
        86,
        103,
        106,
        109,
        112,
        115,
        118,
        133,
        134,
        135,
        136,
        137,
        99,
    },
    "door_close": {3, 42, 75, 107, 110, 113, 116},
    "door_wait": {1, 4, 26, 27, 28, 29, 63, 90, 105, 108, 111, 114, 117},
    "door_close_wait": {16, 76},
    "floor_raise": {5, 24, 64, 91, 101},
    "floor_lower": {19, 45, 83, 102},
    "floor_lowest": {23, 38, 60, 82},
    "floor_turbo_lower": {36, 70, 71, 98},
    "floor_change_lower": {37, 84},
    "floor_next": {18, 20, 22, 47, 68, 69, 95, 119, 128},
    "floor_turbo_raise": {129, 130, 131, 132},
    "floor_24": {58, 59, 66, 92, 93},
    "floor_32": {14, 67},
    "floor_texture": {30, 96},
    "floor_crush": {55, 56, 65, 94},
    "lift": {10, 21, 62, 88, 120, 121, 122, 123},
    "perpetual_lift": {53, 87},
    "stop_lift": {54, 89},
    "stairs": {7, 8, 100, 127},
    "donut": {9},
    "crush": {6, 25, 49, 73, 77, 141},
    "ceiling_lower": {41, 43, 44, 72},
    "ceiling_raise": {40},
    "stop_crush": {57, 74},
    "teleport": {39, 97, 125, 126},
    "light": {12, 13, 17, 35, 79, 80, 81, 104, 138, 139},
}
ACTIONS = {number: action for action, numbers in GROUPS.items() for number in numbers}
FAST = set(range(99, 138)) | {36, 70, 71, 77, 98}


def targets(mode: Any, line: dict[str, Any]) -> list[int]:
    if line["special"] in MANUAL_DOORS and line["left"] != 65535:
        return [mode.data["sides"][line["left"]]["sector"]]
    return [
        i for i, sector in enumerate(mode.data["sectors"]) if line["tag"] and sector["tag"] == line["tag"]
    ]


def plan(mode: Any) -> None:
    sectors = mode.data["sectors"]
    # All floors get their own native mesh group: stairs/donut propagation can reach untagged sectors.
    for i, sector in enumerate(sectors):
        neighbours = mode.neighbours(i)
        low = min([sector["floor"]] + [sectors[n]["floor"] for n in neighbours])
        mode.movers[i] = dict(
            actor=None,
            kind="floor",
            speed=35.0,
            target=low - sector["floor"],
            offset=0.0,
            goal=0.0,
            wait=0.0,
            active=False,
        )
    door_sectors = {i for i, sector in enumerate(sectors) if sector["floor"] == sector["ceiling"]}
    ceiling_sectors = set()
    for line in mode.data["lines"]:
        action = ACTIONS.get(line["special"], "")
        if action.startswith("door_"):
            door_sectors.update(targets(mode, line))
        if action in ("crush", "ceiling_lower", "ceiling_raise", "stop_crush"):
            ceiling_sectors.update(targets(mode, line))
    for i in door_sectors:
        sector = sectors[i]
        adjacent = [sectors[n]["ceiling"] for n in mode.neighbours(i)]
        mode.doors[i] = dict(
            actor=None,
            height=0.0,
            target=min(adjacent, default=sector["ceiling"] + 128) - sector["ceiling"] - 4,
            opened=False,
            timer=0.0,
            closed=0.0,
            speed=80.0,
            reopen=False,
        )
    for i in ceiling_sectors - door_sectors:
        mode.ceilings[i] = dict(
            actor=None,
            offset=0.0,
            goal=0.0,
            speed=35.0,
            active=False,
            low=sectors[i]["floor"] + 8 - sectors[i]["ceiling"],
            high=0.0,
            cycle=False,
            crush=False,
            slows=False,
            base_speed=35.0,
        )


def neighbours(mode: Any, index: int) -> list[dict[str, Any]]:
    return [mode.data["sectors"][i] for i in mode.neighbours(index)]


def activate(mode: Any, index: int, activation: str = "use", who: Any = None) -> bool:
    """Trigger a linedef special for marine `who` (the player at this machine when None)."""
    ps = mode.resolve(who)
    line = mode.data["lines"][index]
    special = line["special"]
    if (activation == "walk") != (special in WALK) and special not in SHOOT:
        return False
    if special in SHOOT and activation != "shoot":
        return False
    if activation == "shoot" and special not in SHOOT:
        return False
    if index in mode.triggered and special not in REPEAT:
        return False
    if special in (125, 126):
        # These teleporters are monster-only in the original game.
        return False
    colour = LOCKS.get(special)
    if bool(colour) and (ps is None or colour not in ps.keys):
        mode.tell(ps, f"YOU NEED THE {colour.upper()} KEY", 2.0)
        mode.sound("DSNOWAY", who=ps)
        return False
    if special in EXIT_SPECIALS:
        from doom.campaign import finish_level

        finish_level(mode, special in SECRET_EXITS)
        mode.triggered.add(index)
        return True
    action = ACTIONS.get(special)
    indices = targets(mode, line)
    if not bool(action) or not indices:
        return False
    if action == "teleport":
        moved = teleport(mode, indices, ps.get_pawn() if ps is not None else None)
        if moved and special not in REPEAT:
            mode.triggered.add(index)
        return moved
    for i in indices:
        sector = mode.data["sectors"][i]
        adjacent = neighbours(mode, i)
        floors = [s["floor"] for s in adjacent]
        ceilings = [s["ceiling"] for s in adjacent]
        base = sector["floor"]
        if action.startswith("door_"):
            door = mode.doors.get(i)
            if door is None:
                continue
            door["speed"] = 280.0 if special in FAST else 80.0
            door["stays"] = action == "door_close"  # a blocked closing door reopens, except these
            door["closed"] = sector["floor"] - sector["ceiling"]
            if action in ("door_close", "door_close_wait"):
                door["opened"] = False
                door["reopen"] = action == "door_close_wait"
                door["timer"] = 30.0
            else:
                door["opened"] = True
                door["timer"] = math.inf if action == "door_open" else 4.0
                door["reopen"] = False
            mode.sound("DSDOROPN" if door["opened"] else "DSDORCLS")
        elif action in ("crush", "ceiling_lower", "ceiling_raise", "stop_crush"):
            ceiling = mode.ceilings.get(i)
            if ceiling is None:
                continue
            ceiling["active"] = action != "stop_crush"
            ceiling["cycle"] = action == "crush"
            ceiling["speed"] = ceiling["base_speed"] = 70.0 if special in (6, 77) else 35.0
            ceiling["crush"], ceiling["slows"] = special in CRUSHERS, special in SLOWING_CRUSHERS
            ceiling["goal"] = (
                max(ceilings, default=sector["ceiling"]) - sector["ceiling"]
                if action == "ceiling_raise"
                else ceiling["low"]
            )
            if special == 40:
                mover = mode.movers[i]
                mover.update(goal=min([base] + floors) - base, active=True)
        elif action == "stairs":
            build_stairs(mode, i, 16 if special in (100, 127) else 8)
        elif action == "donut":
            donut(mode, i)
        elif action == "light":
            # Plain unlit rendering intentionally has no sector brightness modulation.
            pass
        else:
            mover = mode.movers[i]
            if action == "stop_lift":
                mover["active"] = False
                continue
            if action == "floor_lower":
                target = max([f for f in floors if f < base], default=base)
            elif action in ("floor_lowest", "floor_change_lower", "lift", "perpetual_lift"):
                target = min([base] + floors)
            elif action == "floor_turbo_lower":
                target = max([f for f in floors if f < base], default=base)
                if target != base:
                    target += 8
            elif action in ("floor_next", "floor_turbo_raise"):
                target = min([f for f in floors if f > base], default=base)
            elif action in ("floor_raise", "floor_crush"):
                target = min([sector["ceiling"]] + ceilings) - (8 if action == "floor_crush" else 0)
            elif action in ("floor_24", "floor_32"):
                target = base + (24 if action == "floor_24" else 32)
            elif action == "floor_texture":
                heights = []
                for boundary in mode.data["lines"]:
                    if boundary["left"] != 65535:
                        for side in (boundary["left"], boundary["right"]):
                            data = mode.data["sides"][side]
                            if data["sector"] == i and data["lower"] in mode.data["textures"]:
                                heights.append(mode.data["textures"][data["lower"]][1])
                target = base + min(heights, default=24)
            else:
                continue
            mover.update(
                target=target - base,
                goal=target - base,
                active=True,
                kind="lift" if action == "lift" else "perpetual" if action == "perpetual_lift" else "floor",
                speed=280.0
                if special in (120, 121, 122, 123)
                else 140.0
                if special in FAST or action == "lift"
                else 35.0,
                high=max([base] + floors) - base,
                wait=0.0,
            )
            mode.sound("DSPSTART" if action == "lift" else "DSSTNMOV")
    if special not in REPEAT:
        mode.triggered.add(index)
    from doom.campaign import set_switch

    set_switch(mode, index, special in REPEAT)
    return True


def build_stairs(mode: Any, first: int, step: int) -> None:
    seen, index, height = set(), first, mode.data["sectors"][first]["floor"]
    texture = mode.data["sectors"][first]["floor_tex"]
    while index not in seen:
        seen.add(index)
        height += step
        mover = mode.movers[index]
        target = height - mode.data["sectors"][index]["floor"]
        mover.update(goal=target, target=target, active=True, speed=140.0 if step == 16 else 8.75)
        candidates = []
        for line in mode.data["lines"]:
            if line["left"] == 65535:
                continue
            right, left = (
                mode.data["sides"][line["right"]]["sector"],
                mode.data["sides"][line["left"]]["sector"],
            )
            if right == index and left not in seen and mode.data["sectors"][left]["floor_tex"] == texture:
                candidates.append(left)
        if not candidates:
            break
        index = candidates[0]


def donut(mode: Any, index: int) -> None:
    ring = next(iter(mode.neighbours(index)), None)
    if ring is None:
        return
    outside = next((i for i in mode.neighbours(ring) if i != index), None)
    if outside is None:
        return
    height = mode.data["sectors"][outside]["floor"]
    for i in (index, ring):
        target = height - mode.data["sectors"][i]["floor"]
        mode.movers[i].update(goal=target, target=target, active=True, speed=17.5)


def teleport(mode: Any, indices: list[int], player: Any = None) -> bool:
    from doom.campaign import game

    g = game()
    for x, y, angle, kind, _ in mode.data["things"]:
        if kind != 14 or mode.sector_at(x, y) not in indices:
            continue
        if player is None:
            player = ue.GameplayStatics.get_player_pawn(0)
        if not player:
            return False
        mode.effect("teleport", g.vec(*g.xy(player), mode.floor(*g.xy(player))))
        ahead = math.radians(angle)
        mode.effect("teleport", g.vec(x + 20 * math.cos(ahead), y + 20 * math.sin(ahead), mode.floor(x, y)))
        mode.warp(player, x, y, angle)
        for enemy in mode.enemies:
            if not enemy.dead and math.dist(g.xy(enemy), (x, y)) < 35:
                enemy.hurt(10000)
        ps = mode.resolve(player)
        if ps is not None:
            ps.last_xy = (x, y)
        mode.sound("DSTELEPT", at=player.get_actor_location())
        return True
    return False


def hurt_tic(mode: Any, dt: float) -> bool:
    """Is this frame one where Doom's `leveltime & 3 == 0` lets a crusher hurt (every fourth tic)?"""
    quarter = 4 * TIC
    return int(mode.level_clock / quarter) != int((mode.level_clock - dt) / quarter)


def squeeze(mode: Any, index: int, ceiling_z: float, crush: bool) -> bool:
    """Check what still fits in sector `index` with its ceiling at `ceiling_z`.

    Corpses that no longer fit become gibs and dropped items vanish. True when a live thing no longer fits;
    a crusher then deals 10 damage to it every fourth tic (`mode.crush_now`, set once per frame).
    """
    from doom import monsters, world

    gap = ceiling_z - mode.sector_floor(index)
    if gap >= 110:
        return False
    blocked = False
    hurt = crush and mode.crush_now

    def hit(thing: Any) -> None:
        nonlocal blocked
        blocked = True
        if hurt:
            location = thing.get_actor_location().copy()
            mode.effect("blood", location)
            if isinstance(thing, ue.Pawn) and not isinstance(thing, monsters.DoomDemon):
                mode.hurt(10, who=thing, environment=True)
            else:
                thing.hurt(10)

    for marine in mode.marines():
        ps = marine.doom_state
        if (
            ps is not None
            and not ps.dead
            and not ps.noclip
            and gap < MARINE_HEIGHT
            and mode.sector_at(*xy(marine)) == index
        ):
            hit(marine)
    for obj in mode.objects:
        if not obj.is_valid():
            continue
        if isinstance(obj, monsters.DoomDemon):
            if obj.gibbed or mode.sector_at(*xy(obj)) != index:
                continue
            height = MONSTER_HEIGHT.get(obj.type_id, 56)
            if obj.dead:
                if gap < height // 4:
                    obj.gib()
            elif gap < height:
                hit(obj)
        elif isinstance(obj, world.DoomBarrel):
            if not obj.exploded and gap < BARREL_HEIGHT and mode.sector_at(*xy(obj)) == index:
                hit(obj)
        elif (
            isinstance(obj, world.DoomSprite)
            and obj.dropped
            and not obj.taken
            and gap < ITEM_HEIGHT
            and mode.sector_at(*xy(obj)) == index
        ):
            obj.destroy_actor()
    return blocked


def tick(mode: Any, dt: float) -> None:
    from doom import world
    from doom.campaign import game

    g = game()
    for index, mover in mode.movers.items():
        if not mover.get("active", False):
            continue
        offset, goal = mover["offset"], mover["goal"]
        if offset != goal:
            step = mover["speed"] * dt
            mover["offset"] = min(goal, offset + step) if goal > offset else max(goal, offset - step)
            mode.geo_dirty.add(index)
            world.follow_floor(mode, index)
            if mover["actor"]:
                mover["actor"].set_actor_location(ue.Vector(0, 0, mover["offset"] * g.SCALE), False, True)
            if mover["offset"] == goal:
                mode.sound("DSPSTOP")
                if mover["kind"] in ("lift", "perpetual"):
                    mover["wait"] = 3.0
                else:
                    mover["active"] = False
        elif mover["kind"] in ("lift", "perpetual"):
            mover["wait"] -= dt
            if mover["wait"] <= 0:
                if mover["kind"] == "lift":
                    if goal == 0:
                        mover["active"] = False
                    else:
                        mover["goal"] = 0.0
                else:
                    mover["goal"] = mover["high"] if goal == mover["target"] else mover["target"]
    for index, ceiling in mode.ceilings.items():
        if not ceiling["active"]:
            continue
        offset, goal, step = ceiling["offset"], ceiling["goal"], ceiling["speed"] * dt
        new = min(goal, offset + step) if goal > offset else max(goal, offset - step)
        if new < offset:  # what no longer fits is crushed, or holds a non-crusher back
            squeezed = squeeze(
                mode, index, float(mode.data["sectors"][index]["ceiling"]) + new, ceiling["crush"]
            )
            if squeezed and not ceiling["crush"]:
                continue
            if squeezed and ceiling["slows"]:
                ceiling["speed"] = ceiling["base_speed"] / 8
        ceiling["offset"] = new
        mode.geo_dirty.add(index)
        if ceiling["actor"]:
            ceiling["actor"].set_actor_location(ue.Vector(0, 0, ceiling["offset"] * g.SCALE), False, True)
        if ceiling["offset"] == goal:
            ceiling["speed"] = ceiling["base_speed"]
            if ceiling["cycle"]:
                ceiling["goal"] = ceiling["high"] if goal == ceiling["low"] else ceiling["low"]
            else:
                ceiling["active"] = False


def boss_death(mode: Any, enemy: Any) -> None:
    expected = {"E1M8": "BOSS", "E2M8": "CYBR", "E3M8": "SPID", "E4M6": "CYBR", "E4M8": "SPID"}
    if expected.get(mode.marker) != enemy.prefix:
        return
    if any(not e.dead and e.prefix == enemy.prefix for e in mode.enemies):
        return
    if mode.marker in ("E2M8", "E3M8"):
        from doom.campaign import finish_level

        finish_level(mode)
        return
    for i, sector in enumerate(mode.data["sectors"]):
        if sector["tag"] != 666:
            continue
        if mode.marker == "E4M6" and i in mode.doors:
            mode.open_door(i)
            mode.doors[i]["timer"] = math.inf
        else:
            lowest = min([sector["floor"]] + [s["floor"] for s in neighbours(mode, i)])
            mode.movers[i].update(goal=lowest - sector["floor"], target=lowest - sector["floor"], active=True)

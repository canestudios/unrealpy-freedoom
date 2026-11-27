"""Sprite animations: which frame of a sprite shows when, in game tics (35 a second).

The frame letters are the ones the WAD's sprites carry; the timings are this project's own, chosen by eye and
by feel for each animation (a weapon's cycle also sets its rate of fire, and its shot tics when it hits).
"""

from __future__ import annotations

TIC = 1 / 35

Frames = list[tuple[str, int]]
Action = list[tuple[str, int, bool]]


def steps(letters: str, tics: int | tuple[int, ...]) -> Frames:
    """Frames named by `letters`, each `tics` long (one value, or one per letter); -1 holds forever."""
    lengths = (tics,) * len(letters) if isinstance(tics, int) else tics
    assert len(lengths) == len(letters), letters
    return list(zip(letters, lengths, strict=True))


def lumps(sprite: str, letters: str, tics: int | tuple[int, ...], rotation: str = "0") -> Frames:
    """`steps` with full lump names (sprite + letter + rotation), for things drawn from one view."""
    return [(sprite + letter + rotation, length) for letter, length in steps(letters, tics)]


def action(letters: str, tics: tuple[int, ...], strikes: tuple[int, ...] = ()) -> Action:
    """A monster action: its frames, and the frames (indices into `letters`) on which it strikes."""
    return [(letter, length, index in strikes) for index, (letter, length) in enumerate(steps(letters, tics))]


# Monsters, by sprite prefix. An attack strikes (shoots, bites or charges) as its marked frame begins.
ATTACK_FRAMES: dict[str, Action] = {
    "POSS": action("EFE", (9, 7, 7), (1,)),
    "SPOS": action("EFE", (9, 8, 9), (1,)),
    "TROO": action("EFG", (7, 7, 7), (2,)),
    "SARG": action("EFG", (7, 7, 7), (2,)),
    "HEAD": action("BCD", (6, 6, 6), (2,)),
    "SKUL": action("CDCD", (8, 5, 5, 5), (1,)),
    "BOSS": action("EFG", (7, 7, 7), (2,)),
    "CYBR": action("EFEFEF", (7, 10, 10, 10, 10, 10), (1, 3, 5)),
    "SPID": action("AGHH", (18, 5, 5, 2), (1, 2)),
}

PAIN_FRAMES: dict[str, Action] = {
    "POSS": action("G", (7,)),
    "SPOS": action("G", (7,)),
    "TROO": action("H", (5,)),
    "SARG": action("H", (5,)),
    "HEAD": action("EF", (5, 5)),
    "SKUL": action("E", (5,)),
    "BOSS": action("H", (5,)),
    "CYBR": action("G", (8,)),
    "SPID": action("I", (7,)),
}

# Death: the corpse frame (-1) stays; a lost soul has none and vanishes when its last frame ends.
DEATH_STATES: dict[str, Frames] = {
    "POSS": steps("HIJKL", (6, 6, 6, 6, -1)),
    "SPOS": steps("HIJKL", (6, 6, 6, 6, -1)),
    "TROO": steps("IJKLM", (7, 7, 7, 7, -1)),
    "SARG": steps("IJKLMN", (7, 7, 6, 6, 6, -1)),
    "HEAD": steps("GHIJKL", (7, 7, 7, 7, 7, -1)),
    "SKUL": steps("FGHIJK", 5),
    "BOSS": steps("IJKLMNO", (7, 7, 7, 7, 7, 7, -1)),
    "CYBR": steps("HIJKLMNOP", (9, 9, 9, 9, 9, 9, 9, 9, -1)),
    "SPID": steps("JKLMNOPQRS", (18, 9, 9, 9, 9, 9, 9, 9, 9, -1)),
}

WALK_STATES: dict[str, Frames] = {
    "POSS": steps("ABCD", 7),
    "SPOS": steps("ABCD", 6),
    "TROO": steps("ABCD", 6),
    "SARG": steps("ABCD", 4),
    "HEAD": steps("A", 5),
    "SKUL": steps("AB", 5),
    "BOSS": steps("ABCD", 7),
    "CYBR": steps("ABCD", 7),
    "SPID": steps("ABCDEF", 5),
}

IDLE_STATES: dict[str, Frames] = {prefix: steps("AB", 12) for prefix in WALK_STATES}
IDLE_STATES["HEAD"] = steps("A", 12)

# Animated pick-ups, by thing type: bonuses and the map pulse, spheres and goggles cycle.
ITEM_STATES: dict[int, Frames] = {
    2014: lumps("BON1", "ABCDCB", 5),
    2015: lumps("BON2", "ABCDCB", 5),
    2026: lumps("PMAP", "ABCDCB", 5),
    2013: lumps("SOUL", "ABCD", 5),
    2022: lumps("PINV", "ABCD", 5),
    2024: lumps("PINS", "ABCD", 5),
    2045: lumps("PVIS", "AB", 7),
}

PAIN: dict[str, str] = {prefix: "DSDMPAIN" for prefix in WALK_STATES}
PAIN["POSS"] = PAIN["SPOS"] = "DSPOPAIN"

# Projectiles: (flight loop, impact).
PROJECTILE_STATES: dict[str, tuple[Frames, Frames]] = {
    "imp": (lumps("BAL1", "AB", 3), lumps("BAL1", "CDE", 5)),
    "caco": (lumps("BAL2", "AB", 3), lumps("BAL2", "CDE", 5)),
    "baron": (lumps("BAL7", "AB", 3, "1"), lumps("BAL7", "CDE", 5)),
    "rocket": (lumps("MISL", "A", 4, "1"), lumps("MISL", "BCD", (7, 5, 5))),
    "plasma": (lumps("PLSS", "AB", 5), lumps("PLSE", "ABCDE", 3)),
    "bfg": (lumps("BFS1", "AB", 5), lumps("BFE1", "ABCDEF", 7)),
}

EFFECT_STATES: dict[str, Frames] = {
    "teleport": lumps("TFOG", "ABCDEFGHIJ", 5),
    "item_fog": lumps("IFOG", "ABCDE", 5),  # where an item comes back (altdeath)
    "bfg_hit": lumps("BFE2", "ABCD", 7),
    "blood": lumps("BLUD", "CBA", 7),
    "puff": lumps("PUFF", "ABCD", 3),
}

BARREL_EXPLOSION: Frames = lumps("BEXP", "ABCDE", (4, 4, 6, 8, 8))

# The player's weapons. A cycle's length is the time between shots while the trigger is held.
WEAPON_FRAMES: dict[str, Frames] = {
    "fist": lumps("PUNG", "BCDCB", (4, 5, 6, 4, 4)),
    "chainsaw": lumps("SAWG", "AB", (4, 3)),
    "pistol": lumps("PISG", "ABCB", (3, 5, 4, 6)),
    "shotgun": lumps("SHTG", "ABCDCBA", (10, 6, 6, 5, 6, 6, 3)),
    "chaingun": lumps("CHGG", "AB", (5, 4)),
    "rocket": lumps("MISG", "B", 21),
    "plasma": lumps("PLSG", "AB", (4, 18)),
    "bfg": lumps("BFGG", "AB", (22, 36)),
}

# Muzzle flashes over the weapon: (lump, first tic, tics).
WEAPON_FLASH: dict[str, list[tuple[str, int, int]]] = {
    "pistol": [("PISFA0", 3, 6)],
    "shotgun": [("SHTFA0", 2, 3), ("SHTFB0", 5, 3)],
    "chaingun": [("CHGFA0", 0, 3), ("CHGFB0", 5, 3)],
    "rocket": [("MISFA0", 3, 4), ("MISFB0", 7, 4), ("MISFC0", 11, 4), ("MISFD0", 15, 4)],
    "plasma": [("PLSFA0", 0, 3)],
    "bfg": [("BFGFA0", 22, 10), ("BFGFB0", 32, 6)],
}

# The tics of a cycle at which the weapon fires (or hits).
WEAPON_EVENTS: dict[str, list[int]] = {
    "fist": [9],
    "chainsaw": [0],
    "pistol": [3],
    "shotgun": [2],
    "chaingun": [0, 5],
    "rocket": [7],
    "plasma": [0],
    "bfg": [32],
}

# Weapons that fire again this many tics into their cycle while the trigger is held (the rest of the cycle
# is the cool-down after the trigger is released).
WEAPON_REFIRE: dict[str, int] = {"plasma": 4}


def state_frame(states: Frames, elapsed: float, loop: bool = False) -> str:
    duration = sum(tics for _, tics in states if tics > 0) * TIC
    if loop and duration > 0:
        elapsed %= duration

    elapsed_tics = elapsed / TIC
    elapsed_so_far = 0
    for letter, tics in states:
        if tics < 0 or elapsed_tics < elapsed_so_far + tics:
            return letter
        elapsed_so_far += tics
    return states[-1][0]

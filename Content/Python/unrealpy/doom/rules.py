"""Local Ultimate Doom campaign rules, inventory, and the save slots' names and checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, NamedTuple

from doom.dataset import ASSETS

# Episode and skill names are the data set's own menu graphics (lump names); without them, numbers.
EPISODE_GRAPHICS = ("M_EPI1", "M_EPI2", "M_EPI3", "M_EPI4")
SKILL_GRAPHICS = ("M_JKILL", "M_ROUGH", "M_HURT", "M_ULTRA", "M_NMARE")
E4_MUSIC = ("E3M4", "E3M2", "E3M3", "E1M5", "E2M7", "E2M4", "E2M6", "E2M5", "E1M9")
WEAPONS: dict[str, dict[str, Any]] = {
    "fist": dict(idle="PUNGA0", ammo="", cost=0, sound="DSPUNCH", length=128, pellets=1),
    "chainsaw": dict(idle="SAWGC0", ammo="", cost=0, sound="DSSAWFUL", length=128, pellets=1),
    "pistol": dict(idle="PISGA0", ammo="bullets", cost=1, sound="DSPISTOL", length=6000, pellets=1),
    "shotgun": dict(idle="SHTGA0", ammo="shells", cost=1, sound="DSSHOTGN", length=6000, pellets=7),
    "chaingun": dict(idle="CHGGA0", ammo="bullets", cost=1, sound="DSPISTOL", length=6000, pellets=1),
    "rocket": dict(
        idle="MISGA0",
        ammo="rockets",
        cost=1,
        sound="DSRLAUNC",
        projectile="MISLA1",
        speed=700,
        damage=20,
        radius=128,
    ),
    "plasma": dict(
        idle="PLSGA0",
        ammo="cells",
        cost=1,
        sound="DSPLASMA",
        projectile="PLSSA0",
        speed=875,
        damage=5,
        radius=0,
    ),
    "bfg": dict(
        idle="BFGGA0",
        ammo="cells",
        cost=40,
        sound="DSBFG",
        projectile="BFS1A0",
        speed=875,
        damage=100,
        radius=0,
    ),
}
WEAPON_PICKUPS = {
    2001: "shotgun",
    2002: "chaingun",
    2003: "rocket",
    2004: "plasma",
    2005: "chainsaw",
    2006: "bfg",
}
AMMO_PICKUPS = {
    2007: ("bullets", 10),
    2048: ("bullets", 50),
    2008: ("shells", 4),
    2049: ("shells", 20),
    2010: ("rockets", 1),
    2046: ("rockets", 5),
    2047: ("cells", 20),
    17: ("cells", 100),
}
KEY_PICKUPS = {5: "blue", 40: "blue", 6: "yellow", 39: "yellow", 13: "red", 38: "red"}
AMMO_MAX = {"bullets": 200, "shells": 50, "rockets": 50, "cells": 300}
MONSTERS = {
    3004: ("POSS", 20, "DSPISTOL"),
    9: ("SPOS", 30, "DSSHOTGN"),
    3001: ("TROO", 60, "DSFIRSHT"),
    3002: ("SARG", 150, "DSSGTATK"),
    58: ("SARG", 150, "DSSGTATK"),
    3005: ("HEAD", 400, "DSFIRSHT"),
    3006: ("SKUL", 100, "DSSKLATK"),
    3003: ("BOSS", 1000, "DSFIRSHT"),
    16: ("CYBR", 4000, "DSRLAUNC"),
    7: ("SPID", 3000, "DSSHOTGN"),
}


class MonsterInfo(NamedTuple):
    """A monster type's properties the AI uses; speed is map units per think."""

    speed: int
    chase_tics: int  # tics between two thinks
    radius: int
    painchance: int
    reactiontime: int
    melee: bool  # has a melee attack
    missile: bool


# Skull charge and the cacodemon bite run through the missile state, so their meleestate is empty.
MONSTER_INFO = {
    3004: MonsterInfo(8, 4, 20, 200, 8, False, True),
    9: MonsterInfo(8, 3, 20, 170, 8, False, True),
    3001: MonsterInfo(8, 3, 20, 200, 8, True, True),
    3002: MonsterInfo(10, 2, 30, 180, 8, True, False),
    58: MonsterInfo(10, 2, 30, 180, 8, True, False),
    3005: MonsterInfo(8, 3, 31, 128, 8, False, True),
    3006: MonsterInfo(8, 6, 16, 256, 8, False, True),
    3003: MonsterInfo(8, 3, 24, 50, 8, True, True),
    16: MonsterInfo(16, 3, 40, 20, 8, False, True),
    7: MonsterInfo(12, 3, 128, 40, 8, False, True),
}

# Doom mobjinfo heights (map units): what must fit between a sector's floor and ceiling.
MONSTER_HEIGHT = {3004: 56, 9: 56, 3001: 56, 3002: 56, 58: 56, 3005: 56, 3006: 56, 3003: 64, 16: 110, 7: 100}
MARINE_HEIGHT = 56
BARREL_HEIGHT = 42
ITEM_HEIGHT = 16
# Ceiling specials that crush (Doom's crushAndRaise, fastCrushAndRaise, silentCrushAndRaise, lowerAndCrush),
# and those that slow to 1/8 speed while they squeeze something (the fast ones do not).
CRUSHERS = {6, 25, 44, 49, 72, 73, 77, 141}
SLOWING_CRUSHERS = {25, 44, 49, 72, 73, 141}

DEATH_FRAMES = {
    "POSS": "HIJKL",
    "SPOS": "HIJKL",
    "TROO": "IJKLM",
    "SARG": "IJKLMN",
    "HEAD": "GHIJKL",
    "SKUL": "FGHIJK",
    "BOSS": "IJKLMNO",
    "CYBR": "HIJKLMNOP",
    "SPID": "JKLMNOPQRS",
}
THING_SPRITES = {
    5: "BKEYA0",
    6: "YKEYA0",
    13: "RKEYA0",
    38: "RSKUA0",
    39: "YSKUA0",
    40: "BSKUA0",
    8: "BPAKA0",
    2010: "ROCKA0",
    17: "CELPA0",
    2004: "PLASA0",
    2006: "BFUGA0",
    2047: "CELLA0",
    2013: "SOULA0",
    2022: "PINVA0",
    2024: "PINSA0",
    2025: "SUITA0",
    2026: "PMAPA0",
    2045: "PVISA0",
    10: "PLAYW0",
    12: "PLAYW0",
    15: "PLAYN0",
    18: "POSSL0",
    19: "SPOSL0",
    20: "TROOM0",
    21: "SARGN0",
    22: "HEADL0",
    23: "SKULK0",
    25: "POL1A0",
    26: "POL6A0",
    27: "POL4A0",
    28: "POL2A0",
    29: "POL3A0",
    30: "COL1A0",
    31: "COL2A0",
    32: "COL3A0",
    33: "COL4A0",
    34: "CANDA0",
    36: "COL5A0",
    37: "COL6A0",
    41: "CEYEA0",
    42: "FSKUA0",
    43: "TRE1A0",
    44: "TBLUA0",
    45: "TGRNA0",
    46: "TREDA0",
    47: "SMITA0",
    49: "GOR1A0",
    50: "GOR2A0",
    51: "GOR3A0",
    52: "GOR4A0",
    53: "GOR5A0",
    54: "TRE2A0",
    55: "SMBTA0",
    56: "SMGTA0",
    57: "SMRTA0",
    59: "GOR2A0",
    60: "GOR4A0",
    61: "GOR3A0",
    62: "GOR5A0",
    63: "GOR1A0",
    70: "FCANA0",
}
COUNT_ITEMS = {2014, 2015, 2018, 2019, 2013, 2022, 2023, 2024, 2025, 2026, 2045}
ANIMATIONS = (
    ("NUKAGE1", "NUKAGE2", "NUKAGE3"),
    ("FWATER1", "FWATER2", "FWATER3", "FWATER4"),
    ("SWATER1", "SWATER2", "SWATER3", "SWATER4"),
    ("LAVA1", "LAVA2", "LAVA3", "LAVA4"),
    ("BLOOD1", "BLOOD2", "BLOOD3"),
    tuple("FIREWAL" + letter for letter in "ABCDEFGHIJKL"),
    ("FIREBLU1", "FIREBLU2"),
    ("FIREMAG1", "FIREMAG2", "FIREMAG3"),
    ("FIRELAVA", "FIRELAV2", "FIRELAV3"),
    ("GSTFONT1", "GSTFONT2", "GSTFONT3"),
)
# Doom key-locked manual doors (card and skull keys share a colour).
LOCKS = {
    26: "blue",
    27: "yellow",
    28: "red",
    32: "blue",
    33: "red",
    34: "yellow",
    99: "blue",
    133: "blue",
    134: "red",
    135: "red",
    136: "yellow",
    137: "yellow",
}
MANUAL_DOORS = {1, 26, 27, 28, 31, 32, 33, 34, 117, 118}
EXIT_SPECIALS = {11, 51, 52, 124}
SECRET_EXITS = {51, 124}


_level_names: dict[str, Any] | None = None


def level_names() -> dict[str, Any]:
    """The data set's names.json: map titles and par times its DEHACKED lump sets (empty without one)."""
    global _level_names
    if _level_names is None:
        try:
            loaded = json.loads((ASSETS / "names.json").read_text(encoding="utf-8"))
            _level_names = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError):
            _level_names = {}
    return _level_names


def map_title(marker: str) -> str:
    """The map's title from the data set, else its marker (E1M1)."""
    titles = level_names().get("map_names")
    title = titles.get(marker) if isinstance(titles, dict) else None
    return str(title) if title else marker


def map_heading(marker: str) -> str:
    """`E1M1: TITLE`, or just the marker when the data set names no title."""
    title = map_title(marker)
    return marker if title == marker else f"{marker}: {title}"


def music_name(marker: str) -> str:
    return "D_" + (E4_MUSIC[int(marker[3]) - 1] if marker[1] == "4" else marker) + ".mid"


@dataclass(frozen=True)
class MatchRules:
    """What differs between the network game modes; the game state replicates the active one by name."""

    name: str
    weapons_stay: (
        bool  # weapons stay on the floor, one pick-up per marine and life (keys always stay in a netgame)
    )
    carry_inventory: bool  # a level change keeps health, armor, weapons and ammo (keys and powerups go)
    count_frags: (
        bool  # the HUD and the intermission show the frags, and the frag and time limits end the level
    )
    cheats: bool  # the cheat console works (vanilla netgames allow it only in co-op)
    stay_clips: int = (
        2  # clips of ammo a weapon pick-up gives when weapons stay (Doom: 2 in co-op, 5 in deathmatch)
    )
    random_spawns: bool = (
        False  # players (re)start at random deathmatch starts and telefrag what stands there
    )
    item_respawn: bool = False  # altdeath: items come back 30 seconds after they were taken


COOP = MatchRules("coop", weapons_stay=True, carry_inventory=True, count_frags=False, cheats=True)
DEATHMATCH = MatchRules(
    "deathmatch",
    weapons_stay=True,
    carry_inventory=False,
    count_frags=True,
    cheats=False,
    stay_clips=5,
    random_spawns=True,
)
ALTDEATH = MatchRules(
    "altdeath",
    weapons_stay=False,
    carry_inventory=False,
    count_frags=True,
    cheats=False,
    random_spawns=True,
    item_respawn=True,
)
MATCH_RULES = {rules.name: rules for rules in (COOP, DEATHMATCH, ALTDEATH)}
ITEM_RESPAWN_SECONDS = 30.0  # altdeath: how long a taken item stays away
NO_RESPAWN_ITEMS = (2022, 2024)  # invulnerability and invisibility never come back (MT_INV, MT_INS)
MAX_DEATHMATCH_STARTS = 10  # Doom keeps the first ten deathmatch starts of a map
SPAWN_TRIES = 20  # random deathmatch starts tried for a free one


def par_time(marker: str) -> int | None:
    """Seconds of par for a map, from the data set (the intermission shows it next to the time); None when
    the data set sets none (a par of 0 included)."""
    pars = level_names().get("par_times")
    par = pars.get(marker) if isinstance(pars, dict) else None
    return int(par) if isinstance(par, (int, float)) and par > 0 else None


def next_map(marker: str, secret: bool = False) -> str | None:
    episode, level = int(marker[1]), int(marker[3])
    if secret:
        return f"E{episode}M9"
    if level == 8:
        return None
    if level == 9:
        return f"E{episode}M{(4, 6, 7, 3)[episode - 1]}"
    return f"E{episode}M{level + 1}"


def skill_flag(skill: int) -> int:
    return 1 if skill <= 2 else 2 if skill == 3 else 4


def save_path(prefix: str, slot: int) -> str:
    """The name of save slot `slot` (0 to 5) of the data set whose slots start with `prefix`: the engine keeps
    it as Saved/SaveGames/<name>.sav (savegame.write_save)."""
    if not 0 <= slot <= 5:
        raise ValueError("Invalid save slot")
    return f"{prefix}-slot-{slot}"


def check_save(version: int, source_sha256: str, expected_sha256: str, marker: str, skill: int) -> None:
    """Refuse a save made for other game data, or of a map or a skill that does not exist."""
    if version != 1 or source_sha256 != expected_sha256:
        raise ValueError("Save belongs to another game data version")
    if marker not in [f"E{e}M{m}" for e in range(1, 5) for m in range(1, 10)]:
        raise ValueError("Invalid saved map")
    if skill not in range(1, 6):
        raise ValueError("Invalid saved difficulty")

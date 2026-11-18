"""Co-op networking helpers: who runs the simulation, how actors replicate, who the players are.

The listen server (or the standalone game) owns the simulation; clients only render what replicates.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import ue
from doom.rules import MATCH_RULES

if TYPE_CHECKING:
    from doom import player as player_mod
    from doom import state

MAX_PLAYERS = 4  # Doom player starts 1-4
NET_FREQUENCY = 35.0  # updates per second of the replicated gameplay actors (one Doom tic)
CULL_DISTANCE_SQUARED = 1.0e12  # the whole map is relevant to every player


def networked() -> bool:
    """True in a listen server or a client; False in the plain standalone game."""
    return not ue.KismetSystemLibrary.is_standalone(world_context_object=ue.get_world())


def is_client() -> bool:
    """True on a remote client (no game mode, no simulation)."""
    return not ue.KismetSystemLibrary.is_server(world_context_object=ue.get_world())


def replicate(actor: ue.Actor, movement: bool = False) -> None:
    """Replicate a freshly spawned gameplay actor to every client, wherever they are on the map.

    Per-instance equivalents of the uclass net options, so they work whatever the plugin version.
    """
    actor.set_replicates(True)
    actor.set_replicate_movement(movement)
    actor.always_relevant = True
    actor.net_update_frequency = NET_FREQUENCY
    actor.net_cull_distance_squared = CULL_DISTANCE_SQUARED


_cache: dict[str, list[Any]] = {}
_frame = [-1]


def invalidate() -> None:
    """Forget the cached player lists (they also expire with the engine frame)."""
    _cache.clear()


def _current() -> None:
    frame = ue.KismetSystemLibrary.get_frame_count()
    if frame != _frame[0]:
        _frame[0] = frame
        _cache.clear()


def marines() -> list[player_mod.DoomMarine]:
    """Every marine of this world, in start order (what the simulation targets)."""
    from doom import player as player_mod

    _current()
    if "marines" not in _cache:
        found = [
            pawn
            for pawn in ue.GameplayStatics.get_all_actors_of_class(player_mod.DoomMarine)
            if isinstance(pawn, player_mod.DoomMarine) and pawn.is_valid()
        ]
        found.sort(key=lambda pawn: pawn.start_index)
        _cache["marines"] = found
    return cast("list[player_mod.DoomMarine]", _cache["marines"])


def players() -> list[state.DoomPlayerState]:
    """Every DoomPlayerState of this world, in start order."""
    from doom import state

    _current()
    if "players" not in _cache:
        found = [
            ps
            for ps in ue.GameplayStatics.get_all_actors_of_class(state.DoomPlayerState)
            if isinstance(ps, state.DoomPlayerState)
            and ps.is_valid()
            # A player who left stays around as an inactive state without a controller (on the server).
            and not (ps.has_authority() and ps.player_controller() is None)
        ]
        found.sort(key=lambda ps: ps.start_index)
        _cache["players"] = found
    return cast("list[state.DoomPlayerState]", _cache["players"])


# -- the host's options -----------------------------------------------------------------------------------

OPTION_ENV = {
    "match": "DOOM_MATCH",
    "fraglimit": "DOOM_FRAGLIMIT",
    "timelimit": "DOOM_TIMELIMIT",
    "monsters": "DOOM_MONSTERS",
    "map": "DOOM_MAP",
}


@dataclass(frozen=True)
class HostOptions:
    """What the host chose for the network game (the clients read the mode from the game state)."""

    match: str = "coop"  # coop, deathmatch or altdeath
    fraglimit: int = 0  # 0: none
    timelimit: float = 0.0  # minutes, 0: none
    monsters: bool = True
    map: str = "E1M1"


def apply_args(args: list[str]) -> None:
    """Take `key=value` (or `--key=value`) host arguments into the environment the options are read from."""
    for arg in args:
        key, _, value = arg.lstrip("-").partition("=")
        if key.lower() in OPTION_ENV and value:
            os.environ[OPTION_ENV[key.lower()]] = value


def _number(name: str, kind: type, default: Any) -> Any:
    try:
        return max(kind(0), kind(os.environ.get(name, "") or default))
    except ValueError:
        ue.log(f"Doom: {name} is not a number: ignored", "warning")
        return default


def host_options() -> HostOptions:
    """The host's options from env DOOM_MATCH, DOOM_FRAGLIMIT, DOOM_TIMELIMIT, DOOM_MONSTERS and DOOM_MAP.

    Monsters default to off in deathmatch and altdeath (how people play) and to on in co-op.
    """
    match = os.environ.get("DOOM_MATCH", "").strip().lower() or "coop"
    if match not in MATCH_RULES:
        ue.log(f"Doom: unknown DOOM_MATCH {match!r} (coop, deathmatch, altdeath): co-op", "warning")
        match = "coop"
    monsters = os.environ.get("DOOM_MONSTERS", "").strip().lower()
    return HostOptions(
        match=match,
        fraglimit=_number("DOOM_FRAGLIMIT", int, 0),
        timelimit=_number("DOOM_TIMELIMIT", float, 0.0),
        monsters=(monsters not in ("0", "false", "no", "off")) if monsters else match == "coop",
        map=os.environ.get("DOOM_MAP", "").strip().upper() or "E1M1",
    )

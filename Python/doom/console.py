"""Local Doom command console; explicit commands only, never Python/UE eval."""

from typing import Any

import ue
from doom import campaign
from doom.common import xy
from doom.rules import music_name

CHAR_KEYS = {letter: ue.Key(key_name=letter.upper()) for letter in "abcdefghijklmnopqrstuvwxyz"}
CHAR_KEYS.update(
    {
        str(i): ue.Key(key_name=name)
        for i, name in enumerate(
            ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine")
        )
    }
)
CONTROL_KEYS = {
    name: ue.Key(key_name=name) for name in ("F1", "Escape", "Enter", "BackSpace", "SpaceBar", "Up", "Down")
}


def initialize(mode: Any) -> None:
    mode.console_text = ""
    mode.console_lines = ["DOOM CONSOLE - F1 / ESC TO CLOSE - HELP FOR COMMANDS"]
    mode.console_history = []
    mode.console_history_index = 0


HELP = "IDDQD IDFA IDKFA IDCLEVxy IDCLIP IDBEHOLDx (V S I R A L) IDCHOPPERS | IDMYPOS IDDT IDMUSxy CLEAR HELP"
BEHOLD_POWERS = {
    "v": ("invulnerability", 30.0, "INVULNERABILITY"),
    "i": ("invisibility", 60.0, "INVISIBILITY"),
    "r": ("suit", 60.0, "RADIATION SUIT"),
    "l": ("light_visor", 120.0, "LIGHT AMPLIFICATION"),
}
LOCAL_CHEATS = ("idmypos", "iddt", "idmus")  # what a machine does for itself: nothing here needs the server
ALL_WEAPONS = ("fist", "chainsaw", "pistol", "shotgun", "chaingun", "rocket", "plasma", "bfg")


def on_off(value: bool) -> str:
    return "ON" if value else "OFF"


def execute(mode: Any, text: str, controller: Any = None) -> str:
    """Run a console line on this machine. The cheats that change a marine run on the server for the player
    that typed them: here when this machine has authority, else the line goes over `controller` and the
    answer comes back to the console. Position, automap and music commands are local to each machine."""
    command = "".join(text.strip().lower().split())
    if command == "help":
        return HELP
    if command == "clear":
        mode.console_lines = []
        return ""
    if command == "idmypos":
        return where_am_i(mode)
    if command == "iddt":
        mode.automap_level = (mode.automap_level + 1) % 3
        return str(
            ("MAP AS IT IS", "MAP SHOWS EVERY LINE", "MAP SHOWS EVERY LINE AND THING")[mode.automap_level]
        )
    if command.startswith("idmus"):
        return change_music(mode, command[5:])
    if mode.has_authority():
        ps = mode.primary()
        if ps is None:
            return "NO PLAYER"
        result = apply(mode, ps, command, host=True)
        if command.startswith("idclev") and result.startswith("WARPED"):
            mode.menu = "console"
        return result
    if controller is None or not command.startswith("id"):
        return "UNKNOWN COMMAND - TYPE HELP"
    controller.to_server_cheat(command)
    return ""  # the server answers with owner_console


def where_am_i(mode: Any) -> str:
    player = ue.GameplayStatics.get_player_pawn(0)
    controller = ue.GameplayStatics.get_player_controller(0)
    if player is None or controller is None:
        return "NO PLAYER"
    x, y = xy(player)
    angle = -float(controller.get_control_rotation()[1]) % 360
    return f"ANG={angle:.0f} X={x:.0f} Y={y:.0f}"


def change_music(mode: Any, digits: str) -> str:
    if len(digits) != 2 or not digits.isdigit() or digits[0] not in "1234" or digits[1] == "0":
        return "USAGE: IDMUSxy (EPISODE, MAP)"
    marker = f"E{digits[0]}M{digits[1]}"
    mode.music.play(music_name(marker))
    return f"CHANGING MUSIC TO {marker}"


def apply(mode: Any, ps: Any, command: str, host: bool = False) -> str:
    """The cheats that change a marine, on the server. `ps` is the player that typed `command`; `host`
    is True for the host (and the single player), who alone may change the map."""
    if not command.startswith("id"):
        return "UNKNOWN COMMAND - TYPE HELP"
    if mode.networked and not mode.match.cheats:
        return "CHEATS ARE OFF IN THIS GAME"
    if ps.dead or mode.won:
        return "CHEATS REQUIRE A LIVE LEVEL"
    if command == "iddqd":
        ps.god_mode = not ps.god_mode
        if ps.god_mode:
            ps.health = max(ps.health, 100)
        return "GOD MODE ON" if ps.god_mode else "GOD MODE OFF"
    if command in ("idfa", "idkfa"):
        ps.armor, ps.armor_type = 200, 2
        ps.weapons.update(ALL_WEAPONS)
        for ammo in ("bullets", "shells", "rockets", "cells"):
            setattr(ps, ammo, campaign.ammo_limit(ps, ammo))
        if command == "idkfa":
            ps.keys.update(("blue", "yellow", "red"))
            ps.key_kinds.update(blue=5, yellow=6, red=13)
        return "FULL ARSENAL" + (" AND KEYS" if command == "idkfa" else "")
    if command == "idclip":
        ps.noclip = not ps.noclip
        return "NOCLIP " + on_off(ps.noclip)
    if command == "idchoppers":
        ps.weapons.add("chainsaw")
        return "CHAINSAW"
    if command.startswith("idbehold"):
        return behold(ps, command[8:])
    if command.startswith("idclev"):
        if not host:
            return "ONLY THE HOST CAN CHANGE THE MAP"
        digits = command[6:]
        if len(digits) != 2 or not digits.isdigit():
            return "USAGE: IDCLEVxy (EPISODE, MAP)"
        marker = f"E{digits[0]}M{digits[1]}"
        if marker not in mode.maps:
            return "INVALID MAP"
        campaign.load_level(mode, marker, mode.skill)
        return f"WARPED TO {marker}"
    return "UNKNOWN COMMAND - TYPE HELP"


def behold(ps: Any, option: str) -> str:
    """IDBEHOLDx: toggle a power (V invulnerable, S berserk, I invisible, R suit, A map, L light amp)."""
    if option in BEHOLD_POWERS:
        field, seconds, name = BEHOLD_POWERS[option]
        on = getattr(ps, field) <= 0
        setattr(ps, field, seconds if on else 0.0)
        return f"{name} {on_off(on)}"
    if option == "s":
        ps.berserk = not ps.berserk
        if ps.berserk:
            ps.weapon = "fist"
        return "BERSERK " + on_off(ps.berserk)
    if option == "a":
        ps.all_map = not ps.all_map
        return "ALL MAP " + on_off(ps.all_map)
    return "INVULNERABILITY, BERSERK, INVISIBILITY, RADSUIT, ALLMAP, LIGHT: IDBEHOLD + V S I R A L"


def input_tick(mode: Any, controller: Any) -> None:
    pressed = controller.was_input_key_just_pressed
    if pressed(CONTROL_KEYS["F1"]) or pressed(CONTROL_KEYS["Escape"]):
        mode.menu = ""
        return
    if pressed(CONTROL_KEYS["Enter"]):
        text = mode.console_text.strip()
        if text:
            mode.console_lines.append("> " + text)
            mode.console_history.append(text)
            mode.console_history = mode.console_history[-32:]
            result = execute(mode, text, controller)
            if result:
                mode.console_lines.append(result)
            mode.console_lines = mode.console_lines[-12:]
        mode.console_text = ""
        mode.console_history_index = len(mode.console_history)
        return
    if pressed(CONTROL_KEYS["Up"]) or pressed(CONTROL_KEYS["Down"]):
        step = -1 if pressed(CONTROL_KEYS["Up"]) else 1
        mode.console_history_index = max(0, min(len(mode.console_history), mode.console_history_index + step))
        mode.console_text = (
            mode.console_history[mode.console_history_index]
            if mode.console_history_index < len(mode.console_history)
            else ""
        )
        return
    if pressed(CONTROL_KEYS["BackSpace"]):
        mode.console_text = mode.console_text[:-1]
    if pressed(CONTROL_KEYS["SpaceBar"]):
        mode.console_text = (mode.console_text + " ")[:80]
    for character, key in CHAR_KEYS.items():
        if pressed(key):
            mode.console_text = (mode.console_text + character)[:80]


def draw(hud: Any, mode: Any, width: int, height: int) -> None:
    scale = max(0.75, min(width / 960, height / 720))
    line_height = 22 * scale
    panel_height = min(height * 0.65, line_height * 15)
    hud.draw_rect(ue.LinearColor(0.015, 0.015, 0.015, 0.94), 0, 0, width, panel_height)
    color = ue.LinearColor(0.85, 0.9, 0.75, 1)
    visible = max(1, int(panel_height / line_height) - 2)
    for index, text in enumerate(mode.console_lines[-visible:]):
        hud.draw_text(text, color, 14 * scale, (index + 0.5) * line_height, scale=scale)
    hud.draw_text("> " + mode.console_text + "_", color, 14 * scale, panel_height - line_height, scale=scale)

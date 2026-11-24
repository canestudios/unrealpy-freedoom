"""Campaign/menu/save flow for the locally owned Ultimate Doom IWAD."""

from __future__ import annotations

import math
import random
from typing import Any

import ue
from doom import lighting, net
from doom.dataset import save_root
from doom.rules import (
    AMMO_MAX,
    ANIMATIONS,
    EPISODE_GRAPHICS,
    SKILL_GRAPHICS,
    WEAPONS,
    map_heading,
    next_map,
    par_time,
    read_save,
    save_path,
    write_save,
)


def game() -> Any:
    from doom import runtime

    return runtime


def enter_menu(mode: Any, screen: str = "main") -> None:
    mode.menu = screen
    mode.menu_row = 1 if screen == "save" else 0
    if mode.networked:
        return  # a network game cannot be paused
    player: Any = ue.GameplayStatics.get_player_pawn(0)
    if player:
        player.character_movement.stop_movement_immediately()
        player.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
    for enemy in mode.enemies:
        if enemy.is_valid():
            enemy.character_movement.stop_movement_immediately()
            enemy.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)


def leave_menu(mode: Any) -> None:
    mode.menu = ""
    if mode.networked:
        return
    player: Any = ue.GameplayStatics.get_player_pawn(0)
    if player and not mode.dead:
        player.character_movement.set_movement_mode(ue.EMovementMode.MOVE_Walking)
    for enemy in mode.enemies:
        if enemy.is_valid() and not enemy.dead:
            movement = (
                ue.EMovementMode.MOVE_Flying
                if enemy.type_id in (3005, 3006)
                else ue.EMovementMode.MOVE_Walking
            )
            enemy.character_movement.set_movement_mode(movement)


ENDING_DELAY = 12.0  # seconds a co-op game shows the end of an episode before the next one starts


def load_level(
    mode: Any,
    marker: str,
    skill: int,
    carry: dict[str, Any] | None = None,
    players: dict[int, dict[str, Any] | None] | None = None,
) -> None:
    """Start a map. `carry` is the single player's inventory; `players` the co-op ones by start index."""
    if marker not in mode.maps or not 1 <= skill <= 5:
        raise ValueError("Invalid map or difficulty")
    mode.music.stop()
    mode.clear_level()
    mode.marker, mode.skill = marker, skill
    mode.level_serial += 1  # clients rebuild their copy of the level
    mode.load_data(marker)
    mode.build()
    mode.restart()
    # Co-op marines keep their own inventories; joiners and dead marines start fresh.
    if bool(players):
        for ps in mode.players():
            saved = players.get(int(ps.start_index))
            if bool(saved):
                apply_inventory(ps, saved)
    elif bool(carry):
        apply_inventory(mode, carry)
    mode.menu = ""
    mode.started = True
    mode.finished_episode = False
    mode.secret_exit = False
    mode.notice = map_heading(marker).upper()
    mode.notice_timer = 3.0


INVENTORY = (
    "god_mode",
    "health",
    "armor",
    "bullets",
    "shells",
    "rockets",
    "cells",
    "weapon",
    "backpack",
    "berserk",
    "armor_type",
    "invulnerability",
    "suit",
    "invisibility",
    "light_visor",
    "all_map",
)


def inventory(mode: Any) -> dict[str, Any]:
    return {field: getattr(mode, field) for field in INVENTORY} | {"weapons": sorted(mode.weapons)}


def apply_inventory(mode: Any, state: dict[str, Any]) -> None:
    for field in INVENTORY:
        if field in state:
            setattr(mode, field, state[field])
    mode.weapons = set(state["weapons"])


def next_map_inventory(owner: Any) -> dict[str, Any]:
    """What a marine takes to the next map: health, armor, weapons and ammo stay; keys and powerups go, and
    so does the automap power."""
    kept = inventory(owner)
    kept.update(
        invulnerability=0.0, invisibility=0.0, suit=0.0, light_visor=0.0, berserk=False, all_map=False
    )
    return kept


def carry_over(ps: Any) -> dict[str, Any] | None:
    """What a network marine takes to the next map. A marine that is dead when the exit is used starts the
    next map like a new one (pistol, 100 health)."""
    if ps.dead:
        return None
    return next_map_inventory(ps)


def ending_music(marker: str) -> str:
    return "D_VICTOR.mid" if marker[1] in "12" else "D_BUNNY.mid"


def finish_level(mode: Any, secret: bool = False) -> None:
    if mode.won:
        return
    mode.won = True
    mode.secret_exit = secret
    mode.music.play("D_INTER.mid")
    for player in mode.marines():
        player.character_movement.stop_movement_immediately()


def advance(mode: Any) -> None:
    if mode.networked and mode.finished_episode:
        return  # the episode's end is on the screens: the server moves on by itself
    marker = next_map(mode.marker, mode.secret_exit)
    if marker is None:
        mode.finished_episode = True
        mode.music.play(ending_music(mode.marker))
        if mode.networked:  # nobody pauses: every screen shows the end, then the next episode begins
            mode.ending_timer = ENDING_DELAY
        else:
            mode.menu = "ending"
        return
    if mode.networked:
        carried = (
            {int(ps.start_index): carry_over(ps) for ps in mode.players()}
            if mode.match.carry_inventory
            else None
        )
        load_level(mode, marker, mode.skill, players=carried)
        return
    load_level(mode, marker, mode.skill, next_map_inventory(mode))
    save_game(mode, 0)


def next_episode(mode: Any) -> None:
    """A co-op game after the end of an episode: the first map of the next one (E4 returns to E1), all new."""
    load_level(mode, f"E{int(mode.marker[1]) % 4 + 1}M1", mode.skill)


def secret_total(mode: Any) -> int:
    return int(sum(sector["special"] == 9 for sector in mode.data["sectors"]))


def intermission_stats(mode: Any) -> dict[str, Any]:
    """The network intermission: percentages per marine, or a deathmatch's frags."""
    totals = {
        "kills": max(1, int(mode.total)),
        "items": max(1, int(mode.total_items)),
        "secrets": max(1, secret_total(mode)),
    }
    rows = [
        {
            "player": int(ps.start_index) + 1,
            "kills": int(ps.kills),
            "items": int(ps.items),
            "secrets": int(ps.secret_found),
            "kills_percent": int(ps.kills) * 100 // totals["kills"],
            "items_percent": int(ps.items) * 100 // totals["items"],
            "secrets_percent": int(ps.secret_found) * 100 // totals["secrets"],
            "frags": int(ps.frags),
            "victims": [
                int(n) for n in ps.frag_table
            ],  # deathmatch: how often it killed each marine (by start)
        }
        for ps in net.players()
    ]
    return {
        "map": mode.marker,
        "rows": rows,
        "time": int(mode.elapsed),
        "par": par_time(mode.marker),
        "frags": bool(mode.match.count_frags),
    }


def finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: finite(v) for key, v in value.items() if key != "actor"}
    if isinstance(value, (tuple, list, set)):
        return [finite(v) for v in value]
    return value


def snapshot(mode: Any) -> dict[str, Any]:
    player: Any = ue.GameplayStatics.get_player_pawn(0)
    controller: Any = ue.GameplayStatics.get_player_controller(0)
    assert player and controller
    objects = []
    g = game()
    for obj in mode.objects:
        if not obj.is_valid():
            continue
        if isinstance(obj, g.DoomEffect):
            continue  # Transient decorations do not participate in saved gameplay state.
        role = (
            "enemy" if isinstance(obj, g.DoomDemon) else "barrel" if isinstance(obj, g.DoomBarrel) else "item"
        )
        if isinstance(obj, g.DoomProjectile):
            role = "projectile"
        fields = (
            "kind",
            "prefix",
            "health",
            "dead",
            "awake",
            "attack",
            "clock",
            "frame",
            "key",
            "taken",
            "dropped",
            "exploded",
            "anim",
            "anim_time",
            "fired",
            "action_event",
            "facing",
            "charge_time",
            "charge_direction",
            "age",
            "dx",
            "dy",
            "dz",
            "speed",
            "damage",
            "radius",
            "weapon",
            "friendly",
            "stage",
            "family",
            "sprayed",
            "spawn_x",
            "spawn_y",
            "spawn_z",
            "spawn_health",
            "type_id",
        )
        objects.append(
            dict(
                role=role,
                id=getattr(obj, "thing_id", -1),
                position=[float(v) for v in obj.get_actor_location()],
                hidden=bool(obj.hidden),
                owner_id=getattr(getattr(obj, "owner", None), "thing_id", -1),
                fields={field: finite(getattr(obj, field)) for field in fields if hasattr(obj, field)},
            )
        )
    return finite(
        dict(
            source_sha256=mode.data["source_sha256"],
            map=mode.marker,
            skill=mode.skill,
            inventory=inventory(mode),
            keys=sorted(mode.keys),
            key_kinds=mode.key_kinds,
            player=[float(v) for v in player.get_actor_location()],
            rotation=[float(v) for v in controller.get_control_rotation()],
            elapsed=mode.elapsed,
            cooldown=mode.cooldown,
            weapon_action=mode.weapon_action,
            weapon_clock=mode.weapon_clock,
            weapon_event=mode.weapon_event,
            flash_variant=mode.flash_variant,
            pickup_flash=mode.pickup_flash,
            berserk_flash=mode.berserk_flash,
            kills=mode.kills,
            item_count=mode.item_count,
            secrets=sorted(mode.secrets),
            triggered=sorted(mode.triggered),
            switches=sorted(mode.switches),
            switch_timers=mode.switch_timers,
            won=mode.won,
            secret_exit=mode.secret_exit,
            dead=mode.dead,
            doors=mode.doors,
            movers=mode.movers,
            ceilings=mode.ceilings,
            objects=objects,
            random_state=random.getstate(),
        )
    )


def save_game(mode: Any, slot: int) -> bool:
    if mode.networked:
        mode.notice, mode.notice_timer = "SAVING IS SINGLE-PLAYER ONLY", 3.0
        return False
    if not mode.started or mode.dead:
        mode.notice, mode.notice_timer = "START A GAME BEFORE SAVING", 3.0
        return False
    try:
        write_save(save_root(), slot, snapshot(mode))
    except (OSError, ValueError, TypeError) as error:
        mode.notice, mode.notice_timer = f"SAVE FAILED: {error}", 4.0
        return False
    mode.notice, mode.notice_timer = f"SAVED SLOT {slot}", 2.0
    return True


def tuples(value: Any) -> Any:
    return tuple(tuples(v) for v in value) if isinstance(value, list) else value


def load_game(mode: Any, slot: int) -> bool:
    if mode.networked:
        mode.notice, mode.notice_timer = "LOADING IS SINGLE-PLAYER ONLY", 3.0
        return False
    try:
        state = read_save(save_root(), slot, mode.data["source_sha256"])
    except (OSError, ValueError, KeyError) as error:
        mode.notice, mode.notice_timer = f"LOAD FAILED: {error}", 4.0
        return False
    g = game()
    load_level(mode, state["map"], state["skill"])
    # Powerups are kept as expiry times on the level clock, so the clock is restored before them.
    mode.elapsed = state["elapsed"]
    apply_inventory(mode, state["inventory"])
    mode.keys = set(state["keys"])
    mode.key_kinds = state.get("key_kinds", {})
    for field, default in (
        ("weapon_action", ""),
        ("weapon_clock", 0.0),
        ("weapon_event", 0),
        ("flash_variant", 0),
        ("pickup_flash", 0.0),
        ("berserk_flash", 0.0),
    ):
        setattr(mode, field, state.get(field, default))
    for field in ("cooldown", "kills", "item_count", "won", "secret_exit", "dead"):
        setattr(mode, field, state[field])
    mode.secrets, mode.triggered = set(state["secrets"]), set(state["triggered"])
    mode.switch_timers = {int(i): value for i, value in state.get("switch_timers", {}).items()}
    for i in state.get("switches", []):
        set_switch(mode, i, False)
    for field in ("doors", "movers", "ceilings"):
        collection = getattr(mode, field)
        for index, saved in state[field].items():
            entry = collection[int(index)]
            entry.update({key: math.inf if value is None else value for key, value in saved.items()})
            if entry["actor"]:
                offset = entry["height"] if field == "doors" else entry["offset"]
                entry["actor"].set_actor_location(ue.Vector(0, 0, offset * g.SCALE), False, True)
    existing = {obj.thing_id: obj for obj in mode.objects if getattr(obj, "thing_id", -1) >= 0}
    retained = []
    for saved in state["objects"]:
        obj = existing.pop(saved["id"], None) if saved["id"] >= 0 else None
        if obj is None:
            cls = {
                "enemy": g.DoomDemon,
                "barrel": g.DoomBarrel,
                "item": g.DoomSprite,
                "projectile": g.DoomProjectile,
            }[saved["role"]]
            obj = ue.spawn_actor(cls, location=ue.Vector(*saved["position"]))
        obj.thing_id = saved["id"]
        obj.set_actor_location(ue.Vector(*saved["position"]), False, True)
        for field, value in saved["fields"].items():
            setattr(obj, field, value)
        if isinstance(obj, g.DoomDemon):
            obj.attack_sound = g.DEMONS[obj.type_id][2]
            obj.frame = ""
            obj.image(saved["fields"].get("frame", obj.prefix + "A1"))
            if obj.dead:
                obj.character_movement.set_movement_mode(ue.EMovementMode.MOVE_None)
                obj.capsule_component.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
        else:
            obj.key = ""
            obj.image(saved["fields"].get("key", "BAR1A0"))
            obj.set_actor_hidden_in_game(saved.get("hidden", bool(getattr(obj, "taken", False))))
            if isinstance(obj, g.DoomBarrel) and obj.exploded:
                obj.body.set_collision_enabled(ue.ECollisionEnabled.NoCollision)
        retained.append(obj)
    for obj in existing.values():
        obj.destroy_actor()
    mode.objects = retained
    mode.enemies = [obj for obj in retained if isinstance(obj, g.DoomDemon)]
    by_id = {obj.thing_id: obj for obj in retained if obj.thing_id >= 0}
    for obj, saved in zip(retained, state["objects"], strict=True):
        if isinstance(obj, g.DoomProjectile) and not obj.friendly:
            obj.owner = by_id.get(saved.get("owner_id", -1))
    player: Any = ue.GameplayStatics.get_player_pawn(0)
    controller: Any = ue.GameplayStatics.get_player_controller(0)
    assert player and controller
    player.set_actor_location(ue.Vector(*state["player"]), False, True)
    player.character_movement.stop_movement_immediately()
    controller.set_control_rotation(ue.Rotator(*state["rotation"]))
    controller.yaw = state["rotation"][1]
    mode.last_xy = None
    random.setstate(tuples(state["random_state"]))
    mode.notice, mode.notice_timer = f"LOADED SLOT {slot}", 2.0
    from doom.geometry import refresh

    refresh(mode)
    return True


def slot_label(slot: int) -> str:
    try:
        import json

        state = json.loads(save_path(save_root(), slot).read_text(encoding="utf-8"))
        return f"{slot}: {state['map']} / SKILL {state['skill']} / {int(state['elapsed'])}s"
    except (OSError, ValueError, KeyError, IndexError):
        return f"{slot}: EMPTY"


def setup_graphics(mode: Any) -> dict[int, str]:
    """Setup-menu rows whose choice shows as the data set's menu graphic: row index -> lump name."""
    choices = {0: EPISODE_GRAPHICS[mode.selected_episode - 1], 2: SKILL_GRAPHICS[mode.selected_skill - 1]}
    return {row: lump for row, lump in choices.items() if lump in mode.data["sprites"]}


def draw_graphic(hud: Any, mode: Any, lump: str, x: float, y: float, scale: float) -> None:
    """A menu graphic at its own proportions, `scale` times its size in the 320-wide original."""
    width, height = mode.data["sprites"][lump][:2]
    hud.image(mode, lump, x, y, width * scale, height * scale)


def menu_rows(mode: Any) -> list[str]:
    if mode.menu == "setup":
        e, m = mode.selected_episode, mode.selected_map
        return [
            f"EPISODE: {e}",
            f"MAP: {map_heading(f'E{e}M{m}')}",
            f"DIFFICULTY: {mode.selected_skill}",
            "START GAME",
        ]
    if mode.menu in ("save", "load"):
        return [slot_label(i) for i in range(6)]
    rows = ["RESUME"] if mode.networked else ["NEW GAME / SELECT MAP", "LOAD GAME", "SAVE GAME", "RESUME"]
    if lighting.supported():
        rows.append("LIGHTING: " + ("LIT" if lighting.active() else "CLASSIC"))
        rows.extend(lighting.slider_rows())
    return [*rows, "QUIT"]


def menu_input(mode: Any, controller: Any) -> None:
    keys = game().KEYS

    def pressed(key: str) -> bool:
        return bool(controller.was_input_key_just_pressed(keys[key]))

    if mode.menu == "ending":
        if pressed("Enter") or pressed("Escape"):
            enter_menu(mode)
        return
    rows = menu_rows(mode)
    if pressed("Up") or pressed("W"):
        mode.menu_row = (mode.menu_row - 1) % len(rows)
    if pressed("Down") or pressed("S"):
        mode.menu_row = (mode.menu_row + 1) % len(rows)
    delta = int(pressed("Right") or pressed("D")) - int(pressed("Left") or pressed("A"))
    if mode.menu == "setup" and delta and mode.menu_row < 3:
        field, limit = (("selected_episode", 4), ("selected_map", 9), ("selected_skill", 5))[mode.menu_row]
        setattr(mode, field, (getattr(mode, field) - 1 + delta) % limit + 1)
    row = rows[mode.menu_row]
    if mode.menu == "main" and delta and row.startswith("LIGHTING"):
        lighting.toggle(mode)
        return
    slider = lighting.slider_key(row) if mode.menu == "main" else None
    if bool(slider) and delta:
        lighting.adjust(mode, slider, delta)
        return
    if pressed("Escape"):
        if mode.menu != "main":
            enter_menu(mode)
        elif mode.started:
            leave_menu(mode)
        return
    if not pressed("Enter"):
        return
    if mode.networked and mode.menu == "main":
        if row == "RESUME":
            leave_menu(mode)
        elif row.startswith("LIGHTING"):
            lighting.toggle(mode)
        elif bool(slider) or row == lighting.RESET_ROW:
            lighting.reset(mode, slider)
        else:
            ue.KismetSystemLibrary.execute_console_command("quit")
        return
    if mode.menu == "setup":
        if mode.menu_row == 3:
            load_level(mode, f"E{mode.selected_episode}M{mode.selected_map}", mode.selected_skill)
            save_game(mode, 0)
    elif mode.menu == "save":
        if mode.menu_row != 0 and save_game(mode, mode.menu_row):
            leave_menu(mode)
    elif mode.menu == "load":
        load_game(mode, mode.menu_row)
    elif mode.menu_row == 0:
        enter_menu(mode, "setup")
    elif mode.menu_row == 1:
        enter_menu(mode, "load")
    elif mode.menu_row == 2:
        enter_menu(mode, "save")
    elif mode.menu_row == 3:
        if mode.started:
            leave_menu(mode)
    elif row.startswith("LIGHTING"):
        lighting.toggle(mode)
    elif bool(slider) or row == lighting.RESET_ROW:
        lighting.reset(mode, slider)  # Enter on a slider resets it, on the last row all of them
    else:
        mode.music.stop()
        ue.KismetSystemLibrary.execute_console_command("quit")


def draw_menu(hud: Any, mode: Any, width: int, height: int) -> None:
    hud.draw_rect(ue.LinearColor(0.04, 0.01, 0.01, 1), 0, 0, float(width), float(height))
    scale = min(width / 800, height / 600)
    x, y = width * 0.12, height * 0.25
    red, white = ue.LinearColor(0.85, 0.15, 0.08, 1), ue.LinearColor(1, 1, 1, 1)
    # Use the original title art, with the menu below it; the game data remains local.
    if "M_DOOM" in mode.data["sprites"]:
        hud.image(mode, "M_DOOM", width / 2 - 140 * scale, 22 * scale, 280 * scale, 120 * scale)
    else:
        hud.draw_text("ULTIMATE DOOM", red, x, 40 * scale, scale=3 * scale)
    if mode.menu == "ending":
        hud.draw_text(f"EPISODE {mode.marker[1]} COMPLETE", red, x, y, scale=2 * scale)
        lump = EPISODE_GRAPHICS[int(mode.marker[1]) - 1]
        if lump in mode.data["sprites"]:
            draw_graphic(hud, mode, lump, x, y + 55 * scale, 2 * scale)
        hud.draw_text("ENTER: RETURN TO MENU", white, x, y + 150 * scale, scale=scale)
        return
    rows = menu_rows(mode)
    step, text = (48, 1.5) if len(rows) <= 6 else (34, 1.15)  # the lighting sliders add rows
    graphics = setup_graphics(mode) if mode.menu == "setup" else {}
    for i, row in enumerate(rows):
        colour = red if i == mode.menu_row else white
        if i in graphics:
            row = row.split(":")[0] + ":"
            draw_graphic(
                hud, mode, graphics[i], x + 150 * scale, y + i * step * scale - 2 * scale, 1.6 * scale
            )
        hud.draw_text(
            ("> " if i == mode.menu_row else "  ") + row,
            colour,
            x,
            y + i * step * scale,
            scale=text * scale,
        )
        slider = lighting.slider_key(row) if mode.menu == "main" else None
        if bool(slider):
            draw_thermometer(hud, mode, slider, x + 330 * scale, y + i * step * scale, scale, colour)
    hud.draw_text(
        "ARROWS: SELECT / CHANGE    ENTER: CONFIRM    ESC: BACK",
        white,
        x,
        height - 95 * scale,
        scale=scale,
    )
    hud.draw_text(
        "IN GAME: ESC MENU   F5 QUICKSAVE   F9 QUICKLOAD   1-7 WEAPONS",
        white,
        x,
        height - 65 * scale,
        scale=scale,
    )
    if mode.notice_timer > 0:
        hud.draw_text(mode.notice, white, x, height - 35 * scale, scale=scale)


def draw_thermometer(hud: Any, mode: Any, key: str, x: float, y: float, scale: float, colour: Any) -> None:
    """Doom's options-menu slider (M_THERM* graphics, a plain bar without them)."""
    index, count = lighting.slider_position(key)
    sprites = mode.data["sprites"]
    parts = ("M_THERML", "M_THERMM", "M_THERMR", "M_THERMO")
    if all(p in sprites for p in parts):
        cell, height = 8 * 2 * scale, sprites["M_THERML"][1] * 2 * scale
        hud.image(mode, "M_THERML", x, y, cell, height)
        for i in range(8):
            hud.image(mode, "M_THERMM", x + cell * (i + 1), y, cell, height)
        hud.image(mode, "M_THERMR", x + cell * 9, y, cell, height)
        knob = cell * (1 + 8 * index / (count - 1))
        hud.image(mode, "M_THERMO", x + knob, y, cell, height)
        end = x + cell * 10
    else:
        length, end = 160 * scale, x + 160 * scale
        hud.draw_rect(ue.LinearColor(0.25, 0.25, 0.25, 1), x, y + 8 * scale, length, 6 * scale)
        hud.draw_rect(colour, x + (length - 8 * scale) * index / (count - 1), y, 8 * scale, 22 * scale)
    hud.draw_text(lighting.slider_text(key), colour, end + 12 * scale, y, scale=scale)


def current_ammo(mode: Any) -> int:
    ammo = WEAPONS[mode.weapon]["ammo"]
    return int(getattr(mode, ammo)) if ammo else 0


def ammo_limit(mode: Any, ammo: str) -> int:
    return AMMO_MAX[ammo] * (2 if mode.backpack else 1)


def register_animation(mode: Any, material: Any, key: str) -> None:
    for frames in ANIMATIONS:
        if key in frames and all(frame in mode.data["textures"] for frame in frames):
            mode.animated_materials.append((material, frames, frames.index(key)))
            return


def set_switch(mode: Any, index: int, repeat: bool) -> None:
    for material, key in mode.button_materials.get(index, []):
        replacement = ("SW2" if key.startswith("SW1") else "SW1") + key[3:]
        if replacement in mode.data["textures"]:
            material.set_texture_parameter_value("DoomTexture", mode.texture(replacement))
    mode.switches.add(index)
    if repeat:
        mode.switch_timers[index] = 1.0


def tick_materials(mode: Any, dt: float, local: bool = False) -> None:
    """Animate textures and scrolling walls; `local` (a client) leaves the switches to the server's state."""
    frame = int(mode.elapsed / (8 / 35))
    if frame != mode.animation_frame:
        mode.animation_frame = frame
        for material, frames, phase in mode.animated_materials:
            material.set_texture_parameter_value(
                "DoomTexture", mode.texture(frames[(frame + phase) % len(frames)])
            )
    for material, width in mode.scroll_materials.values():
        material.set_scalar_parameter_value("DoomScrollX", (mode.elapsed * 35 / width) % 1)
    if local:
        return
    for index in list(mode.switch_timers):
        mode.switch_timers[index] -= dt
        if mode.switch_timers[index] <= 0:
            for material, key in mode.button_materials.get(index, []):
                material.set_texture_parameter_value("DoomTexture", mode.texture(key))
            mode.switch_timers.pop(index)
            mode.switches.discard(index)

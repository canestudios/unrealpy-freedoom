from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from typing_extensions import override

import ue
from doom import campaign, console, net
from doom.animation import WEAPON_FLASH
from doom.common import TIC, WHITE, mode_now, player_now, weapon_frame, xy
from doom.rules import EPISODE_GRAPHICS, map_title
from doom.visual import hud_layout

if TYPE_CHECKING:
    from doom.mode import DoomHangarMode


@ue.uclass
class DoomHUD(ue.HUD):
    def image(
        self,
        mode: DoomHangarMode,
        key: str,
        x: float,
        y: float,
        width: float,
        height: float,
        clip_bottom: float | None = None,
        alpha: float = 1.0,
    ) -> None:
        texture = mode.texture(key, True)
        v_height = 1.0
        if clip_bottom is not None:
            visible = min(height, max(0.0, clip_bottom - y))
            if not visible:
                return
            v_height = visible / height
            height = visible
        if texture:
            self.draw_texture(
                texture,
                x,
                y,
                width,
                height,
                0,
                0,
                1,
                v_height,
                ue.LinearColor(1, 1, 1, alpha),
                ue.EBlendMode.BLEND_Translucent,
                1,
                False,
                0,
                ue.Vector2D(0, 0),
            )

    def digits(
        self,
        mode: DoomHangarMode,
        value: int,
        right: float,
        y: float,
        scale: float,
        small: bool = False,
    ) -> None:
        for digit in reversed(str(max(0, value))):
            key = ("STYSNUM" if small else "STTNUM") + digit
            w, h = mode.data["sprites"][key][:2]
            right -= float(w) * scale
            self.image(mode, key, right, y, w * scale, h * scale)

    @override
    def receive_draw_hud(self, size_x: int, size_y: int) -> None:
        mode = mode_now()
        if mode is None or not mode.data or not mode.ready:
            return
        if mode.menu == "console":
            console.draw(self, mode, size_x, size_y)
            return
        if mode.menu:
            campaign.draw_menu(self, mode, size_x, size_y)
            return
        if mode.networked and mode.finished_episode:
            self.draw_ending(mode, size_x, size_y)
            return
        scale, left, bottom = hud_layout(size_x, size_y)
        self.draw_rect(ue.LinearColor(0.12, 0.12, 0.12, 1), 0, bottom, float(size_x), 32 * scale)
        self.image(mode, "STBAR", left, bottom, 320 * scale, 32 * scale)
        frags = mode.networked and mode.match.count_frags
        if not frags:
            self.image(mode, "STARMS", left + 104 * scale, bottom, 40 * scale, 32 * scale)
        tier = min(4, (100 - min(100, mode.health)) // 20)
        face = (
            "STFDEAD0"
            if mode.dead
            else "STFGOD0"
            if mode.invulnerability > 0 or getattr(mode, "god_mode", False)
            else f"STFOUCH{tier}"
            if mode.pain > 0
            else f"STFST{tier}{int(mode.elapsed * 2) % 3}"
        )
        w, h, ox, oy = mode.data["sprites"][face]
        self.image(mode, face, left + (143 - ox) * scale, bottom - oy * scale, w * scale, h * scale)
        self.digits(
            mode,
            campaign.current_ammo(mode),
            left + 44 * scale,
            bottom + 3 * scale,
            scale,
        )
        self.digits(mode, mode.health, left + 90 * scale, bottom + 3 * scale, scale)
        self.image(mode, "STTPRCNT", left + 91 * scale, bottom + 3 * scale, 14 * scale, 16 * scale)
        self.digits(mode, mode.armor, left + 221 * scale, bottom + 3 * scale, scale)
        self.image(mode, "STTPRCNT", left + 222 * scale, bottom + 3 * scale, 14 * scale, 16 * scale)
        for i, colour in enumerate(("blue", "yellow", "red")):
            if colour in mode.keys:
                self.image(
                    mode,
                    f"STKEYS{i + (3 if mode.key_kinds.get(colour, 0) in (38, 39, 40) else 0)}",
                    left + 239 * scale,
                    bottom + (3 + 10 * i) * scale,
                    8 * scale,
                    5 * scale,
                )
        for i, ammo in enumerate(("bullets", "shells", "rockets", "cells")):
            self.digits(
                mode,
                getattr(mode, ammo),
                left + 288 * scale,
                bottom + (5 + 6 * i) * scale,
                scale,
                True,
            )
            self.digits(
                mode,
                campaign.ammo_limit(mode, ammo),
                left + 314 * scale,
                bottom + (5 + 6 * i) * scale,
                scale,
                True,
            )
        if frags:
            # A deathmatch shows the frags where the ARMS panel is.
            count = int(getattr(mode.primary(), "frags", 0))
            self.digits(mode, abs(count), left + 138 * scale, bottom + 3 * scale, scale)
            if count < 0:  # a suicide costs a frag: the minus sign (a bar when the data set lacks the lump)
                digit_w, digit_h = (float(v) for v in mode.data["sprites"]["STTNUM0"][:2])
                left_edge = left + 138 * scale - len(str(-count)) * digit_w * scale
                if "STTMINUS" in mode.data["sprites"]:
                    w, h = mode.data["sprites"]["STTMINUS"][:2]
                    self.image(
                        mode, "STTMINUS", left_edge - w * scale, bottom + 3 * scale, w * scale, h * scale
                    )
                else:
                    self.draw_rect(
                        WHITE,
                        left_edge - 12 * scale,
                        bottom + (3 + digit_h / 2) * scale,
                        10 * scale,
                        3 * scale,
                    )
        for number, weapon in enumerate(
            () if frags else ("pistol", "shotgun", "chaingun", "rocket", "plasma", "bfg"), 2
        ):
            key = ("STYSNUM" if weapon in mode.weapons else "STGNUM") + str(number)
            if key in mode.data["sprites"]:
                w, h = mode.data["sprites"][key][:2]
                self.image(
                    mode,
                    key,
                    left + (111 + 12 * ((number - 2) % 3)) * scale,
                    bottom + (4 + 10 * ((number - 2) // 3)) * scale,
                    w * scale,
                    h * scale,
                )
        if not mode.show_map and not mode.won:
            elapsed = mode.weapon_clock if mode.weapon_action == mode.weapon else math.inf
            frame = weapon_frame(mode.weapon, elapsed)
            if mode.weapon == "chainsaw" and mode.cooldown <= 0:
                frame = "SAWG" + "CD"[int(mode.elapsed / (4 * TIC)) % 2] + "0"
            alpha = 0.22 if mode.invisibility > 0 else 1.0
            if frame in mode.data["sprites"]:
                w, h, ox, oy = mode.data["sprites"][frame]
                self.image(
                    mode,
                    frame,
                    left - ox * scale,
                    bottom - (168 + oy) * scale,
                    w * scale,
                    h * scale,
                    bottom,
                    alpha,
                )
            for flash, start, tics in WEAPON_FLASH.get(mode.weapon, []):
                if start * TIC <= elapsed < (start + tics) * TIC:
                    if mode.weapon == "plasma" and mode.flash_variant:
                        flash = "PLSFB0"
                    w, h, ox, oy = mode.data["sprites"][flash]
                    self.image(
                        mode,
                        flash,
                        left - ox * scale,
                        bottom - (168 + oy) * scale,
                        w * scale,
                        h * scale,
                        bottom,
                        alpha,
                    )
        if mode.show_map:
            self.draw_automap(mode, size_x, bottom)
        if mode.pain > 0:
            self.draw_rect(ue.LinearColor(1, 0, 0, min(0.3, mode.pain)), 0, 0, float(size_x), bottom)
        elif mode.berserk_flash > 0:
            self.draw_rect(
                ue.LinearColor(1, 0, 0, min(0.3, mode.berserk_flash * 0.08)),
                0,
                0,
                float(size_x),
                bottom,
            )
        elif mode.pickup_flash > 0:
            self.draw_rect(
                ue.LinearColor(1, 0.75, 0, min(0.25, mode.pickup_flash)),
                0,
                0,
                float(size_x),
                bottom,
            )
        elif mode.suit > 0 and (mode.suit > 4 or int(mode.suit / TIC) & 8):
            self.draw_rect(ue.LinearColor(0, 1, 0, 0.18), 0, 0, float(size_x), bottom)
        if mode.notice_timer > 0:
            self.draw_text(mode.notice, WHITE, 20, 15, scale=1.4)
        if mode.networked:
            players = net.players()
            for i, ps in enumerate(players):
                self.draw_text(
                    f"P{ps.start_index + 1} {'DEAD' if ps.dead else ps.health}  KILLS {ps.kills}",
                    WHITE,
                    float(size_x - 230),
                    15 + 20 * i,
                    scale=1.0,
                )
        if mode.dead:
            self.draw_text(
                "YOU DIED - YOU WILL BE BACK" if mode.networked else "YOU DIED - R TO RESTART",
                WHITE,
                float(size_x / 2 - 170),
                float(size_y / 2),
                scale=2,
            )
        if mode.won:
            self.draw_rect(ue.LinearColor(0.08, 0.03, 0.02, 1), 0, 0, float(size_x), bottom)
            if mode.networked:
                self.draw_intermission(mode, size_x)
                return
            self.draw_text(
                f"{map_title(mode.marker).upper()} / FINISHED",
                WHITE,
                float(size_x / 2 - 220),
                110,
                scale=3,
            )
            self.draw_text(
                f"KILLS {mode.kills}/{mode.total}    ITEMS {mode.item_count}/{mode.total_items}",
                WHITE,
                150,
                210,
                scale=2,
            )
            self.draw_text(
                f"SECRETS {len(mode.secrets)}/{campaign.secret_total(mode)}    "
                f"TIME {int(mode.elapsed) // 60}:{int(mode.elapsed) % 60:02d}",
                WHITE,
                150,
                265,
                scale=2,
            )
            self.draw_text("ENTER: NEXT LEVEL    ESC: MENU", WHITE, 150, 340, scale=1.5)

    def draw_automap(self, mode: DoomHangarMode, size_x: int, bottom: float) -> None:
        """The automap: walls and special lines; the map power and IDDT add lines (IDDT twice, the things)."""
        from doom import monsters, world

        self.draw_rect(ue.LinearColor(0, 0, 0, 1), 0, 0, float(size_x), bottom)
        x0, y0, x1, y1 = mode.data["bounds"]
        zoom = min(size_x / (x1 - x0 + 100), bottom / (y1 - y0 + 100))
        sides, sectors = mode.data["sides"], mode.data["sectors"]
        level = mode.automap_level

        def screen(point: tuple[float, float]) -> tuple[float, float]:
            return float((point[0] - x0 + 50) * zoom), float(bottom - (point[1] - y0 + 50) * zoom)

        for line in mode.data["lines"]:
            a, b = mode.data["vertices"][line["a"]], mode.data["vertices"][line["b"]]
            colour = None
            if line["left"] == 65535 or line["special"]:
                colour = ue.LinearColor(0.8, 0.12, 0.04, 1)
            elif mode.all_map or level >= 1:
                front, back = sectors[sides[line["right"]]["sector"]], sectors[sides[line["left"]]["sector"]]
                if front["floor"] != back["floor"] or front["ceiling"] != back["ceiling"]:
                    colour = ue.LinearColor(0.55, 0.4, 0.1, 1)  # a step or a ledge
                elif level >= 1:
                    colour = ue.LinearColor(0.3, 0.3, 0.3, 1)  # a passage, only with IDDT
            if colour is not None:
                (sx, sy), (ex, ey) = screen(a), screen(b)
                self.draw_line(sx, sy, ex, ey, colour, 1)
        if level >= 2:
            for thing in mode.things():
                if not thing.is_valid() or getattr(thing, "dead", False) or getattr(thing, "taken", False):
                    continue
                if isinstance(thing, monsters.DoomDemon):
                    colour = ue.LinearColor(1, 0.1, 0.1, 1)
                elif isinstance(thing, (world.DoomSprite, world.DoomBarrel)) and not isinstance(
                    thing, world.DoomEffect
                ):
                    colour = ue.LinearColor(0.9, 0.8, 0.2, 1)
                else:
                    continue
                px, py = screen(xy(thing))
                self.draw_rect(colour, px - 1.5, py - 1.5, 3, 3)
        mine = player_now()
        for marine in net.marines():
            px, py = screen(xy(marine))
            colour = WHITE if marine is mine else ue.LinearColor(0.2, 1, 0.2, 1)
            self.draw_rect(colour, px - 3, py - 3, 6, 6)

    def draw_intermission(self, mode: DoomHangarMode, size_x: int) -> None:
        """The co-op intermission: one row per marine, then the time and the par."""
        stats = campaign.intermission_stats(mode)
        x = float(size_x) * 0.12
        self.draw_text(
            f"{map_title(stats['map']).upper()} / FINISHED", WHITE, float(size_x / 2 - 220), 60, scale=3
        )
        if stats["frags"]:
            self.draw_frag_matrix(stats, x)
            return
        columns = [("PLAYER", 0), ("KILLS", 150), ("ITEMS", 290), ("SECRETS", 430), ("FRAGS", 590)]
        for title, offset in columns:
            self.draw_text(title, ue.LinearColor(0.85, 0.15, 0.08, 1), x + offset, 150, scale=1.5)
        for index, row in enumerate(stats["rows"]):
            y = 195 + 38 * index
            cells = (
                f"P{row['player']}",
                f"{row['kills_percent']}%",
                f"{row['items_percent']}%",
                f"{row['secrets_percent']}%",
                str(row["frags"]),
            )
            for (_, offset), text in zip(columns, cells, strict=True):
                self.draw_text(text, WHITE, x + offset, y, scale=2)
        y = 195 + 38 * max(1, len(stats["rows"])) + 40
        time, par = stats["time"], stats["par"]
        times = f"TIME {time // 60}:{time % 60:02d}"
        if par is not None:
            times += f"    PAR {par // 60}:{par % 60:02d}"
        self.draw_text(times, WHITE, x, y, scale=2)
        self.draw_text("NEXT MAP SOON    ENTER: SKIP", WHITE, x, y + 60, scale=1.2)

    def draw_frag_matrix(self, stats: dict[str, Any], x: float) -> None:
        """The deathmatch intermission (WI_drawDeathmatchStats): who killed whom, and each marine's total."""
        red = ue.LinearColor(0.85, 0.15, 0.08, 1)
        rows = stats["rows"]
        starts = [row["player"] - 1 for row in rows]
        self.draw_text("KILLER", red, x, 135, scale=1.5)
        self.draw_text("VICTIM", red, x + 150, 135, scale=1.5)
        for column, start in enumerate(starts):
            self.draw_text(f"P{start + 1}", red, x + 150 + 90 * column, 165, scale=1.5)
        self.draw_text("FRAGS", red, x + 150 + 90 * len(starts) + 30, 165, scale=1.5)
        for index, row in enumerate(rows):
            y = 205 + 38 * index
            self.draw_text(f"P{row['player']}", WHITE, x, y, scale=2)
            for column, start in enumerate(starts):
                count = row["victims"][start]
                self.draw_text(
                    str(-count if start == row["player"] - 1 and count else count),
                    WHITE,
                    x + 150 + 90 * column,
                    y,
                    scale=2,
                )
            self.draw_text(str(row["frags"]), WHITE, x + 150 + 90 * len(starts) + 30, y, scale=2)
        y = 205 + 38 * max(1, len(rows)) + 30
        time = stats["time"]
        self.draw_text(f"TIME {time // 60}:{time % 60:02d}", WHITE, x, y, scale=2)
        self.draw_text("NEXT MAP SOON    ENTER: SKIP", WHITE, x, y + 60, scale=1.2)

    def draw_ending(self, mode: DoomHangarMode, size_x: int, size_y: int) -> None:
        """The end of an episode in a co-op game: shown on every machine until the next episode begins."""
        episode = int(mode.marker[1])
        self.draw_rect(ue.LinearColor(0.04, 0.01, 0.01, 1), 0, 0, float(size_x), float(size_y))
        x = float(size_x) * 0.12
        self.draw_text(f"EPISODE {episode} COMPLETE", ue.LinearColor(0.85, 0.15, 0.08, 1), x, 130, scale=3)
        lump = EPISODE_GRAPHICS[episode - 1]
        if lump in mode.data["sprites"]:
            width, height = mode.data["sprites"][lump][:2]
            self.image(mode, lump, x, 210, width * 2.5, height * 2.5)
        self.draw_text(f"NEXT: EPISODE {episode % 4 + 1}", WHITE, x, 320, scale=1.5)

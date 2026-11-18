"""Read the user's DOOM IWAD. No game data is bundled with this module."""

from __future__ import annotations

import hashlib
import json
import re
import struct
import wave
import zlib
from pathlib import Path
from typing import Any

from doom.dataset import ASSETS, find_wad


def name(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii").upper()


class Wad:
    def __init__(self, path: Path):
        self.data = path.read_bytes()
        magic, count, directory = struct.unpack_from("<4sii", self.data)
        if magic not in (b"IWAD", b"PWAD"):
            raise ValueError("Not a Doom WAD")
        self.entries = [struct.unpack_from("<ii8s", self.data, directory + i * 16) for i in range(count)]
        self.lumps = {name(n): self.data[p : p + size] for p, size, n in self.entries}
        self.palette = [tuple(self.lumps["PLAYPAL"][i : i + 3]) for i in range(0, 768, 3)]

    def patch(self, key: str) -> tuple[int, int, int, int, bytearray]:
        data = self.lumps[key]
        w, h, left, top = struct.unpack_from("<hhhh", data)
        if not (0 < w <= 512 and 0 < h <= 512 and len(data) >= 8 + w * 4):
            raise ValueError(f"{key} is not a sprite patch")
        pixels = bytearray(w * h * 4)
        for x in range(w):
            p = struct.unpack_from("<I", data, 8 + x * 4)[0]
            while data[p] != 255:
                y, length = data[p : p + 2]
                for j, c in enumerate(data[p + 3 : p + 3 + length]):
                    if y + j < h:
                        k = ((y + j) * w + x) * 4
                        pixels[k : k + 4] = bytes((*self.palette[c], 255))
                p += length + 4
        return int(w), int(h), int(left), int(top), pixels

    def texture(self, key: str) -> tuple[int, int, bytearray]:
        pnames = self.lumps["PNAMES"]
        patches = [name(pnames[4 + i * 8 : 12 + i * 8]) for i in range(struct.unpack_from("<i", pnames)[0])]
        for table in ("TEXTURE1", "TEXTURE2"):
            data = self.lumps.get(table)
            if data is None:
                continue
            for i in range(struct.unpack_from("<i", data)[0]):
                p = struct.unpack_from("<i", data, 4 + i * 4)[0]
                if name(data[p : p + 8]) != key:
                    continue
                w, h = struct.unpack_from("<hh", data, p + 12)
                pixels = bytearray(w * h * 4)
                for j in range(struct.unpack_from("<h", data, p + 20)[0]):
                    ox, oy, index, _, _ = struct.unpack_from("<hhhhh", data, p + 22 + j * 10)
                    pw, ph, _, _, src = self.patch(patches[index])
                    for sy in range(ph):
                        for sx in range(pw):
                            x, y = sx + ox, sy + oy
                            if 0 <= x < w and 0 <= y < h:
                                si, di = (sy * pw + sx) * 4, (y * w + x) * 4
                                if src[si + 3]:
                                    pixels[di : di + 4] = src[si : si + 4]
                return int(w), int(h), pixels
        raise KeyError(key)

    def level(self, marker: str = "E1M1") -> dict[str, Any]:
        start = next(i for i, (_, _, n) in enumerate(self.entries) if name(n) == marker)
        lumps = {name(n): self.data[p : p + size] for p, size, n in self.entries[start + 1 : start + 11]}

        def rows(key: str, fmt: str) -> list[Any]:
            return list(struct.iter_unpack("<" + fmt, lumps[key]))

        sectors = [
            dict(floor=f, ceiling=c, floor_tex=name(ft), ceiling_tex=name(ct), light=light, special=s, tag=t)
            for f, c, ft, ct, light, s, t in rows("SECTORS", "hh8s8shhh")
        ]
        sides = [
            dict(x=x, y=y, upper=name(u), lower=name(low), middle=name(m), sector=s)
            for x, y, u, low, m, s in rows("SIDEDEFS", "hh8s8s8sh")
        ]
        lines = [
            dict(a=a, b=b, flags=f, special=s, tag=t, right=r, left=left)
            for a, b, f, s, t, r, left in rows("LINEDEFS", "HHHHHHH")
        ]
        vertices = rows("VERTEXES", "hh")
        segs = rows("SEGS", "HHHHHH")
        leaves = rows("SSECTORS", "HH")
        nodes = rows("NODES", "hhhhhhhhhhhhHH")
        bounds = [
            min(v[0] for v in vertices),
            min(v[1] for v in vertices),
            max(v[0] for v in vertices),
            max(v[1] for v in vertices),
        ]
        polygons = []

        def clip(poly: list[Any], nx: float, ny: float, d: float) -> list[Any]:
            result = []
            for a, b in zip(poly, poly[1:] + poly[:1], strict=True):
                da, db = nx * a[0] + ny * a[1] - d, nx * b[0] + ny * b[1] - d
                if da >= -0.001:
                    result.append(a)
                if (da > 0) != (db > 0):
                    t = da / (da - db)
                    result.append([a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])])
            return result

        def walk(index: int, poly: list[Any]) -> None:
            if len(poly) < 3:
                return
            if index & 0x8000:
                count, first = leaves[index & 0x7FFF]
                if count:
                    line, side = segs[first][3:5]
                    sector = sides[lines[line]["right" if side == 0 else "left"]]["sector"]
                    # BSP leaves are further bounded by their actual segments.
                    for seg in segs[first : first + count]:
                        a, b = vertices[seg[0]], vertices[seg[1]]
                        nx, ny = b[1] - a[1], a[0] - b[0]
                        poly = clip(poly, nx, ny, nx * a[0] + ny * a[1])
                    if len(poly) >= 3:
                        polygons.append(dict(sector=sector, points=poly))
                return
            n = nodes[index]
            x, y, dx, dy = n[:4]
            nx, ny = dy, -dx
            walk(n[12], clip(poly, nx, ny, nx * x + ny * y))
            walk(n[13], clip(poly, -nx, -ny, -nx * x - ny * y))

        x0, y0, x1, y1 = bounds
        root = len(nodes) - 1 if nodes else 0x8000  # A single subsector needs no BSP partition.
        walk(root, [[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
        return dict(
            marker=marker,
            sectors=sectors,
            sides=sides,
            lines=lines,
            vertices=vertices,
            nodes=nodes,
            segs=segs,
            leaves=leaves,
            polygons=polygons,
            things=rows("THINGS", "hhhhh"),
            bounds=bounds,
        )


def png(path: Path, w: int, h: int, pixels: bytes | bytearray) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    scan = b"".join(b"\0" + pixels[y * w * 4 : (y + 1) * w * 4] for y in range(h))
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scan))
        + chunk(b"IEND", b"")
    )


def png_rows(path: Path) -> tuple[int, int, list[bytes]]:
    """Width, height and the RGBA8 byte rows of a PNG written by `png` (no filtering)."""
    data = path.read_bytes()
    w, h = struct.unpack(">II", data[16:24])
    pos, idat = 8, b""
    while pos < len(data):
        size, kind = struct.unpack(">I4s", data[pos : pos + 8])
        if kind == b"IDAT":
            idat += data[pos + 8 : pos + 8 + size]
        pos += 12 + size
    raw = zlib.decompress(idat)
    stride = w * 4 + 1
    return w, h, [raw[y * stride + 1 : (y + 1) * stride] for y in range(h)]


def srgb_to_linear(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else float(((v + 0.055) / 1.055) ** 2.4)


def png_top_colour(path: Path, rows: int = 4) -> tuple[float, float, float]:
    """Mean linear colour of the first `rows` pixel rows of a PNG written by `png` (RGBA8, no filtering)."""
    w, h, lines = png_rows(path)
    total = [0.0, 0.0, 0.0]
    for line in lines[: min(rows, h)]:
        for x in range(w):
            for c in range(3):
                total[c] += srgb_to_linear(line[x * 4 + c] / 255)
    count = w * min(rows, h)
    return total[0] / count, total[1] / count, total[2] / count


def mus_to_midi(data: bytes) -> bytes:
    """Convert Doom MUS events to standard MIDI, preserving the original score."""
    if data[:4] == b"MThd":
        return data
    if data[:4] != b"MUS\x1a":
        raise ValueError("Expected a MUS or MIDI music lump")
    length, start = struct.unpack_from("<HH", data, 4)
    controls = (0, 0, 1, 7, 10, 11, 91, 93, 64, 67, 120, 123, 126, 127, 121)
    velocities = [64] * 16
    track, pending, p = bytearray(), 0, start

    def vlq(value: int) -> bytes:
        result = [value & 127]
        value >>= 7
        while value:
            result.insert(0, (value & 127) | 128)
            value >>= 7
        return bytes(result)

    track.extend(b"\0\xff\x51\x03\x07\xa1\x20")
    while p < start + length:
        event = data[p]
        p += 1
        kind, channel = (event >> 4) & 7, event & 15
        channel = 9 if channel == 15 else channel + (channel >= 9)
        payload = b""
        if kind == 6:
            break
        if kind == 0:
            payload = bytes((0x80 | channel, data[p] & 127, 64))
            p += 1
        elif kind == 1:
            note = data[p]
            p += 1
            if note & 128:
                velocities[channel] = data[p] & 127
                p += 1
            payload = bytes((0x90 | channel, note & 127, velocities[channel]))
        elif kind == 2:
            bend = data[p] << 6
            p += 1
            payload = bytes((0xE0 | channel, bend & 127, (bend >> 7) & 127))
        elif kind == 3:
            control = data[p]
            p += 1
            payload = bytes((0xB0 | channel, controls[control], 0))
        elif kind == 4:
            control, value = data[p : p + 2]
            p += 2
            payload = (
                bytes((0xC0 | channel, value & 127))
                if control == 0
                else bytes((0xB0 | channel, controls[control], value & 127))
            )
        else:
            raise ValueError(f"Unknown MUS event {kind}")
        track.extend(vlq(pending) + payload)
        pending = 0
        if event & 128:
            delay = 0
            while True:
                part = data[p]
                p += 1
                delay = delay * 128 + (part & 127)
                if not part & 128:
                    break
            pending = delay
    track.extend(vlq(pending) + b"\xff\x2f\0")
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, 70) + b"MTrk" + struct.pack(">I", len(track)) + track


def dehacked_map_names(data: bytes) -> dict[str, str]:
    """Level names a DEHACKED lump sets: BEX [STRINGS] HUSTR_ExMy, and classic Text blocks that replace an
    `ExMy: ...` string."""
    text = data.decode("latin-1")
    names: dict[str, str] = {}

    def keep(marker: str, value: str) -> None:
        value = value.strip()
        prefix = f"{marker}:"
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
        if value:
            names[marker] = value

    for match in re.finditer(r"^[ \t]*HUSTR_(E\dM\d)[ \t]*=[ \t]*(.*?)[ \t]*\\?\r?$", text, re.MULTILINE):
        keep(match.group(1), match.group(2))
    for match in re.finditer(r"^Text[ \t]+(\d+)[ \t]+(\d+)[ \t]*\r?\n", text, re.MULTILINE):
        old_len, new_len = int(match.group(1)), int(match.group(2))
        body = text[match.end() : match.end() + old_len + new_len]
        old = re.match(r"(E\dM\d):", body[:old_len])
        if old is not None and len(body) == old_len + new_len:
            keep(old.group(1), body[old_len:])
    return names


def dehacked_par_times(data: bytes) -> dict[str, int]:
    """Par times (seconds) a DEHACKED lump's BEX [PARS] section sets with `par <episode> <map> <seconds>`."""
    text = data.decode("latin-1")
    return {
        f"E{match.group(1)}M{match.group(2)}": int(match.group(3))
        for match in re.finditer(
            r"^[ \t]*par[ \t]+([1-4])[ \t]+([1-9])[ \t]+(\d+)", text, re.MULTILINE | re.IGNORECASE
        )
    }


def write_level_names(wad: Wad, target: Path) -> None:
    """names.json: the map titles and par times the WAD's DEHACKED lump sets (none without one)."""
    dehacked = wad.lumps.get("DEHACKED", b"")
    names = dict(map_names=dehacked_map_names(dehacked), par_times=dehacked_par_times(dehacked))
    (target / "names.json").write_text(json.dumps(names, indent=1), encoding="utf-8")


def extract(wad_path: Path | None = None, target: Path = ASSETS) -> dict[str, Any]:
    wad = Wad(wad_path or find_wad())
    markers = sorted(
        key
        for key in wad.lumps
        if len(key) == 4 and key[0] == "E" and key[1] in "1234" and key[2] == "M" and key[3] in "123456789"
    )
    levels = {marker: wad.level(marker) for marker in markers}
    target.mkdir(parents=True, exist_ok=True)
    textures, sprites, sounds = target / "textures", target / "sprites", target / "sounds"
    for folder in (textures, sprites, sounds):
        folder.mkdir(exist_ok=True)

    info = {}
    skipped: dict[str, list[str]] = {"textures": [], "flats": [], "sprites": [], "sounds": [], "music": []}
    wall_names = {
        side[key]
        for level in levels.values()
        for side in level["sides"]
        for key in ("upper", "lower", "middle")
    } - {"-"}
    flat_names = {
        sector[key]
        for level in levels.values()
        for sector in level["sectors"]
        for key in ("floor_tex", "ceiling_tex")
    } - {"F_SKY1"}
    in_flats = False
    for offset, size, raw_name in wad.entries:
        lump_name = name(raw_name)
        if lump_name in {"F_START", "F1_START", "F2_START"}:
            in_flats = True
            continue
        if lump_name in {"F_END", "F1_END", "F2_END"}:
            in_flats = False
            continue
        data = wad.data[offset : offset + size]
        if in_flats and len(data) == 4096:
            flat_names.add(lump_name)
    texture_names = set()
    for table in ("TEXTURE1", "TEXTURE2"):
        data = wad.lumps.get(table)
        if data is None:
            continue
        for i in range(struct.unpack_from("<i", data)[0]):
            offset = struct.unpack_from("<i", data, 4 + i * 4)[0]
            texture_names.add(name(data[offset : offset + 8]))
    wall_names.update(texture_names)
    for key in sorted(wall_names):
        try:
            w, h, pixels = wad.texture(key)
        except (KeyError, IndexError, struct.error):
            skipped["textures"].append(key)
            continue
        png(textures / f"{key}.png", w, h, pixels)
        info[key] = [w, h]
    for key in sorted(flat_names):
        data = wad.lumps.get(key, b"")
        if len(data) < 4096:
            skipped["flats"].append(key)
            continue
        png(textures / f"{key}.png", 64, 64, b"".join(bytes((*wad.palette[c], 255)) for c in data[:4096]))
        info[key] = [64, 64]

    sprite_info = {}
    prefixes = (
        "POSS",
        "SPOS",
        "TROO",
        "PLAY",
        "STIM",
        "MEDI",
        "BON1",
        "BON2",
        "ARM1",
        "ARM2",
        "CLIP",
        "SHEL",
        "AMMO",
        "SBOX",
        "SHOT",
        "CSAW",
        "BKEY",
        "YKEY",
        "RKEY",
        "BAR1",
        "BEXP",
        "COLU",
        "SMT2",
        "TRE1",
        "POL5",
        "CBRA",
        "ELEC",
        "PSTR",
        "MGUN",
        "LAUN",
        "BROK",
        "STBAR",
        "STF",
        "STTNUM",
        "STTMINUS",
        "STTPRCNT",
        "STARMS",
        "STGNUM",
        "STYSNUM",
        "STKEYS",
        "STDISK",
        "PISG",
        "PISF",
        "SHTG",
        "SHTF",
        "PUNG",
        "PUFF",
        "BAL1",
        "TFOG",
        "WISCRT2",
        "WIOSTK",
        "WIOSTS",
        "WIOSTI",
        "WITIME",
        "WIMAP0",
        "WILV00",
        "WIF",
        "WIPCNT",
        "WINUM",
        "WICOLON",
        "WISUCKS",
        "WIENTER",
        "WIMSTT",
        "WISPLAT",
        "WIURH",
        "M_",
        "TITLEPIC",
        "CREDIT",
        "HELP",
        "VICTORY",
        "ENDPIC",
        "INTERPIC",
        "WIMAP",
        "WILV",
        "CHGG",
        "CHGF",
        "SAWG",
        "PLSG",
        "PLSF",
        "BFGG",
        "BFGF",
        "MISG",
        "MISF",
        "PLSS",
        "PLSE",
        "MISL",
        "BFS1",
        "BFE1",
        "BFE2",
    )
    sprite_keys = set()
    in_sprites = False
    for _, _, raw_name in wad.entries:
        lump_name = name(raw_name)
        if lump_name == "S_START":
            in_sprites = True
            continue
        if lump_name == "S_END":
            in_sprites = False
            continue
        if in_sprites:
            sprite_keys.add(lump_name)
    sprite_keys.update(key for key in wad.lumps if key.startswith(prefixes))
    for key in sorted(sprite_keys):
        try:
            w, h, left, top, pixels = wad.patch(key)
            png(sprites / f"{key}.png", w, h, pixels)
            sprite_info[key] = [w, h, left, top]
        except (struct.error, IndexError, ValueError):
            skipped["sprites"].append(key)
            continue

    for key, data in wad.lumps.items():
        if key.startswith("DS") and len(data) > 8:
            fmt, rate, length = struct.unpack_from("<HHI", data)
            if not (fmt == 3 and rate):
                skipped["sounds"].append(key)
            else:
                with wave.open(str(sounds / f"{key}.wav"), "wb") as stream:
                    stream.setparams((1, 1, rate, 0, "NONE", "not compressed"))
                    stream.writeframes(data[8 : 8 + length])
        if key.startswith("D_"):
            if data.startswith((b"MUS\x1a", b"MThd")):  # Freedoom already ships standard MIDI
                (target / f"{key}.mid").write_bytes(mus_to_midi(data))
            else:
                skipped["music"].append(key)

    source_sha256 = hashlib.sha256(wad.data).hexdigest()
    for marker, level in levels.items():
        level["textures"] = info
        level["sprites"] = sprite_info
        level["source_sha256"] = source_sha256
        (target / f"{marker}.json").write_text(json.dumps(level), encoding="utf-8")
    for kind, keys in skipped.items():
        if keys:
            print(f"extract: skipped {len(keys)} {kind}: {', '.join(sorted(keys)[:40])}")
    write_level_names(wad, target)
    manifest = dict(maps=markers, textures=info, sprites=sprite_info, source_sha256=source_sha256)
    (target / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    demo = levels["E1M1"]
    return dict(
        map="E1M1",
        sectors=len(demo["sectors"]),
        polygons=len(demo["polygons"]),
        lines=len(demo["lines"]),
        things=len(demo["things"]),
        textures=len(info),
        sprites=len(sprite_info),
        sounds=len(list(sounds.glob("*.wav"))),
        maps=len(levels),
        source_sha256=source_sha256,
    )


if __name__ == "__main__":
    print(json.dumps(extract(), indent=2))

"""Doom data readers handle valid minimal levels and damaged local saves."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from doom.rules import read_save, save_path
from doom.wad import Wad


def test_wad_level_with_one_subsector_and_no_bsp_nodes(tmp_path: Path) -> None:
    # One clockwise square is already convex: its sole subsector needs no nodes.
    lumps = [
        ("PLAYPAL", bytes(768)),
        ("E1M1", b""),
        ("THINGS", b""),
        ("LINEDEFS", b"".join(struct.pack("<7H", i, (i + 1) % 4, 1, 0, 0, i, 65535) for i in range(4))),
        ("SIDEDEFS", struct.pack("<hh8s8s8sh", 0, 0, b"-", b"-", b"WALL", 0) * 4),
        ("VERTEXES", struct.pack("<8h", 0, 0, 0, 64, 64, 64, 64, 0)),
        ("SEGS", b"".join(struct.pack("<6H", i, (i + 1) % 4, 0, i, 0, 0) for i in range(4))),
        ("SSECTORS", struct.pack("<HH", 4, 0)),
        ("NODES", b""),
        ("SECTORS", struct.pack("<hh8s8shhh", 0, 128, b"FLOOR", b"CEILING", 160, 0, 0)),
        ("REJECT", b"\0"),
        ("BLOCKMAP", b""),
    ]
    content, directory = bytearray(), bytearray()
    for key, data in lumps:
        directory.extend(struct.pack("<ii8s", 12 + len(content), len(data), key.encode("ascii")))
        content.extend(data)
    path = tmp_path / "square.wad"
    path.write_bytes(struct.pack("<4sii", b"PWAD", len(lumps), 12 + len(content)) + content + directory)

    level = Wad(path).level("E1M1")

    assert level["nodes"] == []
    assert len(level["polygons"]) == 1
    assert level["polygons"][0]["sector"] == 0
    assert {tuple(point) for point in level["polygons"][0]["points"]} == {(0, 0), (0, 64), (64, 64), (64, 0)}


def test_sector_query_with_one_subsector_and_no_bsp_nodes() -> None:
    from doom.level import LevelRuntime

    level = LevelRuntime()
    level.data = {
        "nodes": [],
        "leaves": [(1, 0)],
        "segs": [(0, 1, 0, 0, 0, 0)],
        "lines": [{"right": 0, "left": 65535}],
        "sides": [{"sector": 7}],
    }

    assert level.locate_sector(32, 32) == 7


@pytest.mark.parametrize("state", [None, [], 7, "invalid"])
def test_non_object_save_data_raises_a_load_error(tmp_path: Path, state: object) -> None:
    path = save_path(tmp_path, 0)
    path.parent.mkdir()
    path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid save data"):
        read_save(tmp_path, 0, "source")

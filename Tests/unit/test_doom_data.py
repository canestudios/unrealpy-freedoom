"""Doom data readers handle valid minimal levels; saves of other data, maps or skills are refused."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from doom import dataset
from doom.rules import check_save, save_path
from doom.wad import Wad


def test_extracted_data_and_wad_search_use_project_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    project = Path(__file__).resolve().parents[2]
    gameplay = project / "Content/Python/gameplay"
    assert dataset.DATASETS["doom"][1] == gameplay / "doom_local"
    assert dataset.DATASETS["freedoom1"][1] == gameplay / "doom_local_freedoom1"

    wad = project / "wads" / dataset.WAD_NAMES[0]
    monkeypatch.delenv("DOOM_WAD", raising=False)
    monkeypatch.setattr(dataset, "_in_folder", lambda folder: wad if folder == wad.parent else None)
    assert dataset.find_wad() == wad


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


def test_save_slots_are_named_per_data_set() -> None:
    assert save_path("FreedoomLocal", 0) == "FreedoomLocal-slot-0"
    assert save_path("DoomLocal", 5) == "DoomLocal-slot-5"
    for slot in (-1, 6):
        with pytest.raises(ValueError, match="Invalid save slot"):
            save_path("FreedoomLocal", slot)


@pytest.mark.parametrize(
    ("version", "source", "marker", "skill", "error"),
    [
        (2, "data", "E1M1", 3, "another game data version"),
        (1, "other", "E1M1", 3, "another game data version"),
        (1, "data", "E5M1", 3, "Invalid saved map"),
        (1, "data", "E1M1", 6, "Invalid saved difficulty"),
    ],
)
def test_saves_of_other_data_maps_or_skills_are_refused(
    version: int, source: str, marker: str, skill: int, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        check_save(version, source, "data", marker, skill)


def test_a_save_of_this_data_is_accepted() -> None:
    check_save(1, "data", "data", "E4M9", 5)

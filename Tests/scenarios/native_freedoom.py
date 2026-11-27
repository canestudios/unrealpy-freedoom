"""Verify the Freedoom campaign in a packaged desktop game built with NativeModules=doom.*."""

from __future__ import annotations

import importlib
import runpy
from importlib.machinery import ExtensionFileLoader
from pathlib import Path
from typing import Any

from doom import dataset, wad

ORIGINAL_MODULES = (
    "animation",
    "campaign",
    "common",
    "console",
    "dataset",
    "game",
    "geometry",
    "hud",
    "level",
    "lighting",
    "mode",
    "monsters",
    "music",
    "net",
    "player",
    "projectiles",
    "rules",
    "runtime",
    "specials",
    "state",
    "visual",
    "wad",
    "world",
)


async def demo(args: list[str]) -> dict[str, Any]:
    """Call with UnrealPyRun from the packaged game and the absolute path to this test script."""
    loaded = {}
    for leaf in ORIGINAL_MODULES:
        module = importlib.import_module(f"doom.{leaf}")
        assert isinstance(module.__loader__, ExtensionFileLoader), (leaf, module.__loader__)
        assert module.__file__ is not None, leaf
        path = Path(module.__file__)
        assert path.suffix in (".pyd", ".so") and path.is_file()
        assert not path.with_name(leaf + ".py").exists()
        assert not path.with_name(leaf + ".pyc").exists()
        loaded[leaf] = str(path)

    assert dataset.NAME == "freedoom1" and dataset.extracted()
    if iwad := next((arg.partition("=")[2] for arg in args if arg.startswith("iwad=")), ""):
        parsed = wad.Wad(Path(iwad))
        assert parsed.level("E1M1")["vertices"]
        assert parsed.patch("PLAYA1")[0] > 0

    campaign = runpy.run_path(str(Path(__file__).with_name("doom_campaign.py")))["demo"]
    result = await campaign(args)
    assert "skipped" not in result
    return {"native": loaded, "campaign": result}

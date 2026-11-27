"""Data set selection from DOOM_IWAD, plus WAD discovery. No game data lives in the repository."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

GAMEPLAY = Path(__file__).resolve().parents[1]
REPO = GAMEPLAY.parents[2]

# name -> (WAD file names looked up in wads/, local extraction folder, Unreal content root)
DATASETS: dict[str, tuple[tuple[str, ...], Path, str]] = {
    "doom": (("doom.wad",), GAMEPLAY / "doom_local", "/Game/DoomLocal"),
    "freedoom1": (("freedoom1.wad",), GAMEPLAY / "doom_local_freedoom1", "/Game/FreedoomLocal"),
}


def _default_name() -> str:
    """Without DOOM_IWAD: the retail data set, unless only Freedoom is extracted (a shared build carries
    Freedoom only and has no environment to set)."""
    extracted = [name for name, (_, folder, _) in DATASETS.items() if (folder / "manifest.json").is_file()]
    return extracted[0] if extracted else "doom"


NAME = os.environ.get("DOOM_IWAD", "").strip().lower() or _default_name()
if NAME not in DATASETS:
    raise ValueError(f"Unknown DOOM_IWAD {NAME!r}; expected one of {sorted(DATASETS)}")
WAD_NAMES, ASSETS, CONTENT = DATASETS[NAME]


def _install_candidates() -> list[Path]:
    """Standard install locations of the retail Doom IWAD (only used for the `doom` data set)."""
    steam = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Steam/steamapps/common"
    gog = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "GOG Galaxy/Games"
    return [
        steam / "Ultimate Doom/base/DOOM.WAD",
        steam / "Ultimate Doom/rerelease/DOOM.WAD",
        gog / "Doom/DOOM.WAD",
        gog / "DOOM/DOOM.WAD",
        gog / "Ultimate Doom/DOOM.WAD",
    ]


def _in_folder(folder: Path) -> Path | None:
    if not folder.is_dir():
        return None
    wanted = set(WAD_NAMES)
    return next((p for p in sorted(folder.iterdir()) if p.is_file() and p.name.lower() in wanted), None)


def find_wad() -> Path:
    """Locate the WAD of the selected data set: DOOM_WAD, then <repo>/wads, then install locations."""
    explicit = os.environ.get("DOOM_WAD", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"DOOM_WAD points to a missing file: {path}")
        return path
    local = _in_folder(REPO / "wads")
    if local is not None:
        return local
    if NAME == "doom":
        for candidate in _install_candidates():
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(
        f"No WAD found for data set {NAME!r} (DOOM_IWAD). Set DOOM_WAD to the file, or put "
        f"{'/'.join(WAD_NAMES)} in the git-ignored wads/ folder at the repo root. See README.md."
    )


def extracted() -> bool:
    """True once the editor importer has extracted this data set. The WAD is no longer required."""
    return (ASSETS / "manifest.json").is_file()


def find_fluidsynth() -> Path | None:
    """FluidSynth command line: FLUIDSYNTH (exe path), then `fluidsynth` on PATH; None when missing."""
    explicit = os.environ.get("FLUIDSYNTH", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    found = shutil.which("fluidsynth")
    return Path(found) if bool(found) else None


def find_soundfont() -> Path | None:
    """General MIDI SoundFont: DOOM_SOUNDFONT (.sf2), then common Linux paths; None if missing."""
    explicit = os.environ.get("DOOM_SOUNDFONT", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    candidates = [
        Path("/usr/share/sounds/sf2/FluidR3_GM.sf2"),
        Path("/usr/share/soundfonts/default.sf2"),
        Path("/usr/share/soundfonts/FluidR3_GM.sf2"),
        Path("/usr/share/sounds/sf2/default-GM.sf2"),
        Path("/usr/share/soundfonts/GeneralUser-GS.sf2"),
        Path("/usr/share/sounds/sf2/GeneralUser-GS.sf2"),
    ]
    return next((p for p in candidates if p.is_file()), None)

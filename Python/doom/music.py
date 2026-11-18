from __future__ import annotations

from pathlib import Path

import ue
from doom.dataset import CONTENT

MUSIC_VOLUME = 1.0


@ue.uclass
class DoomMusic(ue.ActorComponent):
    """Original score: MIDI rendered to looping SoundWaves at import (FluidSynth), played as 2D audio."""

    def post_init(self) -> None:
        self.audio: ue.AudioComponent | None = None
        self.error = 0
        self.current = ""

    @property
    def ready(self) -> bool:
        """True while the music is playing."""
        return self.audio is not None and self.audio.is_valid() and bool(self.audio.is_playing())

    def play(self, filename: str) -> None:
        """Start the track of a "D_E1M1.mid" style name; the SoundWave loops (set at import)."""
        self.stop()
        self.current = filename
        name = Path(filename).stem
        sound = ue.load_object(f"{CONTENT}/music/{name}.{name}")
        if not isinstance(sound, ue.SoundWave):
            self.error = 1
            ue.log(f"Doom music unavailable ({name}); see README.md, Music.")
            return
        self.error = 0
        self.audio = ue.GameplayStatics.spawn_sound2d(sound, MUSIC_VOLUME, world_context_object=self)

    def stop(self) -> None:
        if self.audio is not None and self.audio.is_valid():
            self.audio.stop()
        self.audio = None

# Freedoom on UnrealPy

Freedoom runs in Unreal Engine 5.8 on Windows and Linux with its player, monsters, weapons and HUD written in [Python](Python/doom). Unreal renders the levels, and the game supports co-op and deathmatch.

The WebAssembly build is on the `experiment/wasm` branch (UE 5.9 Preview).

Start with the [monster behavior](Python/doom/monsters.py) or the [game mode](Python/doom/mode.py) to explore the code. A small C++ module supplies the Unreal project target. [Plugin compatibility](https://unrealpy.canestudios.xyz/docs/getting-started/compatibility/)

It is an independent reimplementation, written from how the game plays rather than from id Software's source
release, and contains none of that code. Animation timings and the monsters' decision-making are this project's
own, so the game plays close to the original but not exactly like it; map titles and par times come from the data
set (Freedoom sets both; a WAD without them shows the map number and no par).

**This repository ships no Doom data.** No WAD, texture, sprite, sound or music is committed; everything is
extracted from a WAD you own (or the free Freedoom) at import time into git-ignored folders.

## Requirements

- Unreal Engine 5.8 on Windows or Linux (the commands below are for Windows and use the engine's install folder
  as `<UE>`; on Linux the binaries are `<UE>/Engine/Binaries/Linux/UnrealEditor` and `UnrealEditor-Cmd`).
- The **UnrealPy** plugin and its companion **ScriptCore**. They are distributed separately and are not part of this
  repository: copy them into `Plugins/` (`Plugins/UnrealPy`, `Plugins/ScriptCore`) or install them into the engine.
- A WAD (below).

The project turns Unreal's engine plugins off by default (`DisableEnginePluginsByDefault` in `UnrealPyDoom.uproject`)
and enables only what the game uses: procedural meshes for the levels, Enhanced Input, the animation compression
the engine expects, the network driver for co-op, each platform's device profile selector, and in the
editor the asset scripting the importer uses, the Content Browser's asset view and Cascade (the engine's renderer
settings expect its console variables, and cooking fails without them). The other plugins cost build and package
size and are never touched, so the editor opens without most of the tools a new project shows.

Open `UnrealPyDoom.uproject` in the editor once. On that first start UnrealPy creates the Python environment
(`.venv`, from `pyproject.toml` and `uv.lock`; it needs internet once) and the `ue` type stubs that editors and the
unit tests use.

In the commands below:

```powershell
$ue = "<UE>\Engine\Binaries\Win64\UnrealEditor.exe"         # the editor, and the game with -game
$uecmd = "<UE>\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"  # the same, headless (logs to the console)
$project = "<repo>\UnrealPyDoom.uproject"
```

`-UnrealPyRun=module:function` makes UnrealPy call that Python function once the engine is up, and
`-UnrealPyResult=<file.json>` writes what it returned (or the error) to a file.

## Get a WAD

- `doom`: your own copy of Doom / Ultimate Doom (Steam or GOG), `DOOM.WAD`.
- `freedoom1`: Freedoom Phase 1, BSD-licensed, free from <https://freedoom.github.io>.

## Where the WAD is found

For the selected data set, first match wins:

1. `DOOM_WAD`: explicit path to the file.
2. `wads/` at the repo root (git-ignored): `DOOM.WAD`, `doom.wad` or `freedoom1.wad` (case-insensitive).
3. `doom` only: the default Steam (`Ultimate Doom/base` or `rerelease`) and GOG install folders.

If none exists the importer fails naming the data set and pointing here. `DOOM_IWAD` picks the data set
(`doom` or `freedoom1`; unset, `doom` unless only Freedoom is extracted); each has its own extraction folder (`Python/doom_local[_freedoom1]/`)
and Unreal content root (`/Game/DoomLocal`, `/Game/FreedoomLocal`). All of these are git-ignored.

## Import (once per data set)

```powershell
$env:DOOM_IWAD = 'freedoom1'   # optional; default is doom
& $uecmd $project -nullrhi -unattended -nosplash -nopause "-UnrealPyRun=doom.importer:main"
```

This runs in the editor (no `-game`): it extracts maps, textures, sprites, sounds and music from the WAD and
imports them as Unreal assets. After that the game no longer reads the WAD. It takes a few minutes.

## Music

The score is rendered once, at import: each extracted `D_*.mid` is turned into a WAV with the FluidSynth
command line and a General MIDI SoundFont, then imported as a looping `SoundWave` under `<content root>/music`
(22.05 kHz mono WAVs, each peak-normalized to about -1 dBFS so every score is equally loud; they stay in the
git-ignored extraction folder). In the game the music is a plain Unreal 2D sound, so it plays on every platform.
Set these before running the importer:

- **Windows**: download the FluidSynth release zip (github.com/FluidSynth/fluidsynth/releases) and a free
  SoundFont such as GeneralUser GS (github.com/mrbumpy409/GeneralUser-GS); set `FLUIDSYNTH` to `fluidsynth.exe`
  and `DOOM_SOUNDFONT` to the `.sf2` file.
- **Ubuntu**: `sudo apt install fluidsynth fluid-soundfont-gm`; both are found automatically (`fluidsynth` on
  `PATH`, `/usr/share/sounds/sf2/FluidR3_GM.sf2`).

Without FluidSynth or a SoundFont the import logs one line and the game runs silent. Already imported tracks
are not rendered again; playback needs no environment variables.

## Play

```powershell
& $ue $project -game -windowed -ResX=1280 -ResY=720 "-UnrealPyRun=doom.game:play"
```

Set `DOOM_IWAD` as for the import when you play the Freedoom data set.

Controls: WASD move, mouse look, left click fire, E use, Shift run, 1-8 weapons (1 toggles fist and
chainsaw) or mouse wheel, Tab automap, R restart level, Enter next level after the exit, Escape menu
(new game, load, save, multiplayer, resume, lighting, quit), F5 quick save, F9 quick load.

Cheat console (F1 or Escape to close; Up/Down recall history), the Doom cheat codes:

| Command | Effect |
| --- | --- |
| `IDDQD` | god mode (toggle) |
| `IDFA` | all weapons, full ammo, armor |
| `IDKFA` | also all keys |
| `IDCLEVxy` | warp to episode x, map y (a new game there) |
| `IDCLIP` | no clipping (toggle): walls and things stop blocking, the marine flies level |
| `IDBEHOLDx` | toggle a power: `V` invulnerability, `S` berserk, `I` invisibility, `R` radiation suit, `A` automap, `L` light amp (`IDBEHOLD` alone lists them) |
| `IDCHOPPERS` | the chainsaw |
| `IDMYPOS` | your position and angle |
| `IDDT` | cycles the automap: as it is, every line, every line and the things |
| `IDMUSxy` | plays the music of episode x, map y (on this machine only) |
| `CLEAR`, `HELP` | |

The automap (Tab) shows walls and special lines; with the automap power (`IDBEHOLDA`) it also shows the steps and
ledges, with `IDDT` every line and then the monsters and items.

<details>
<summary>Save format and crusher mechanics</summary>

Saves are the engine's own save games: a `DoomSave` object (`savegame.py`) in slot `<data set>-slot-N`, which the
engine keeps as `Saved/SaveGames/FreedoomLocal-slot-N.sav` (in a packaged game, under the user's local
application data). Slot 0 is the autosave at level start, slot 5 the quick save; a save is bound to the SHA-256 of
the imported data. Unreal properties have no maps or unsigned numbers, so the game's dicts are kept as lists of
structs that carry their key, and the `random` module's state as signed 32-bit words.

Crushers follow `P_ChangeSector`: a ceiling (linedef specials 6, 25, 44, 49, 72, 73, 77, 141) that closes on
a marine, a monster or a barrel deals 10 damage every fourth tic (in a deathmatch the level's kill is a suicide,
-1 frag), corpses in the way turn into gibs (`POL5`) and dropped items vanish. The ceiling slows to 1/8 speed while
it squeezes something, except the fast crushers (6, 77), and goes on to the floor. A ceiling that does not crush
(41, 43, 40) stops against what is in its way; a closing door reopens, except the plain `close` doors.

</details>

## Co-op

Up to four marines play Doom's cooperative game on one map, through the whole campaign: every map, the secret
exits, the boss levels and the end of each episode. Single-player is unchanged: it is the same code with one
local player (a listen server or the standalone game).

Host and join from the main menu's **MULTIPLAYER** screen. The host picks the game (co-op, deathmatch, altdeath),
the episode and map, monsters and the frag and time limits, then **HOST GAME**: a listen server that starts the map
and waits. Every other player (one client per machine, up to three besides the host) types the host's address on
the **JOIN** row and presses Enter (the game uses UDP port 7777; `address:port` selects another one). This works in
every build, a Shipping package included. In a network game, the menu's **LEAVE GAME** goes back to the
single-player title (the host's ends the game for everybody).

The same from the command line, in an editor build (a Shipping package has no `-UnrealPyRun`):

```powershell
# the host
& $ue $project -game -windowed -ResX=1280 -ResY=720 "-UnrealPyRun=doom.game:host"
# every other player: DOOM_SERVER is the host's address (default 127.0.0.1; the game uses UDP port 7777,
# "address:port" selects another one)
$env:DOOM_SERVER = "192.168.1.20"
& $ue $project -game -windowed -ResX=1280 -ResY=720 "-UnrealPyRun=doom.game:join"
```

Every machine needs the extracted data and imported assets of the same data set (see above): a client builds the
level from its own copy of the map and only receives state. A client may join at any time: it gets the current map
(and whatever the intermission or the episode end is showing) and the state of every marine. Headless, for a test,
add `-nullrhi -unattended -nosplash -nopause` (`-RenderOffscreen` to draw), start the host first, and give each
process its own `-abslog`.

How it works:

- **The server simulates.** The game mode exists only on the server: monster AI, line crossings and specials,
  doors and lifts, damage, pickups, projectiles. None of that runs on a client.
- **What replicates.** `DoomGameState` carries the map and a serial (clients rebuild the native geometry when it
  changes), the heights of the doors, floors and ceilings (one float array, applied to the client's own
  geometry), the pressed switches, the totals, the intermission and episode-end flags and the name of the game
  rules. `DoomPlayerState` carries each marine's health, armor, ammo, weapon, keys, powerup expiry times, the
  level score (kills, items, secrets, frags) and weapon animation counters.
  Monsters, pickups, barrels and projectiles are replicated actors (position through replicated movement, plus
  a compact pose: sprite frame, facing, dead); each client picks the rotation frame from its own camera.
  Pickups replicate `taken`, barrels `exploded`. Puffs, blood, teleport flashes and one-shot sounds are
  multicast events (sounds get quieter with distance); music, lighting and the menu stay local to each machine.
  Each machine applies the screen settings (fixed exposure, no anti-aliasing) and the lighting itself: the game mode on
  the server, the game state on a client. Unreal mutes a window that loses focus (`[Audio] UnfocusedVolumeMultiplier`,
  0 by default): with two windows on one PC, only the focused one is heard.
- **Input.** Movement is Unreal's character movement. Fire, use, weapon switches, running and cheats are requests
  the controller sends to the server (`to_server_*`); a client sends its own aim direction (it knows its viewport)
  and the server resolves the hits.
- **Rules.** Each player starts at its Doom player start (things 1 to 4). A dead player comes back after three
  seconds at its start with the pistol and without keys. Weapons and keys stay on the floor (each marine takes
  one of each). An exit used by anyone ends the level for everyone. Nothing pauses: Escape opens a menu (resume,
  lighting, leave game, quit) over the running game. Saving and loading are single-player only.
  `rules.MatchRules` (`COOP`, `DEATHMATCH`, `ALTDEATH`) holds what differs between the network game modes (weapons
  stay, inventory carries over, frags count, random spawns, item respawn, cheats allowed); the game state
  replicates the active one by name and `mode.match` returns it.
- **Level changes.** The intermission lasts eight seconds (Enter on any machine skips it), then the server loads
  the next map and every client rebuilds it. Vanilla co-op rules apply: health, armor, weapons and ammo carry
  over; keys, powerups (invulnerability, berserk, invisibility, radiation suit, light amp) and the automap power are
  cleared; a marine that is dead at the exit starts the next map like a new one. Secret exits go to the
  secret map and come back as in single-player (E1M3 to E1M9 to E1M4, and so on). The level score starts again on
  each map.
- **End of an episode.** After the last map of an episode (a boss level, or the exit of E?M8) every machine shows
  the "Episode complete" screen for twelve seconds, then the server starts the first map of the next episode with
  new marines (episode 4 returns to episode 1).
- **Intermission statistics.** Kills, items and secrets are counted per marine on the server: a kill goes to the
  marine whose shot, rocket, plasma or barrel explosion did the damage, an item to the marine that picked it up,
  a secret to the first marine to enter the sector. The intermission shows, on every machine, one row per marine
  (`P1`..`P4`) with kills %, items %, secrets % and frags (in co-op the kills of other marines, as in vanilla),
  then the time and the par (when the data set sets one). It is drawn as text in the
  single-player intermission's style; the data set's `WI*` graphics are not used by it.
- **Cheats.** Vanilla netgames disable cheats except in co-op, where they work, and so does the console here
  (`MatchRules.cheats`). On a client the console routes `IDDQD`, `IDFA`, `IDKFA`, `IDCLIP`, `IDBEHOLDx` and
  `IDCHOPPERS` to the server, which applies them to that client's own marine and answers in the console.
  `IDCLEVxy` changes the map for everybody, so only the host may use it (a client gets "ONLY THE HOST CAN CHANGE THE
  MAP"). `IDMYPOS`, `IDDT` and `IDMUSxy` are local to each machine.
- **Nightmare.** The server respawns dead monsters as in Doom (a corpse older than twelve seconds, a 4/256
  roll every 32 tics): both the corpse's spot and the spawn spot get a teleport fog and sound (multicasts), and the
  same replicated actor's `dead` flag and position change, so the corpse disappears and the monster stands again at
  its spawn point on every client.

Not yet: restarting the level from a client.

### Deathmatch

The host picks the game on the multiplayer screen or, with `doom.game:host`, with options as environment variables
or `key=value` arguments. Either way they travel in the map's URL (`?listen?match=deathmatch?fraglimit=10`), where the
game mode reads them (`net.host_options`):

| Option | Env | Values |
| --- | --- | --- |
| `match` | `DOOM_MATCH` | `coop` (default), `deathmatch` (Doom's `-deathmatch`), `altdeath` (`-altdeath`, deathmatch 2.0) |
| `monsters` | `DOOM_MONSTERS` | `0` or `1`; default `1` in co-op, `0` in the deathmatch modes (Doom's `-nomonsters`) |
| `fraglimit` | `DOOM_FRAGLIMIT` | frags that end the level, `0` for none (default) |
| `timelimit` | `DOOM_TIMELIMIT` | minutes that end the level, `0` for none (default) |
| `map` | `DOOM_MAP` | the first map, e.g. `E1M5` (default `E1M1`) |

```powershell
$env:DOOM_MATCH = "deathmatch"; $env:DOOM_FRAGLIMIT = "10"; $env:DOOM_TIMELIMIT = "15"; $env:DOOM_MAP = "E1M5"
& $ue $project -game -windowed -ResX=1280 -ResY=720 "-UnrealPyRun=doom.game:host"
```

`host` also takes the options as `key=value` arguments: a JSON list such as
`["match=altdeath", "monsters=1", "fraglimit=20"]` in a file named by `-UnrealPyArgsFile=<file>`. They override the
environment.

Everybody else joins as in co-op (`doom.game:join`): the clients learn the mode from the replicated game
state, so they need no option. The rules follow Doom 1.9:

- **Spawns.** A marine starts, and comes back after dying (three seconds later), at one of the map's deathmatch starts
  (thing 11, the first ten): twenty random tries for a start nobody stands on. When none is free it arrives on a
  random start anyway and telefrags whoever stands there (the frag is the arriving marine's). A map without
  deathmatch starts uses its four player starts. The marine always comes back with the pistol, 50 bullets, 100
  health and no keys.
- **Things.** The map's items, weapons and barrels are there, including the things flagged "not in single player"
  (16), which Doom spawns in every network game; monsters only with `monsters=1`.
- **Deathmatch 1.0.** Weapons stay on the floor and each marine takes each one once per life (a weapon gives five
  clips of ammo); keys stay; ammo, health and armor are taken for good and do not return.
- **Altdeath (2.0).** Weapons disappear when taken, and every item returns after 30 seconds in the item fog
  (`IFOG`) with its sound, except the invulnerability and invisibility spheres and a monster's drop, which never
  do. Keys still stay.
- **Frags.** Killing another marine (bullets, fists, a rocket or its splash, the BFG) gives the killer +1. A suicide
  gives -1: your own rocket splash, a barrel you set off that kills you, nukage, or the level itself. A monster's kill
  counts for nobody. The server keeps each marine's frags and who it killed (`DoomPlayerState.frags`, `frag_table`),
  replicated. The status bar shows the frags where the ARMS panel is (the weapon numbers are hidden), and the
  intermission shows the frag matrix (killers by victims, the diagonal is the suicides) with each marine's total.
  The frags start again on every map. Damage from monsters and the environment is never a frag by itself (the
  environment's counts only as a suicide). Co-op counts frags too, as vanilla does (no fraglimit and no status
  bar frags there, only the intermission column); `MatchRules.count_frags` is what makes the HUD, the frag matrix
  and the limits deathmatch-only.
- **Combat.** Every weapon hurts other marines, splash included (bullets, projectiles, splash and the BFG, in
  co-op as well: vanilla has friendly fire). Telefrag damage (10000) ignores god mode and
  invulnerability, as in Doom.
- **Level end.** An exit used by anyone ends the level for everyone, as in vanilla. So do the frag limit (the first
  marine to reach it) and the time limit (Doom's `leveltime`, which never pauses, so a level where everybody is dead
  still ends on time): the intermission shows the frag matrix for eight seconds, then the server loads the next
  map; the inventories do not carry over. Cheats are off in a deathmatch (`MatchRules.cheats`).

## Lighting

The look follows the project settings; the game forces nothing. At level start it reads the engine's console
variables and, when everything below is on, lights the game with Lumen (lit materials, point lights on torches,
lamps and barrels, flickering sectors, sun and sky light, muzzle and projectile flashes). Otherwise it keeps
Doom's flat unlit look, which is what this project's settings give.

In the lit look, switches, computer screens and lamp textures emit their bright, coloured pixels (so they light their
surroundings, with a small coloured point light in front of switches and big screens), lava, fire and nukage glow,
and water is a glossy Lumen mirror; `GLOW_CLASSES` and `LIQUIDS` in `lighting.py` list them (`DOOM_GLOW=0` turns
it off).

To get the lit look, enable in Project Settings > Engine > Rendering:

- Global Illumination: Dynamic Global Illumination Method = Lumen;
- Reflections: Reflection Method = Lumen;
- Hardware Ray Tracing: Support Hardware Ray Tracing, and Use Hardware Ray Tracing when available (Lumen);
- Default RHI = DirectX 12 with Shader Model 6;
- Optimizations: Support Compute Skin Cache (the engine refuses ray tracing without it).

Hardware ray tracing is needed because the procedural meshes have no distance fields, so Lumen's software
tracing cannot see them. The ray tracing and SM6 settings need an editor restart, and the GPU must support
DXR 1.1. Run the import once more afterwards so the lit materials exist.

In the Escape menu, the `LIGHTING: LIT / CLASSIC` row (Enter, or Left/Right) switches the look at runtime without
restarting the level; it appears only when the project settings above are on. Classic swaps every world and
sprite material back to the flat ones, destroys the point lights, sun and sky light, spawns no flashes, and sets
`r.DynamicGlobalIlluminationMethod 0` and `r.ReflectionMethod 0` so the frame does not pay for Lumen; Lit
restores the values read at startup. The choice lasts for the session, across level changes, restarts and loads.

While the look is lit, the menu shows three test sliders below it, drawn as Doom's options-menu thermometer
(`M_THERML/M_THERMM/M_THERMR` with the `M_THERMO` knob, a plain bar if the WAD lacks them) and adjusted with
Left/Right. They are live (no material rebuild, no re-import), neutral by default, and keep their values for the
session across level changes and lit/classic switches. They are hidden in the classic look and when it is
unsupported, and have no effect there.

- `WORLD BRIGHTNESS` (x0.25 to x3.00, 10 steps, neutral x1.00): scales the emission the lit materials give from the
  texture and sector light (`DoomEmissiveMin`, `DoomEmissiveScale` and `DoomEmissive`, set on every material
  instance), so it brightens or darkens the world and what Lumen bounces.
- `LIGHT INTENSITY` (x0.25 to x3.00, 10 steps, neutral x1.00): multiplies the point lights, the sector lights, the
  muzzle and projectile flashes and the sun (not the sky light).
- `EXPOSURE` (-2.0 to +2.0 EV, 0.5 steps, neutral 0): an exposure bias on an unbound post process volume that
  lives with the lit rig. Doom's fixed exposure (`r.EyeAdaptationQuality 0`) ignores a bias, so while lit the
  volume turns eye adaptation on and pins its brightness range to 1, which looks like the fixed exposure.
- Enter on a slider resets it; the `RESET LIGHTING` row resets all three.

`DOOM_LIGHTING=unlit` forces the classic look at start (the menu can still switch it on when supported);
`DOOM_LIGHTING=lit` logs one warning naming the missing settings and falls back to unlit when they are not all on.
Tuning env: `DOOM_LIGHT_UNIT`, `DOOM_SUN_LUX`, `DOOM_EMISSIVE_MIN/SCALE`, `DOOM_INDIRECT`.

## Test

Unit tests, lint and type checks run outside the engine, on UnrealPy's engine-less `ue` and its stubs (written at
the first editor start). The type check matters most: the stubs list every Unreal type by its real name, so `ty`
reports a call to one that does not exist, which would otherwise fail only when the game reaches it.

```powershell
uv sync --all-groups
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m ruff check Python Tests
.venv\Scripts\python.exe -m ty check Python Tests
```

The engine checks run headless in the game. `-UnrealPySelfHost` makes UnrealPy start its own interpreter, as a
packaged game does; the exit code is 0 when the check passed, and the result file says what it found:

```powershell
$headless = "-game", "-nullrhi", "-unattended", "-nosplash", "-nopause", "-UnrealPySelfHost"
# E1M1 gameplay: monsters, weapons, specials, crushers, the console cheats (retail data set only)
& $uecmd $project @headless "-UnrealPyRun=doom.game:demo" "-UnrealPyResult=Saved\demo.json"
# every map, all skills, live walls, save/restore, secret exits (either data set; needs the rendered music)
& $uecmd $project @headless "-UnrealPyRun=Tests/scenarios/doom_campaign.py:demo" "-UnrealPyResult=Saved\campaign.json"
```

The demo checks retail E1M1 and E2M2 by their geometry, so it needs the `doom` data set. It also runs the console
cheats (`IDCLIP`, `IDBEHOLD`, `IDCHOPPERS`, `IDMYPOS`, `IDDT`, `IDMUS`, `IDDQD`, `IDFA`, `IDKFA`) and lets E2M2's
crushers (specials 73 and 77) kill a marine, kill a monster, gib a corpse and remove a dropped item. The campaign
check reports `skipped` when the data set is not extracted; it backs up and restores save slots 0 and 4.

## Modules (`Python/doom`)

| Module | Role |
| --- | --- |
| `dataset` | Data set selection (`DOOM_IWAD`) and WAD discovery |
| `wad` | WAD reader and extractor (levels, graphics, sounds, music) to the local folder |
| `importer` | Editor-side import of the extracted files as Unreal assets and materials |
| `game` | Entry points: `play`, `host`, `join`, `demo`; level-start orchestration |
| `mode` | `DoomHangarMode`, the game mode (the simulation): per-level state, firing, use, tick, co-op rules |
| `level` | `LevelRuntime`: the level on one machine (data, materials, geometry, queries), shared by the game mode and the game state |
| `state` | `DoomPlayerState` (one marine's inventory) and `DoomGameState` (map, moving sectors, totals), both replicated |
| `net` | Network helpers: roles, per-instance replication, player lookup, the host's options (`DOOM_MATCH`...) |
| `campaign` | Menus, level loading and progression, save/load (the snapshot of a game and its restore) |
| `savegame` | `DoomSave` (a `SaveGame`) and the structs it holds; writing, reading and labelling the slots |
| `rules` | Static rules: monsters, weapons, items, skills, the network game modes, the save slots' names and checks |
| `specials` | Linedef actions: doors, lifts, switches, teleports, crushers |
| `geometry` | Live sector walls and sky-ceiling collision |
| `world` | Level actors: geometry, sprites, barrels, effects |
| `monsters` | `DoomDemon` AI and attacks |
| `projectiles` | Fireballs and rockets |
| `player` | `DoomMarine`, input class and `DoomController` (controls, and the client's requests to the server) |
| `animation` | Frame and state tables for attacks and deaths |
| `visual` | Sprite view selection (rotations, mirrored lumps) |
| `hud` | `DoomHUD`: status bar, weapon, automap, menus |
| `console` | F1 cheat console: the cheat codes (on a client they go to the server through `to_server_cheat`) |
| `music` | `DoomMusic`: plays the rendered score as looping 2D Unreal audio |
| `common`, `runtime` | Shared constants/helpers, and a facade namespace over them |

The classes are found through the `doom` class package (`Config/DefaultUnrealPy.ini`, `+ClassPackages=doom`).

## Licences and contact

Cane Studios’ gameplay code and documentation use the [MIT License](LICENSE). Game data comes from [Freedoom](https://freedoom.github.io/) under its [BSD licence](FREEDOOM-COPYING.txt). UnrealPy, Unreal Engine and other dependencies keep their own licences.

[contact@canestudios.xyz](mailto:contact@canestudios.xyz)

## Trademarks

DOOM is a trademark of id Software / ZeniMax Media. This project is not affiliated with or endorsed by them, and
contains none of their data.

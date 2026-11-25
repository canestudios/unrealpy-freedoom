"""The saved game: an engine SaveGame object in a slot that the engine keeps (Saved/SaveGames/<slot>.sav, the
browser's persistent storage on the web).

Unreal properties have no maps, sets or unsigned numbers. The snapshot's dicts are lists of structs that carry
their key, and Python's generator state is kept as signed 32-bit words.
"""

from __future__ import annotations

import ue
from doom.dataset import CONTENT
from doom.rules import check_save, save_path

# The data set's content folder names its slots, which keeps the saves of each data set apart.
SLOT_PREFIX = CONTENT.rsplit("/", 1)[-1]


def _vector() -> ue.Vector:
    return ue.Vector(0.0, 0.0, 0.0)


def _rotator() -> ue.Rotator:
    return ue.Rotator(0.0, 0.0, 0.0)


@ue.ustruct
class SavedInventory(ue.StructBase):
    """What campaign.inventory returns: the INVENTORY fields and the weapons."""

    god_mode: bool = False
    health: int = 100
    armor: int = 0
    bullets: int = 50
    shells: int = 0
    rockets: int = 0
    cells: int = 0
    weapon: str = "pistol"
    backpack: bool = False
    berserk: bool = False
    armor_type: int = 1
    invulnerability: float = 0.0
    suit: float = 0.0
    invisibility: float = 0.0
    light_visor: float = 0.0
    all_map: bool = False
    weapons: list[str] = ue.uproperty(default_factory=list)


@ue.ustruct
class KeyKind(ue.StructBase):
    """A key the marine holds and the thing it came from."""

    colour: str = ""
    kind: int = 0


@ue.ustruct
class SwitchTimer(ue.StructBase):
    """A switch that pops back out when its timer runs out."""

    line: int = 0
    timer: float = 0.0


@ue.ustruct
class SavedDoor(ue.StructBase):
    """A door of the level, by its sector."""

    sector: int = 0
    height: float = 0.0
    target: float = 0.0
    opened: bool = False
    timer: float = 0.0
    closed: float = 0.0
    speed: float = 0.0
    reopen: bool = False
    stays: bool = False


@ue.ustruct
class SavedMover(ue.StructBase):
    """A floor of the level, by its sector."""

    sector: int = 0
    kind: str = ""
    speed: float = 0.0
    target: float = 0.0
    offset: float = 0.0
    goal: float = 0.0
    wait: float = 0.0
    active: bool = False
    high: float = 0.0


@ue.ustruct
class SavedCeiling(ue.StructBase):
    """A ceiling of the level, by its sector."""

    sector: int = 0
    offset: float = 0.0
    goal: float = 0.0
    speed: float = 0.0
    active: bool = False
    low: float = 0.0
    high: float = 0.0
    cycle: bool = False
    crush: bool = False
    slows: bool = False
    base_speed: float = 0.0


@ue.ustruct
class ActionFrame(ue.StructBase):
    """A frame of a monster's attack: its sprite letter, how many tics, whether it strikes as it begins."""

    letter: str = ""
    tics: int = 0
    strikes: bool = False


@ue.ustruct
class SavedThing(ue.StructBase):
    """An object of the level. `fields` names the members below that the object has (OBJECT_FIELDS of
    campaign): the rest keep their defaults and are not restored."""

    role: str = ""
    id: int = -1
    position: ue.Vector = ue.uproperty(default_factory=_vector)
    hidden: bool = False
    owner_id: int = -1
    fields: list[str] = ue.uproperty(default_factory=list)
    kind: int = 0
    prefix: str = ""
    health: int = 0
    dead: bool = False
    awake: bool = False
    clock: float = 0.0
    frame: str = ""
    key: str = ""
    taken: bool = False
    dropped: bool = False
    exploded: bool = False
    anim: list[ActionFrame] = ue.uproperty(default_factory=list)
    anim_time: float = 0.0
    fired: bool = False
    action_event: int = -1
    facing: float = 0.0
    charge_time: float = 0.0
    charge_direction: list[float] = ue.uproperty(default_factory=list)
    age: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0
    speed: float = 0.0
    damage: int = 0
    radius: float = 0.0
    weapon: str = ""
    friendly: bool = False
    stage: str = ""
    family: str = ""
    sprayed: bool = False
    spawn_x: float = 0.0
    spawn_y: float = 0.0
    spawn_z: float = 0.0
    spawn_health: int = 0
    type_id: int = 0


@ue.uclass
class DoomSave(ue.SaveGame):
    """A single-player game in a slot, bound to the SHA-256 of the imported data."""

    version: int = ue.uproperty(1)
    source_sha256: str = ue.uproperty("")
    map: str = ue.uproperty("")
    skill: int = ue.uproperty(3)
    inventory: SavedInventory = ue.uproperty(default_factory=SavedInventory)
    keys: list[str] = ue.uproperty(default_factory=list)
    key_kinds: list[KeyKind] = ue.uproperty(default_factory=list)
    player: ue.Vector = ue.uproperty(default_factory=_vector)
    rotation: ue.Rotator = ue.uproperty(default_factory=_rotator)
    elapsed: float = ue.uproperty(0.0)
    cooldown: float = ue.uproperty(0.0)
    weapon_action: str = ue.uproperty("")
    weapon_clock: float = ue.uproperty(0.0)
    weapon_event: int = ue.uproperty(0)
    flash_variant: int = ue.uproperty(0)
    pickup_flash: float = ue.uproperty(0.0)
    berserk_flash: float = ue.uproperty(0.0)
    kills: int = ue.uproperty(0)
    item_count: int = ue.uproperty(0)
    secrets: list[int] = ue.uproperty(default_factory=list)
    triggered: list[int] = ue.uproperty(default_factory=list)
    switches: list[int] = ue.uproperty(default_factory=list)
    switch_timers: list[SwitchTimer] = ue.uproperty(default_factory=list)
    won: bool = ue.uproperty(False)
    secret_exit: bool = ue.uproperty(False)
    dead: bool = ue.uproperty(False)
    doors: list[SavedDoor] = ue.uproperty(default_factory=list)
    movers: list[SavedMover] = ue.uproperty(default_factory=list)
    ceilings: list[SavedCeiling] = ue.uproperty(default_factory=list)
    objects: list[SavedThing] = ue.uproperty(default_factory=list)
    # random.getstate(): its version, its 625 words (unsigned 32-bit, kept as signed), the pending gauss value
    random_version: int = ue.uproperty(3)
    random_words: list[int] = ue.uproperty(default_factory=list)
    random_gauss: float = ue.uproperty(0.0)
    random_has_gauss: bool = ue.uproperty(False)


def signed_word(value: int) -> int:
    """An unsigned 32-bit word as the signed int32 with the same bits."""
    return value - (1 << 32) if value >= 1 << 31 else value


def unsigned_word(value: int) -> int:
    return value & 0xFFFFFFFF


_labels: dict[int, str] = {}  # slot_label's text per slot, until the slot is written again


def new_save() -> DoomSave:
    state = ue.GameplayStatics.create_save_game_object(DoomSave)
    if not isinstance(state, DoomSave):
        raise TypeError("the engine did not create a DoomSave")
    return state


def write_save(slot: int, state: DoomSave) -> None:
    name = save_path(SLOT_PREFIX, slot)
    state.version = 1
    _labels.pop(slot, None)
    if not ue.GameplayStatics.save_game_to_slot(state, name, 0):
        raise OSError(f"could not write {name}")


def stored(slot: int) -> DoomSave | None:
    """What a slot holds, unchecked (None when it holds no DoomSave)."""
    name = save_path(SLOT_PREFIX, slot)
    if not ue.GameplayStatics.does_save_game_exist(name, 0):
        return None
    state = ue.GameplayStatics.load_game_from_slot(name, 0)
    return state if isinstance(state, DoomSave) else None


def read_save(slot: int, source_sha256: str) -> DoomSave:
    """The game in a slot, refused when it was made for other game data, or a map or skill that does not
    exist."""
    name = save_path(SLOT_PREFIX, slot)
    if not ue.GameplayStatics.does_save_game_exist(name, 0):
        raise OSError(f"no save in {name}")
    state = stored(slot)
    if state is None:
        raise ValueError("Invalid save data: expected a Doom save")
    check_save(state.version, state.source_sha256, source_sha256, state.map, state.skill)
    return state


def restore(slot: int, state: DoomSave | None) -> None:
    """Put back what a slot held (`stored`): its save, or nothing."""
    if state is None:
        ue.GameplayStatics.delete_game_in_slot(save_path(SLOT_PREFIX, slot), 0)
        _labels.pop(slot, None)
    else:
        write_save(slot, state)


def slot_label(slot: int) -> str:
    if slot not in _labels:
        state = stored(slot)
        _labels[slot] = (
            f"{slot}: {state.map} / SKILL {state.skill} / {int(state.elapsed)}s"
            if state is not None
            else f"{slot}: EMPTY"
        )
    return _labels[slot]

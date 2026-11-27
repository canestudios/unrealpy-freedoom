from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import ue
from doom import campaign, console
from doom.common import KEYS, SCALE, TIC, mode_now, show_sprite, xy
from doom.visual import sprite_view, view_rotation

if TYPE_CHECKING:
    from doom.state import DoomPlayerState

WEAPON_KEYS = (
    ("One", "fist"),
    ("Two", "pistol"),
    ("Three", "shotgun"),
    ("Four", "chaingun"),
    ("Five", "rocket"),
    ("Six", "plasma"),
    ("Seven", "bfg"),
    ("Eight", "chainsaw"),
)
WEAPON_CYCLE = ("fist", "chainsaw", "pistol", "shotgun", "chaingun", "rocket", "plasma", "bfg")
WALK_SPEED, RUN_SPEED = 500, 900


@ue.uclass
class DoomMarine(ue.Character):
    camera = ue.component(
        ue.CameraComponent,
        parent="capsule_component",
        relative_location=ue.Vector(0, 0, 25.05),
        field_of_view=90.0,
        use_pawn_control_rotation=True,
    )
    # A joiner is first spawned at the world origin (there are no PlayerStart actors), which may be inside the
    # geometry of the map in play: spawn anyway, the game mode moves the marine to its start right after.
    spawn_collision_handling_method = ue.ESpawnActorCollisionHandlingMethod.AlwaysSpawn
    # What the other players see of this marine: a camera-facing sprite (hidden on its own screen).
    sprite = ue.component(ue.MaterialBillboardComponent, parent="capsule_component")

    def post_init(self) -> None:
        self.frame = ""
        self.view: tuple[str, int] = ("", 0)
        self.flipped = False
        self.clock = 0.0
        self.death_clock = 0.0
        self.sprite_hidden: bool | None = None
        self.noclip_applied = False

    @property
    def doom_state(self) -> DoomPlayerState | None:
        """This marine's DoomPlayerState (None until the engine has assigned it)."""
        from doom import state

        ps = self.player_state
        return ps if isinstance(ps, state.DoomPlayerState) else None

    @property
    def start_index(self) -> int:
        """Which Doom player start (0-3) this marine belongs to."""
        ps = self.doom_state
        return int(ps.start_index) if ps is not None else 0

    def begin_play(self) -> None:
        # CMC floats ~2.15 UE units above its floor. Leave that space inside a Doom
        # 56-unit opening; otherwise exact-height doorways trap the full-height capsule.
        self.capsule_component.set_capsule_size(32, 54.8, True)
        self.capsule_component.set_collision_response_to_channel(
            ue.ECollisionChannel.ECC_Visibility, ue.ECollisionResponse.ECR_Block
        )
        self.character_movement.max_step_height = 24 * SCALE
        self.character_movement.max_walk_speed = WALK_SPEED
        self.character_movement.walkable_floor_angle = 60
        self.use_controller_rotation_yaw = True
        self.camera.post_process_blend_weight = 1.0
        self.sprite.set_mobility(ue.EComponentMobility.Movable)
        self.sprite.set_collision_enabled(ue.ECollisionEnabled.NoCollision)

    def apply_noclip(self) -> None:
        """IDCLIP on this machine's copy of the marine: walls and things stop blocking it and it flies level.

        The monsters still see it (the capsule keeps answering the visibility traces).
        """
        ps = self.doom_state
        want = bool(ps.noclip) if ps is not None else False
        if want == self.noclip_applied:
            return
        self.noclip_applied = want
        reply = ue.ECollisionResponse.ECR_Ignore if want else ue.ECollisionResponse.ECR_Block
        for channel in (ue.ECollisionChannel.ECC_WorldStatic, ue.ECollisionChannel.ECC_WorldDynamic):
            self.capsule_component.set_collision_response_to_channel(channel, reply)
        movement = self.character_movement
        movement.braking_deceleration_flying = 4096.0
        movement.max_fly_speed = float(movement.max_walk_speed)
        movement.set_movement_mode(ue.EMovementMode.MOVE_Flying if want else ue.EMovementMode.MOVE_Walking)

    def pose(self) -> str:
        """The sprite stem the marine shows now (PLAY + frame letter), from replicated state only."""
        ps = self.doom_state
        if ps is not None and getattr(ps, "dead", False):
            return (
                "PLAYN"
                if self.death_clock > 6 * 10 * TIC
                else "PLAY" + "HIJKLM"[int(self.death_clock / (10 * TIC)) % 6]
            )
        if ps is not None and getattr(ps, "pain", 0.0) > 0:
            return "PLAYG"
        if ps is not None and getattr(ps, "weapon_action", "") and getattr(ps, "weapon_clock", 9.0) < 0.3:
            return "PLAYF"
        velocity = self.get_velocity()
        if math.hypot(float(velocity[0]), float(velocity[1])) > 20:
            return "PLAY" + "ABCD"[int(self.clock / (4 * TIC)) % 4]
        return "PLAYA"

    def tick(self, delta_seconds: float) -> None:
        """Other players' marines are drawn as Doom sprites seen from the local camera."""
        mode = mode_now()
        if mode is None or not getattr(mode, "loaded_map", False):
            return
        self.apply_noclip()
        local = self.is_locally_controlled()
        if local != self.sprite_hidden:
            self.sprite_hidden = local
            self.sprite.set_hidden_in_game(local)
        if local:
            return
        self.clock += delta_seconds
        ps = self.doom_state
        self.death_clock = (
            self.death_clock + delta_seconds if ps is not None and getattr(ps, "dead", False) else 0.0
        )
        viewer = ue.GameplayStatics.get_player_pawn(0)
        facing = -float(self.get_actor_rotation()[1])
        rotation = view_rotation(*xy(self), *xy(viewer), facing) if viewer is not None else 1
        stem = self.pose()
        if (stem, rotation) == self.view:
            return
        self.view = (stem, rotation)
        key, flipped = sprite_view(mode.data["sprites"], stem, rotation)
        if not key and stem == "PLAYN":
            key, flipped = sprite_view(mode.data["sprites"], "PLAYL", rotation)
        if not key or (key == self.frame and flipped == self.flipped):
            return
        self.frame, self.flipped = key, flipped
        show_sprite(self.sprite, mode, key, flipped, -54.8)


@ue.uclass
class DoomInput(ue.PlayerInput):
    # Gameplay owns F5/F9: Engine defaults switch shader view / take a screenshot.
    debug_exec_bindings = []


@ue.uclass
class DoomController(ue.PlayerController):
    """Reads this machine's input. A client asks the server to act (the `to_server_*` calls)."""

    override_player_input_class = DoomInput

    def post_init(self) -> None:
        self.yaw = -90.0
        self.automated = False
        self.sent_fire = False
        self.sent_run = False

    def begin_play(self) -> None:
        self.show_mouse_cursor = False

    @property
    def doom_state(self) -> DoomPlayerState | None:
        from doom import state

        ps = self.player_state
        return ps if isinstance(ps, state.DoomPlayerState) else None

    # -- the server tells this player's screen ---------------------------------------------------------------

    @ue.ufunction(client=True, reliable=True)
    def owner_notice(self, text: str, seconds: float) -> None:
        mode = mode_now()
        if mode is not None:
            mode.notice, mode.notice_timer = text, seconds

    @ue.ufunction(client=True, reliable=True)
    def owner_console(self, text: str) -> None:
        """The server's answer to a cheat typed on this machine."""
        mode = mode_now()
        if mode is not None:
            mode.console_lines = [*mode.console_lines, text][-12:]
            mode.notice, mode.notice_timer = text, 2.0

    @ue.ufunction(client=True, reliable=False)
    def owner_sound(self, key: str, volume: float) -> None:
        mode = mode_now()
        if mode is not None and getattr(mode, "loaded_map", False):
            mode.play_sound(key, volume)

    @ue.ufunction(client=True, reliable=True)
    def owner_warp(self, x: float, y: float, z: float, yaw: float) -> None:
        """The server moved this player's marine (start, respawn, teleporter): follow with the view."""
        self.yaw = yaw
        self.set_control_rotation(ue.Rotator(0, yaw, 0))
        pawn = self.get_controlled_pawn()
        if isinstance(pawn, DoomMarine) and not self.has_authority():
            pawn.set_actor_location(ue.Vector(x, y, z), False, True)
            pawn.character_movement.stop_movement_immediately()

    # -- this player's requests to the server ----------------------------------------------------------------

    def server_mode(self) -> Any:
        mode = mode_now()
        return mode if mode is not None and hasattr(mode, "resolve") else None

    @ue.ufunction(server=True, reliable=True)
    def to_server_fire(self, held: bool) -> None:
        mode = self.server_mode()
        ps = self.doom_state
        if mode is None or ps is None:
            return
        ps.fire_held = held
        if held:
            mode.fire(ps)

    @ue.ufunction(server=True, reliable=False)
    def to_server_aim(self, x: float, y: float, z: float) -> None:
        ps = self.doom_state
        if ps is not None:
            ps.aim = (x, y, z)

    @ue.ufunction(server=True, reliable=True)
    def to_server_weapon(self, weapon: str) -> None:
        ps = self.doom_state
        if ps is not None and weapon in ps.weapons and not ps.dead:
            ps.weapon = weapon

    @ue.ufunction(server=True, reliable=True)
    def to_server_use(self, yaw: float) -> None:
        mode = self.server_mode()
        if mode is not None:
            mode.use(self.doom_state, yaw)

    @ue.ufunction(server=True, reliable=True)
    def to_server_run(self, run: bool) -> None:
        pawn = self.get_controlled_pawn()
        if isinstance(pawn, DoomMarine):
            pawn.character_movement.max_walk_speed = RUN_SPEED if run else WALK_SPEED
            pawn.character_movement.max_fly_speed = RUN_SPEED if run else WALK_SPEED

    @ue.ufunction(server=True, reliable=True)
    def to_server_cheat(self, text: str) -> None:
        """A cheat typed on a client's console, for that client's marine. Only the host may change the map."""
        mode = self.server_mode()
        ps = self.doom_state
        if mode is None or ps is None:
            return
        reply = console.apply(mode, ps, text.strip().lower()[:40], host=bool(self.is_local_controller()))
        if reply:
            self.owner_console(reply)

    @ue.ufunction(server=True, reliable=True)
    def to_server_advance(self) -> None:
        mode = self.server_mode()
        if mode is not None and mode.won:
            campaign.advance(mode)

    # -- input -----------------------------------------------------------------------------------------------

    def tick(self, delta_seconds: float) -> None:
        mode = mode_now()
        player = self.get_controlled_pawn()
        if (
            mode is None
            or not mode.loaded_map
            or not isinstance(player, DoomMarine)
            or self.automated
            or not self.is_local_controller()
        ):
            return
        ps = self.doom_state
        if ps is None:
            return
        if mode.menu == "console":
            console.input_tick(mode, self)
            return
        if not mode.menu and self.was_input_key_just_pressed(console.CONTROL_KEYS["F1"]):
            mode.menu = "console"
            if not mode.networked:
                player.character_movement.stop_movement_immediately()
            return
        if mode.menu:
            campaign.menu_input(mode, self)
            return
        if self.was_input_key_just_pressed(KEYS["Escape"]):
            campaign.enter_menu(mode)
            return
        if not mode.networked:
            if self.was_input_key_just_pressed(KEYS["F5"]):
                campaign.save_game(mode, 5)
            if self.was_input_key_just_pressed(KEYS["F9"]):
                campaign.load_game(mode, 5)
                return
        if mode.won and self.was_input_key_just_pressed(KEYS["Enter"]):
            if self.has_authority():
                campaign.advance(mode)
            else:
                self.to_server_advance()
            return
        if not mode.networked and self.was_input_key_just_pressed(KEYS["R"]):
            mode.restart()
        if self.was_input_key_just_pressed(KEYS["Tab"]):
            mode.show_map = not mode.show_map
        if ps.dead or mode.won:
            return
        mx, _ = self.get_input_mouse_delta()
        self.yaw += mx * 1.2
        self.set_control_rotation(ue.Rotator(0, self.yaw, 0))
        forward = float(self.is_input_key_down(KEYS["W"])) - float(self.is_input_key_down(KEYS["S"]))
        right = float(self.is_input_key_down(KEYS["D"])) - float(self.is_input_key_down(KEYS["A"]))
        yaw = math.radians(self.yaw)
        run = bool(self.is_input_key_down(KEYS["LeftShift"]))
        player.character_movement.max_walk_speed = RUN_SPEED if run else WALK_SPEED
        player.character_movement.max_fly_speed = RUN_SPEED if run else WALK_SPEED
        if run != self.sent_run and not self.has_authority():
            self.sent_run = run
            self.to_server_run(run)
        player.add_movement_input(ue.Vector(math.cos(yaw), math.sin(yaw), 0), forward)
        player.add_movement_input(ue.Vector(-math.sin(yaw), math.cos(yaw), 0), right)
        current = ps.weapon
        for key, weapon in WEAPON_KEYS:
            if self.was_input_key_just_pressed(KEYS[key]):
                if key == "One" and "chainsaw" in ps.weapons:
                    weapon = "fist" if current == "chainsaw" else "chainsaw"
                if weapon in ps.weapons:
                    current = weapon
        for key, direction in (("MouseScrollUp", 1), ("MouseScrollDown", -1)):
            if self.was_input_key_just_pressed(KEYS[key]):
                owned = [weapon for weapon in WEAPON_CYCLE if weapon in ps.weapons]
                if owned:
                    index = owned.index(current) if current in owned else 0
                    current = owned[(index + direction) % len(owned)]
        if current != ps.weapon:
            if self.has_authority():
                ps.weapon = current
            else:
                self.to_server_weapon(current)
        held = bool(self.is_input_key_down(KEYS["LeftMouseButton"]))
        if self.has_authority():
            ps.fire_held = held
            if held:
                mode.fire(ps)
        else:
            if held != self.sent_fire:
                self.sent_fire = held
                self.to_server_fire(held)
            if held:
                aim = mode.aim_direction(player, current)
                self.to_server_aim(float(aim[0]), float(aim[1]), float(aim[2]))
        if self.was_input_key_just_pressed(KEYS["E"]):
            if self.has_authority():
                mode.use(ps)
            else:
                self.to_server_use(float(self.get_control_rotation()[1]))

from __future__ import annotations

import os
import subprocess
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .base import ExternalAdapterError
from ..runner import EnvironmentStep
from ..verification import ObservationSnapshot


StateExtractor = Callable[[Mapping[str, Any], Mapping[str, Any]], ObservationSnapshot]

CONTROLLED_RESOURCE_BLOCKS = (
    "coal_ore",
    "iron_ore",
    "gold_ore",
    "redstone_ore",
    "lapis_ore",
    "diamond_ore",
    "emerald_ore",
)

# Public local perception for text-capable external policies. These are
# ordinary MineRL grid/ray observations, not evaluator-only coordinates or
# verifier diagnostics. Common wood/material blocks support policies using
# structured local observations; see docs/observation-tracks.md for track rules.
AGENT_VISIBLE_BLOCKS = (
    "oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log",
    "dark_oak_log", "mangrove_log", "oak_leaves", "birch_leaves",
    "spruce_leaves", "jungle_leaves", "acacia_leaves", "dark_oak_leaves",
    "mangrove_leaves", "stone", "dirt", "grass_block", "sand", "gravel",
    "cobblestone", "water", "lava", "crafting_table", "furnace",
)


def default_state_extractor(
    observation: Mapping[str, Any],
    info: Mapping[str, Any],
) -> ObservationSnapshot:
    inventory = observation.get("inventory") or info.get("inventory") or {}
    flags = set(info.get("flags") or ())
    counters = _extract_counters(observation, info)
    player_stats = _extract_player_stats(observation, info)
    equipped = _normalize_equipped(observation.get("equipped") or info.get("equipped") or {})
    equipped_items = observation.get("equipped_items") or info.get("equipped_items") or {}
    if not equipped and equipped_items:
        equipped = {slot: _item_name(item) for slot, item in equipped_items.items()}
    flags.update(_derive_flags(inventory, equipped, player_stats, counters, observation, info))
    return ObservationSnapshot(
        inventory=inventory,
        flags=flags,
        counters=counters,
        player_stats=player_stats,
        equipped=equipped,
        raw_observation=observation,
        info=info,
    )


def _extract_counters(
    observation: Mapping[str, Any],
    info: Mapping[str, Any],
) -> Mapping[str, int]:
    counters = dict(info.get("counters") or {})
    kill_entity = observation.get("kill_entity") or info.get("kill_entity") or {}
    if isinstance(kill_entity, Mapping) and "zombie" in kill_entity:
        counters["zombie_defeated"] = int(kill_entity.get("zombie", 0) or 0)
    mine_block = observation.get("mine_block") or info.get("mine_block") or {}
    if isinstance(mine_block, Mapping) and "coal_ore" in mine_block:
        counters["coal_ore_mined"] = int(mine_block.get("coal_ore", 0) or 0)
    pickup = observation.get("pickup") or info.get("pickup") or {}
    if isinstance(pickup, Mapping) and "coal" in pickup:
        counters["coal_picked_up"] = int(pickup.get("coal", 0) or 0)
    return counters


def _extract_player_stats(
    observation: Mapping[str, Any],
    info: Mapping[str, Any],
) -> Mapping[str, Any]:
    player_stats = dict(info.get("player_stats") or {})
    for payload in (
        observation.get("life_stats"),
        info.get("life_stats"),
        observation.get("location_stats"),
        info.get("location_stats"),
    ):
        if isinstance(payload, Mapping):
            player_stats.update(payload)
    for payload in (observation, info, observation.get("world_stats"), info.get("world_stats")):
        if isinstance(payload, Mapping):
            for key in (
                "world_time",
                "total_time",
                "light_level",
                "effective_light_level",
                "sky_light_level",
                "effective_sky_light_level",
                "block_light_level",
                "skylight_subtracted",
                "sun_brightness",
                "can_see_sky",
                "is_alive",
            ):
                _copy_if_present(payload, player_stats, key)
            _copy_if_present(payload, player_stats, "WorldTime", target_key="world_time")
            _copy_if_present(payload, player_stats, "TotalTime", target_key="total_time")
    return player_stats


def _copy_if_present(source: Mapping[str, Any], target: dict[str, Any], key: str, *, target_key: str | None = None) -> None:
    if key in source:
        target[target_key or key] = source[key]


def _normalize_equipped(equipped: Mapping[str, Any]) -> Mapping[str, str]:
    return {slot: _item_name(item) for slot, item in equipped.items()}


def _item_name(item: Any) -> str:
    if isinstance(item, Mapping):
        item = item.get("type", item)
    normalized = _block_name(item)
    return normalized if normalized is not None else str(item)


def _derive_flags(
    inventory: Mapping[str, Any],
    equipped: Mapping[str, Any],
    player_stats: Mapping[str, Any],
    counters: Mapping[str, Any],
    observation: Mapping[str, Any],
    info: Mapping[str, Any],
) -> set[str]:
    flags = set()

    if inventory.get("coal", 0) >= 1:
        flags.add("coal_source_known")
    if counters.get("coal_ore_mined", 0) >= 1 or counters.get("coal_picked_up", 0) >= 1:
        flags.add("coal_source_known")

    if info.get("night_survived") is True:
        flags.add("night_survived")
    if info.get("coal_source_known") is True:
        flags.add("coal_source_known")
    if info.get("lit_shelter") is True:
        flags.add("lit_shelter")
    if (
        _contains_block(info.get("nearby_blocks"), "coal_ore")
        or _contains_block(info.get("visible_blocks"), "coal_ore")
        or _contains_block(observation.get("nearby_blocks"), "coal_ore")
        or _contains_block(observation.get("visible_blocks"), "coal_ore")
        or _coal_observed(observation.get("line_of_sight"))
        or _coal_observed(observation.get("nearby_blocks"))
    ):
        flags.add("coal_source_known")

    life = player_stats.get("life")
    health = player_stats.get("health")
    if life is not None and life <= 0:
        return flags
    if health is not None and health <= 0:
        return flags
    if info.get("survived_target_interval") is True:
        flags.add("night_survived")
    if _lit_shelter_observed(observation, player_stats):
        flags.add("lit_shelter")

    return flags


def _lit_shelter_observed(
    observation: Mapping[str, Any],
    player_stats: Mapping[str, Any],
) -> bool:
    nearby_blocks = observation.get("nearby_blocks")
    if not isinstance(nearby_blocks, Mapping):
        return False

    torch_count = _numeric(nearby_blocks.get("torch"))
    solid_blocks = _numeric(nearby_blocks.get("solid_blocks"))
    light = _numeric_first(player_stats, ("effective_light_level", "light_level", "LightLevel"))
    sky_light = _numeric_first(player_stats, ("effective_sky_light_level", "sky_light_level", "SkyLightLevel"))
    can_see_sky = player_stats.get("can_see_sky", player_stats.get("CanSeeSky"))

    sheltered = solid_blocks >= 60
    dark_sky = sky_light <= 7 or can_see_sky is False or can_see_sky == 0
    lit = torch_count >= 1 and light >= 7
    return bool(sheltered and dark_sky and lit)


def _coal_observed(payload: Any) -> bool:
    if payload is None:
        return False
    if isinstance(payload, Mapping):
        if _numeric(payload.get("coal_ore")) >= 1:
            return True
        if _block_name(payload.get("type")) == "coal_ore":
            return True
        return any(_coal_observed(value) for value in payload.values())
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        return any(_coal_observed(value) for value in payload)
    return _block_name(payload) == "coal_ore"


def _numeric_first(payload: Mapping[str, Any], keys: Sequence[str]) -> float:
    for key in keys:
        if key in payload:
            return _numeric(payload[key])
    return 0.0


def _numeric(value: Any) -> float:
    if hasattr(value, "item"):
        value = value.item()
    return float(value) if isinstance(value, (int, float)) else 0.0


def _block_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.rsplit(":", 1)[-1]


def _contains_block(payload: Any, block_name: str) -> bool:
    if payload is None:
        return False
    if isinstance(payload, str):
        return _block_name(payload) == block_name
    if isinstance(payload, Mapping):
        return any(_contains_block(value, block_name) for value in payload.values())
    if isinstance(payload, Sequence) and not isinstance(payload, (bytes, bytearray)):
        return any(_contains_block(value, block_name) for value in payload)
    return False


class MineRLEnvironmentAdapter:
    def __init__(
        self,
        env_id: str,
        state_extractor: StateExtractor | None = None,
        video_path: str | Path | None = None,
        video_source: str = "pov",
        video_fps: int = 20,
        video_every_n_steps: int = 1,
        video_scale: int | None = None,
        video_size: str = "1280x1024",
        env_resolution: Sequence[int] | str | None = None,
        max_video_frames: int | None = None,
        seed: int | None = None,
        initial_inventory: Mapping[str, int] | None = None,
        start_time: int | None = None,
        weather: str | None = None,
        allow_time: bool = True,
        allow_spawning: bool = True,
        start_position: Mapping[str, float] | None = None,
        world_decorator: str | None = None,
        known_blocks: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.env_id = env_id
        self.state_extractor = state_extractor or default_state_extractor
        self.video_path = Path(video_path) if video_path is not None else None
        self.video_source = video_source
        self.video_fps = video_fps
        self.video_every_n_steps = video_every_n_steps
        self.video_scale = video_scale
        self.video_size = video_size
        self.env_resolution = self._parse_resolution(env_resolution)
        self.max_video_frames = max_video_frames
        self.seed = seed
        self.initial_inventory = dict(initial_inventory or {})
        self.start_time = start_time
        self.weather = weather
        self.allow_time = allow_time
        self.allow_spawning = allow_spawning
        self.start_position = dict(start_position or {})
        self.world_decorator = world_decorator
        self.known_blocks = tuple(dict(block) for block in (known_blocks or ()))
        self._env = None
        self._snapshot = ObservationSnapshot()
        self._video_process = None
        self._step_count = 0
        self._frames_written = 0

    def reset(self, profile: str) -> ObservationSnapshot:
        try:
            gym = import_module("gym")
            import_module("minerl")
        except ModuleNotFoundError as exc:
            raise ExternalAdapterError(
                "MineRL runtime is unavailable. Install MineRL and Gym before using MineRLEnvironmentAdapter."
            ) from exc

        if self.video_source == "x11":
            self._start_x11_video()
        self._env = self._make_env(gym)
        self._step_count = 0
        self._frames_written = 0
        self._seed_env()
        reset_result = self._env.reset()
        observation = reset_result[0] if isinstance(reset_result, tuple) else reset_result
        try:
            if self.video_source == "pov":
                self._record_frame(observation or {})
        except Exception:
            self.close()
            raise
        self._snapshot = self._with_environment_markers(
            self.state_extractor(observation or {}, {"profile": profile})
        )
        return self._snapshot

    def _seed_env(self) -> None:
        if self.seed is None or self._env is None:
            return
        if hasattr(self._env, "seed"):
            self._env.seed(self.seed)
        action_space = getattr(self._env, "action_space", None)
        observation_space = getattr(self._env, "observation_space", None)
        if hasattr(action_space, "seed"):
            action_space.seed(self.seed)
        if hasattr(observation_space, "seed"):
            observation_space.seed(self.seed)

    def observe(self) -> ObservationSnapshot:
        return self._snapshot

    def _make_env(self, gym: Any) -> Any:
        if self.env_id == "MCBenchHumanSurvival-v0":
            return self._make_mcbench_human_survival()
        if self.env_resolution is None:
            return gym.make(self.env_id)
        if self.env_id != "MineRLTreechop-v0":
            raise ExternalAdapterError(
                f"Custom env_resolution is only wired for MineRLTreechop-v0, not {self.env_id}."
            )
        treechop_specs = import_module("minerl.herobraine.env_specs.treechop_specs")
        return treechop_specs.Treechop(resolution=self.env_resolution).make()

    def _make_mcbench_human_survival(self) -> Any:
        human_survival_specs = import_module("minerl.herobraine.env_specs.human_survival_specs")
        handlers = import_module("minerl.herobraine.hero.handlers")
        translation = import_module("minerl.herobraine.hero.handlers.translation")
        gym_spaces = import_module("gym.spaces")
        numpy = import_module("numpy")

        initial_inventory = [
            {"type": item, "quantity": count}
            for item, count in self.initial_inventory.items()
            if count
        ]
        start_position = dict(self.start_position)
        start_time = self.start_time
        weather = self.weather
        allow_time = self.allow_time
        allow_spawning = self.allow_spawning
        world_decorator = self.world_decorator
        observable_nearby_blocks = tuple(
            dict.fromkeys(
                (*CONTROLLED_RESOURCE_BLOCKS, "torch", *AGENT_VISIBLE_BLOCKS)
                + tuple(
                    block_type
                    for block in self.known_blocks
                    if (block_type := _block_name(block.get("type")))
                )
            )
        )
        class CoalLineOfSightObservation(translation.TranslationHandler):
            def __init__(self) -> None:
                super().__init__(
                    gym_spaces.Dict(
                        {
                            **{
                                block_name: gym_spaces.Box(low=0, high=1, shape=(), dtype=numpy.int32)
                                for block_name in dict.fromkeys(
                                    (*CONTROLLED_RESOURCE_BLOCKS, *AGENT_VISIBLE_BLOCKS)
                                )
                            },
                            "distance": gym_spaces.Box(low=0, high=256, shape=(), dtype=numpy.float32),
                        }
                    )
                )

            def to_string(self) -> str:
                return "line_of_sight"

            def xml_template(self) -> str:
                return "<ObservationFromRay/>"

            def from_hero(self, obs):
                line_of_sight = obs.get("LineOfSight") or {}
                block_type = _block_name(line_of_sight.get("type"))
                return {
                    **{
                        block_name: numpy.int32(1 if block_type == block_name else 0)
                        for block_name in dict.fromkeys(
                            (*CONTROLLED_RESOURCE_BLOCKS, *AGENT_VISIBLE_BLOCKS)
                        )
                    },
                    "distance": numpy.float32(line_of_sight.get("distance", 0) or 0),
                }

            def from_universal(self, obs):
                return self.from_hero(obs)

        class NearbyBlocksObservation(translation.TranslationHandler):
            def __init__(self) -> None:
                super().__init__(
                    gym_spaces.Dict(
                        {
                            **{
                                block_name: gym_spaces.Box(low=0, high=343, shape=(), dtype=numpy.int32)
                                for block_name in observable_nearby_blocks
                            },
                            "solid_blocks": gym_spaces.Box(low=0, high=343, shape=(), dtype=numpy.int32),
                            "air": gym_spaces.Box(low=0, high=343, shape=(), dtype=numpy.int32),
                        }
                    )
                )

            def to_string(self) -> str:
                return "nearby_blocks"

            def xml_template(self) -> str:
                return """
                    <ObservationFromGrid>
                        <Grid name="mcbench_nearby_blocks">
                            <min x="-3" y="-2" z="-3"/>
                            <max x="3" y="2" z="3"/>
                        </Grid>
                    </ObservationFromGrid>
                """

            def from_hero(self, obs):
                blocks = [_block_name(block) for block in (obs.get("mcbench_nearby_blocks") or [])]
                air = sum(1 for block in blocks if block in ("air", None))
                return {
                    **{
                        block_name: numpy.int32(sum(1 for block in blocks if block == block_name))
                        for block_name in observable_nearby_blocks
                    },
                    "solid_blocks": numpy.int32(len(blocks) - air),
                    "air": numpy.int32(air),
                }

            def from_universal(self, obs):
                return self.from_hero(obs)

        class WorldStatsObservation(translation.TranslationHandler):
            def __init__(self) -> None:
                super().__init__(
                    gym_spaces.Dict(
                        {
                            "world_time": gym_spaces.Box(low=0, high=24000, shape=(), dtype=numpy.int64),
                            "total_time": gym_spaces.Box(low=0, high=10**12, shape=(), dtype=numpy.int64),
                            "light_level": gym_spaces.Box(low=0, high=15, shape=(), dtype=numpy.int32),
                            "effective_light_level": gym_spaces.Box(low=0, high=15, shape=(), dtype=numpy.int32),
                            "sky_light_level": gym_spaces.Box(low=0, high=15, shape=(), dtype=numpy.int32),
                            "effective_sky_light_level": gym_spaces.Box(low=0, high=15, shape=(), dtype=numpy.int32),
                            "block_light_level": gym_spaces.Box(low=0, high=15, shape=(), dtype=numpy.int32),
                            "skylight_subtracted": gym_spaces.Box(low=0, high=15, shape=(), dtype=numpy.int32),
                            "sun_brightness": gym_spaces.Box(low=0, high=1, shape=(), dtype=numpy.float32),
                            "can_see_sky": gym_spaces.Box(low=0, high=1, shape=(), dtype=numpy.int32),
                            "is_alive": gym_spaces.Box(low=0, high=1, shape=(), dtype=numpy.int32),
                        }
                    )
                )

            def to_string(self) -> str:
                return "world_stats"

            def xml_template(self) -> str:
                return "<ObservationFromFullStats/>"

            def from_hero(self, obs):
                return {
                    "world_time": numpy.int64(obs.get("world_time", obs.get("WorldTime", 0)) or 0),
                    "total_time": numpy.int64(obs.get("total_time", obs.get("TotalTime", 0)) or 0),
                    "light_level": numpy.int32(obs.get("light_level", 0) or 0),
                    "effective_light_level": numpy.int32(obs.get("effective_light_level", 0) or 0),
                    "sky_light_level": numpy.int32(obs.get("sky_light_level", 0) or 0),
                    "effective_sky_light_level": numpy.int32(obs.get("effective_sky_light_level", 0) or 0),
                    "block_light_level": numpy.int32(obs.get("block_light_level", 0) or 0),
                    "skylight_subtracted": numpy.int32(obs.get("skylight_subtracted", 0) or 0),
                    "sun_brightness": numpy.float32(obs.get("sun_brightness", 0) or 0),
                    "can_see_sky": numpy.int32(1 if obs.get("can_see_sky") else 0),
                    "is_alive": numpy.int32(1 if obs.get("is_alive", True) else 0),
                }

            def from_universal(self, obs):
                return self.from_hero(obs)

        class RawDrawingDecorator(handlers.DrawingDecorator):
            def xml_template(self) -> str:
                return "<DrawingDecorator>{{to_draw | safe}}</DrawingDecorator>"

        class MCBenchHumanSurvival(human_survival_specs.HumanSurvival):
            def __init__(self) -> None:
                super().__init__(name="MCBenchHumanSurvival-v0")

            def create_observables(self):
                return super().create_observables() + [
                    CoalLineOfSightObservation(),
                    NearbyBlocksObservation(),
                    WorldStatsObservation(),
                ]

            def create_agent_start(self):
                starts = super().create_agent_start()
                if initial_inventory:
                    starts.append(handlers.SimpleInventoryAgentStart(initial_inventory))
                if start_position:
                    starts.append(
                        handlers.AgentStartPlacement(
                            start_position.get("x", 0),
                            start_position.get("y", 64),
                            start_position.get("z", 0),
                            start_position.get("yaw", 0),
                            start_position.get("pitch", 0),
                        )
                    )
                return starts

            def create_server_initial_conditions(self):
                conditions = [
                    handlers.TimeInitialCondition(
                        allow_passage_of_time=allow_time,
                        start_time=start_time,
                    ),
                    handlers.SpawningInitialCondition(allow_spawning=allow_spawning),
                ]
                if weather:
                    conditions.append(handlers.WeatherInitialCondition(weather))
                return conditions

            def create_server_decorators(self):
                decorators = super().create_server_decorators()
                if world_decorator:
                    decorators.append(RawDrawingDecorator(world_decorator))
                return decorators

        return MCBenchHumanSurvival().make()

    def step(self, action: Mapping[str, Any]) -> EnvironmentStep:
        if self._env is None:
            raise ExternalAdapterError("MineRL environment has not been reset.")
        materialized_action = dict(action)
        if materialized_action == {"__adapter_action__": "noop"}:
            materialized_action = self._noop_action()
        else:
            full_action = self._noop_action()
            action_template = dict(full_action)
            full_action.update(materialized_action)
            materialized_action = self._coerce_action_components(full_action, action_template)
        result = self._env.step(materialized_action)
        if len(result) == 5:
            observation, _reward, terminated, truncated, info = result
            done = bool(terminated or truncated)
        else:
            observation, _reward, done, info = result
        self._step_count += 1
        if self.video_source == "pov":
            self._record_frame(observation or {})
        self._snapshot = self._with_environment_markers(self.state_extractor(observation or {}, info or {}))
        return EnvironmentStep(snapshot=self._snapshot, done=bool(done), info=info or {})

    def _noop_action(self) -> dict[str, Any]:
        if self._env is None or not hasattr(self._env.action_space, "noop"):
            raise ExternalAdapterError("MineRL action space does not expose noop().")
        return dict(self._env.action_space.noop())

    @staticmethod
    def _coerce_action_components(
        action: Mapping[str, Any],
        action_template: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Preserve MineRL action-space shapes when a policy emits JSON scalars.

        Learned VPT-family policies already return the native NumPy values, but
        diagnostic and external policies commonly express binary controls as
        ordinary Python integers.  MCP-Reborn expects the action-space's
        original scalar/array shape, so normalize each supplied value against
        the corresponding noop component before stepping the environment.
        """
        try:
            numpy = import_module("numpy")
        except ModuleNotFoundError:
            return dict(action)

        normalized: dict[str, Any] = {}
        for key, value in action.items():
            template = action_template.get(key)
            if not hasattr(template, "shape") or not hasattr(template, "dtype"):
                normalized[key] = value
                continue
            try:
                component = numpy.asarray(value, dtype=template.dtype)
                if tuple(template.shape):
                    component = component.reshape(template.shape)
                elif component.shape:
                    component = component.reshape(())
                normalized[key] = component
            except (TypeError, ValueError):
                normalized[key] = value
        return normalized

    def _with_environment_markers(self, snapshot: ObservationSnapshot) -> ObservationSnapshot:
        return self._with_known_block_markers(snapshot)

    def _with_known_block_markers(self, snapshot: ObservationSnapshot) -> ObservationSnapshot:
        if not self.known_blocks:
            return snapshot
        xpos = _numeric(snapshot.player_stats.get("xpos"))
        ypos = _numeric(snapshot.player_stats.get("ypos"))
        zpos = _numeric(snapshot.player_stats.get("zpos"))
        markers = []
        for block in self.known_blocks:
            block_type = _block_name(block.get("type"))
            bx = _numeric(block.get("x"))
            by = _numeric(block.get("y"))
            bz = _numeric(block.get("z"))
            dx = bx + 0.5 - xpos
            dy = by + 0.5 - ypos
            dz = bz + 0.5 - zpos
            horizontal_distance = (dx * dx + dz * dz) ** 0.5
            distance = (dx * dx + dy * dy + dz * dz) ** 0.5
            nearby = horizontal_distance <= _numeric(block.get("horizontal_radius", 6)) and abs(dy) <= _numeric(
                block.get("vertical_radius", 4)
            )
            marker = {
                "type": block_type,
                "x": bx,
                "y": by,
                "z": bz,
                "distance": distance,
                "horizontal_distance": horizontal_distance,
                "vertical_distance": dy,
                "nearby": nearby,
            }
            markers.append(marker)
        raw_observation = dict(snapshot.raw_observation)
        raw_observation["known_blocks"] = markers
        return ObservationSnapshot(
            inventory=snapshot.inventory,
            flags=snapshot.flags,
            player_stats=snapshot.player_stats,
            counters=snapshot.counters,
            equipped=snapshot.equipped,
            raw_observation=raw_observation,
            info=snapshot.info,
        )

    def close(self) -> None:
        video_error = None
        try:
            if self._video_process is not None:
                process = self._video_process
                self._video_process = None
                if process.stdin is not None:
                    process.stdin.close()
                    return_code = process.wait()
                else:
                    process.terminate()
                    try:
                        return_code = process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        return_code = process.wait()
                if return_code != 0 and not (self.video_source == "x11" and return_code == 255):
                    video_error = ExternalAdapterError(f"ffmpeg exited with status {return_code}.")
        finally:
            if self._env is not None:
                self._env.close()
                self._env = None
        if video_error is not None:
            raise video_error

    def _start_x11_video(self) -> None:
        if self.video_path is None or self._video_process is not None:
            return
        display = os.environ.get("DISPLAY")
        if not display:
            raise ExternalAdapterError("X11 video recording requires DISPLAY to be set.")
        x11_input = display if "." in display.rsplit(":", 1)[-1] else f"{display}.0"
        self.video_path.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "x11grab",
            "-video_size",
            self.video_size,
            "-framerate",
            str(self.video_fps),
            "-i",
            x11_input,
            "-an",
            "-vcodec",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            str(self.video_path),
        ]
        try:
            self._video_process = subprocess.Popen(
                command,
                stdin=None,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ExternalAdapterError(
                "X11 video recording requires ffmpeg. Install ffmpeg or remove environment.video_path."
            ) from exc

    @staticmethod
    def _parse_resolution(resolution: Sequence[int] | str | None) -> tuple[int, int] | None:
        if resolution is None:
            return None
        if isinstance(resolution, str):
            separator = "x" if "x" in resolution else ","
            parts = [part.strip() for part in resolution.split(separator)]
        else:
            parts = list(resolution)
        if len(parts) != 2:
            raise ExternalAdapterError("env_resolution must contain width and height.")
        width, height = (int(parts[0]), int(parts[1]))
        if width <= 0 or height <= 0:
            raise ExternalAdapterError("env_resolution width and height must be positive.")
        return width, height

    def _record_frame(self, observation: Mapping[str, Any]) -> None:
        if self.video_path is None:
            return
        if self.video_source != "pov":
            return
        if self.max_video_frames is not None and self._frames_written >= self.max_video_frames:
            return
        if self._step_count % max(self.video_every_n_steps, 1) != 0:
            return
        frame = observation.get("pov")
        if frame is None:
            return
        if self._video_process is None:
            shape = getattr(frame, "shape", None)
            if shape is None or len(shape) != 3 or shape[2] != 3:
                raise ExternalAdapterError("Video recording requires RGB frames shaped as (height, width, 3).")
            height, width, _channels = shape
            self.video_path.parent.mkdir(parents=True, exist_ok=True)
            command = [
                "ffmpeg",
                "-y",
                "-f",
                "rawvideo",
                "-vcodec",
                "rawvideo",
                "-s",
                f"{width}x{height}",
                "-pix_fmt",
                "rgb24",
                "-r",
                str(self.video_fps),
                "-i",
                "-",
                "-an",
            ]
            if self.video_scale is not None:
                command.extend(["-vf", f"scale={self.video_scale}:{self.video_scale}:flags=neighbor"])
            command.extend([
                "-vcodec",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(self.video_path),
            ])
            try:
                self._video_process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError as exc:
                raise ExternalAdapterError(
                    "Video recording requires ffmpeg. Install ffmpeg or remove environment.video_path."
                ) from exc
        if self._video_process.stdin is None:
            raise ExternalAdapterError("ffmpeg stdin is unavailable.")
        self._video_process.stdin.write(frame.tobytes())
        self._frames_written += 1

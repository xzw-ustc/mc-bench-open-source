import pytest


import pickle


import sys


from types import SimpleNamespace


from mcbench.adapters.base import ExternalAdapterError


from mcbench.adapters.external import ExternalPolicyAgentAdapter


from mcbench.adapters.minerl import MineRLEnvironmentAdapter, default_state_extractor


from mcbench.adapters.scripted import ScriptedAgentAdapter, ScriptedEnvironmentAdapter


from mcbench.runner import EnvironmentStep


from mcbench.verification import ObservationSnapshot


def test_scripted_adapters_round_trip_snapshots_and_actions():
    environment = ScriptedEnvironmentAdapter(
        snapshots=[
            ObservationSnapshot(),
            ObservationSnapshot(inventory={"oak_log": 1}),
        ]
    )
    agent = ScriptedAgentAdapter(action={"noop": 1})

    first = environment.reset("forest_day")
    action = agent.act(first, "Collect a log.", stage_context=None)
    step = environment.step(action)

    assert action == {"noop": 1}
    assert isinstance(step, EnvironmentStep)
    assert step.snapshot.inventory["oak_log"] == 1


def test_minerl_adapter_reports_missing_runtime(monkeypatch):
    def _missing(_name):
        raise ModuleNotFoundError("missing")

    monkeypatch.setattr("mcbench.adapters.minerl.import_module", _missing)
    adapter = MineRLEnvironmentAdapter(env_id="MineRLTreechop-v0")

    with pytest.raises(ExternalAdapterError, match="MineRL"):
        adapter.reset("forest_day")


def test_default_state_extractor_normalizes_common_minerl_payloads():
    frame = object()
    snapshot = default_state_extractor(
        observation={
            "inventory": {"torch": 2},
            "equipped_items": {"mainhand": {"type": "stone_sword"}},
            "life_stats": {"life": 18},
            "pov": frame,
        },
        info={
            "flags": ["lit_shelter"],
            "counters": {"zombie_defeated": 1},
        },
    )

    assert snapshot.inventory["torch"] == 2
    assert "lit_shelter" in snapshot.flags
    assert snapshot.counters["zombie_defeated"] == 1
    assert snapshot.player_stats["life"] == 18
    assert snapshot.equipped["mainhand"] == "stone_sword"
    assert snapshot.raw_observation["pov"] is frame


def test_default_state_extractor_derives_environment_instrumentation_flags():
    snapshot = default_state_extractor(
        observation={
            "inventory": {},
            "line_of_sight": {"coal_ore": 1, "distance": 2.0},
            "nearby_blocks": {"torch": 1, "solid_blocks": 80, "air": 263},
            "location_stats": {
                "light_level": 9,
                "sky_light_level": 0,
                "can_see_sky": 0,
            },
            "world_stats": {"world_time": 14000, "total_time": 24},
        },
        info={},
    )

    assert "coal_source_known" in snapshot.flags
    assert "lit_shelter" in snapshot.flags
    assert snapshot.player_stats["world_time"] == 14000
    assert snapshot.player_stats["total_time"] == 24


def test_default_state_extractor_accepts_namespaced_block_names():
    snapshot = default_state_extractor(
        observation={
            "line_of_sight": {"type": "minecraft:coal_ore", "distance": 3.0},
            "nearby_blocks": {"coal_ore": 0},
        },
        info={},
    )

    assert "coal_source_known" in snapshot.flags


def test_minerl_adapter_adds_known_block_markers_without_inventory_gifts():
    adapter = MineRLEnvironmentAdapter(
        env_id="MineRLTreechop-v0",
        known_blocks=[{"type": "minecraft:coal_ore", "x": 10, "y": 65, "z": 12}],
    )
    snapshot = ObservationSnapshot(
        inventory={},
        player_stats={"xpos": 10.5, "ypos": 65.0, "zpos": 11.0},
        raw_observation={"inventory": {}},
    )

    augmented = adapter._with_known_block_markers(snapshot)

    assert augmented.inventory == {}
    assert "coal_source_known" not in augmented.flags
    assert augmented.raw_observation["known_blocks"][0]["type"] == "coal_ore"
    assert augmented.raw_observation["known_blocks"][0]["nearby"] is True


def test_minerl_adapter_translates_internal_noop_action(monkeypatch):
    created = {}

    class FakeActionSpace:
        def seed(self, seed):
            created["action_seed"] = seed

        def noop(self):
            return {"camera": [0, 0], "attack": 0}

    class FakeObservationSpace:
        def seed(self, seed):
            created["observation_seed"] = seed

    class FakeEnv:
        action_space = FakeActionSpace()
        observation_space = FakeObservationSpace()

        def seed(self, seed):
            created["seed"] = seed

        def reset(self):
            return {"inventory": {}}

        def step(self, action):
            created["action"] = action
            return {"inventory": {}}, 0.0, False, {}

        def close(self):
            return None

    class FakeGym:
        @staticmethod
        def make(env_id):
            created["env_id"] = env_id
            return FakeEnv()

    def _fake_import(name):
        if name == "gym":
            return FakeGym()
        if name == "minerl":
            return object()
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("mcbench.adapters.minerl.import_module", _fake_import)
    adapter = MineRLEnvironmentAdapter(env_id="MineRLTreechop-v0", seed=123)
    adapter.reset("forest_day")
    adapter.step({"__adapter_action__": "noop"})

    assert created["env_id"] == "MineRLTreechop-v0"
    assert created["seed"] == 123
    assert created["action_seed"] == 123
    assert created["observation_seed"] == 123
    assert created["action"] == {"camera": [0, 0], "attack": 0}


def test_minerl_adapter_coerces_scalar_external_actions_to_native_shapes(monkeypatch):
    numpy = pytest.importorskip("numpy")
    created = {}

    class FakeActionSpace:
        def noop(self):
            return {
                "camera": numpy.zeros((2,), dtype=numpy.float32),
                "attack": numpy.zeros((1,), dtype=numpy.int8),
            }

    class FakeEnv:
        action_space = FakeActionSpace()

        def step(self, action):
            created["action"] = action
            return {"inventory": {}}, 0.0, False, {}

    adapter = MineRLEnvironmentAdapter(env_id="MineRLTreechop-v0")
    adapter._env = FakeEnv()
    adapter.step({"attack": 1, "camera": [2, -3]})

    assert created["action"]["attack"].dtype == numpy.int8
    assert created["action"]["attack"].shape == (1,)
    assert created["action"]["attack"].tolist() == [1]
    assert created["action"]["camera"].dtype == numpy.float32
    assert created["action"]["camera"].shape == (2,)
    assert created["action"]["camera"].tolist() == [2.0, -3.0]


def test_external_policy_adapter_loads_entrypoint_and_returns_action(monkeypatch):
    created = {}

    class FakePolicy:
        def reset(self):
            created["reset"] = True

        def act(self, raw_observation, prompt, **kwargs):
            created["raw_observation"] = raw_observation
            created["prompt"] = prompt
            created["stage_context"] = kwargs["stage_context"]
            return {"forward": 1}

    def create_policy(device, chain_context, checkpoint_path, agent_label):
        created["device"] = device
        created["chain_context"] = chain_context
        created["checkpoint_path"] = checkpoint_path
        created["agent_label"] = agent_label
        return FakePolicy()

    fake_module = SimpleNamespace(create_policy=create_policy)
    monkeypatch.setitem(sys.modules, "fake_external_runtime", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "fake_external_bridge", fake_module)

    stage = SimpleNamespace(
        task=SimpleNamespace(id="collect_coal", name="Collect Coal", domain="survival")
    )
    snapshot = ObservationSnapshot(raw_observation={"pov": "frame"})
    adapter = ExternalPolicyAgentAdapter(
        agent_label="JARVIS-1",
        runtime_module="fake_external_runtime",
        policy_entrypoint="fake_external_bridge:create_policy",
        device="cpu",
        prompt_template="[MC-EvoBench:{task_id}] {instruction}",
        policy_kwargs={"checkpoint_path": "weights/custom_policy"},
    )

    adapter.reset(chain_context="chain")
    action = adapter.act(snapshot, "Collect one coal.", stage)

    assert action == {"forward": 1}
    assert created["device"] == "cpu"
    assert created["chain_context"] == "chain"
    assert created["checkpoint_path"] == "weights/custom_policy"
    assert created["agent_label"] == "JARVIS-1"
    assert created["reset"] is True
    assert created["raw_observation"] == {"pov": "frame"}
    assert created["prompt"] == "[MC-EvoBench:collect_coal] Collect one coal."
    assert created["stage_context"] is stage


def test_external_policy_adapter_forwards_standard_stage_feedback(monkeypatch):
    received = {}

    class FakePolicy:
        def act(self, raw_observation, prompt, **_kwargs):
            return {"forward": 1}

        def on_stage_end(self, **kwargs):
            received.update(kwargs)

    fake_module = SimpleNamespace(create_policy=lambda **_kwargs: FakePolicy())
    monkeypatch.setitem(sys.modules, "fake_feedback_bridge", fake_module)
    stage = SimpleNamespace(task=SimpleNamespace(instruction="Collect one coal."))
    report = SimpleNamespace(status="passed", steps=42, diagnostics={"hidden": "not forwarded"})
    adapter = ExternalPolicyAgentAdapter(policy_entrypoint="fake_feedback_bridge:create_policy")

    adapter.reset(chain_context="chain")
    adapter.on_stage_end(stage, report)

    assert received == {"instruction": "Collect one coal.", "status": "passed", "steps": 42}


def test_external_policy_adapter_does_not_mask_internal_type_errors(monkeypatch):
    class FakePolicy:
        def act(self, raw_observation, prompt, **_kwargs):
            raise TypeError("Object of type ndarray is not JSON serializable")

    fake_module = SimpleNamespace(create_policy=lambda **_kwargs: FakePolicy())
    monkeypatch.setitem(sys.modules, "fake_type_error_bridge", fake_module)
    adapter = ExternalPolicyAgentAdapter(policy_entrypoint="fake_type_error_bridge:create_policy")
    adapter.reset(chain_context="chain")

    with pytest.raises(TypeError, match="ndarray"):
        adapter.act(ObservationSnapshot(raw_observation={"pov": "frame"}), "Collect coal.", stage_context=None)


def test_external_policy_adapter_reports_missing_runtime(monkeypatch):
    def _missing(_name):
        raise ModuleNotFoundError("missing")

    monkeypatch.setattr("mcbench.adapters.external.import_module", _missing)
    adapter = ExternalPolicyAgentAdapter(
        agent_label="JARVIS-1",
        runtime_module="custom_runtime",
        policy_entrypoint="fake_bridge:create_policy",
    )

    with pytest.raises(ExternalAdapterError, match="JARVIS-1"):
        adapter.reset(chain_context=None)


def test_minerl_adapter_records_pov_video_frames(tmp_path, monkeypatch):
    created = {}

    class FakeFrame:
        shape = (2, 3, 3)

        def __init__(self, payload):
            self.payload = payload

        def tobytes(self):
            return self.payload

    class FakeStdin:
        def __init__(self):
            self.payloads = []
            self.closed = False

        def write(self, payload):
            self.payloads.append(payload)

        def close(self):
            self.closed = True

    class FakeProcess:
        def __init__(self):
            self.stdin = FakeStdin()
            self.waited = False

        def wait(self):
            self.waited = True
            return 0

    process = FakeProcess()

    class FakeActionSpace:
        def noop(self):
            return {"attack": 0}

    class FakeEnv:
        action_space = FakeActionSpace()

        def reset(self):
            return {"inventory": {}, "pov": FakeFrame(b"reset-frame")}

        def step(self, action):
            return {"inventory": {}, "pov": FakeFrame(b"step-frame")}, 0.0, False, {}

        def close(self):
            created["env_closed"] = True

    class FakeGym:
        @staticmethod
        def make(env_id):
            return FakeEnv()

    def _fake_import(name):
        if name == "gym":
            return FakeGym()
        if name == "minerl":
            return object()
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("mcbench.adapters.minerl.import_module", _fake_import)
    monkeypatch.setattr(
        "mcbench.adapters.minerl.subprocess.Popen",
        lambda command, **kwargs: created.setdefault("command", command) and process,
    )
    video_path = tmp_path / "videos" / "run.mp4"
    adapter = MineRLEnvironmentAdapter(
        env_id="MineRLTreechop-v0",
        video_path=video_path,
        video_fps=12,
        video_scale=512,
    )

    adapter.reset("forest_day")
    adapter.step({"__adapter_action__": "noop"})
    adapter.close()

    assert created["command"][-1] == str(video_path)
    assert created["command"][created["command"].index("-r") + 1] == "12"
    assert created["command"][created["command"].index("-vf") + 1] == "scale=512:512:flags=neighbor"
    assert process.stdin.payloads == [b"reset-frame", b"step-frame"]
    assert process.stdin.closed is True
    assert process.waited is True
    assert created["env_closed"] is True


def test_minerl_adapter_records_x11_video(tmp_path, monkeypatch):
    created = {}

    class FakeProcess:
        stdin = None

        def __init__(self):
            self.terminated = False
            self.waited = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            self.waited = True
            created["wait_timeout"] = timeout
            return 255

    process = FakeProcess()

    class FakeActionSpace:
        def noop(self):
            return {"attack": 0}

    class FakeEnv:
        action_space = FakeActionSpace()

        def reset(self):
            return {"inventory": {}, "pov": object()}

        def step(self, action):
            return {"inventory": {}, "pov": object()}, 0.0, False, {}

        def close(self):
            created["env_closed"] = True

    class FakeGym:
        @staticmethod
        def make(env_id):
            return FakeEnv()

    def _fake_import(name):
        if name == "gym":
            return FakeGym()
        if name == "minerl":
            return object()
        raise ModuleNotFoundError(name)

    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr("mcbench.adapters.minerl.import_module", _fake_import)
    monkeypatch.setattr(
        "mcbench.adapters.minerl.subprocess.Popen",
        lambda command, **kwargs: created.setdefault("command", command) and process,
    )

    video_path = tmp_path / "videos" / "window.mp4"
    adapter = MineRLEnvironmentAdapter(
        env_id="MineRLTreechop-v0",
        video_path=video_path,
        video_source="x11",
        video_fps=15,
        video_size="1280x1024",
    )

    adapter.reset("forest_day")
    adapter.step({"__adapter_action__": "noop"})
    adapter.close()

    command = created["command"]
    assert command[command.index("-f") + 1] == "x11grab"
    assert command[command.index("-video_size") + 1] == "1280x1024"
    assert command[command.index("-framerate") + 1] == "15"
    assert command[command.index("-i") + 1] == ":99.0"
    assert command[-1] == str(video_path)
    assert process.terminated is True
    assert process.waited is True
    assert created["wait_timeout"] == 10
    assert created["env_closed"] is True


def test_minerl_adapter_can_request_treechop_resolution(monkeypatch):
    created = {}

    class FakeActionSpace:
        def noop(self):
            return {"attack": 0}

    class FakeEnv:
        action_space = FakeActionSpace()

        def reset(self):
            return {"inventory": {}}

        def close(self):
            return None

    class FakeTreechop:
        def __init__(self, resolution):
            created["resolution"] = resolution

        def make(self):
            created["made_custom_env"] = True
            return FakeEnv()

    class FakeGym:
        @staticmethod
        def make(env_id):
            created["gym_make"] = env_id
            return FakeEnv()

    def _fake_import(name):
        if name == "gym":
            return FakeGym()
        if name == "minerl":
            return object()
        if name == "minerl.herobraine.env_specs.treechop_specs":
            return SimpleNamespace(Treechop=FakeTreechop)
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("mcbench.adapters.minerl.import_module", _fake_import)
    adapter = MineRLEnvironmentAdapter(
        env_id="MineRLTreechop-v0",
        env_resolution=[640, 360],
    )

    adapter.reset("forest_day")
    adapter.close()

    assert created["resolution"] == (640, 360)
    assert created["made_custom_env"] is True
    assert "gym_make" not in created


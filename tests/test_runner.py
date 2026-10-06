import pytest

from mcbench.catalog import BenchmarkCatalog
from mcbench.chains import compile_chain
from mcbench.runner import EnvironmentStep, _task_stage_diagnostics, run_compiled_chain
from mcbench.schema import ChainSpec, EdgeSpec, MissionEventSpec, StateSpec, TaskSpec
from mcbench.verification import ObservationSnapshot


class ScriptedEnvironment:
    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.index = 0
        self.reset_profiles = []

    def reset(self, profile):
        self.reset_profiles.append(profile)
        self.index = 0
        return self.snapshots[0]

    def observe(self):
        return self.snapshots[self.index]

    def step(self, action):
        self.index = min(self.index + 1, len(self.snapshots) - 1)
        return EnvironmentStep(snapshot=self.snapshots[self.index], done=False, info={"action": action})

    def close(self):
        return None


class ScriptedAgent:
    def __init__(self):
        self.instructions = []

    def reset(self, chain_context):
        return None

    def act(self, observation, instruction, stage_context):
        self.instructions.append(instruction)
        return {"noop": 1, "stage": stage_context.task.id}


class FeedbackAgent(ScriptedAgent):
    def __init__(self):
        super().__init__()
        self.feedback = []

    def on_stage_end(self, stage, report):
        self.feedback.append((stage.task.instruction, report.status, report.steps))


def _catalog():
    states = {
        "environment:spawned_world": StateSpec(
            id="environment:spawned_world",
            kind="environment",
            description="Spawned.",
        ),
        "item:oak_log": StateSpec(
            id="item:oak_log",
            kind="item",
            description="Log.",
        ),
        "item:oak_planks": StateSpec(
            id="item:oak_planks",
            kind="item",
            description="Planks.",
        ),
    }
    tasks = {
        "collect_log": TaskSpec(
            id="collect_log",
            name="Collect Log",
            domain="survival",
            instruction="Collect one log.",
            max_steps=2,
            environment_profile="forest_day",
            success={"all": [{"predicate": "inventory_at_least", "item": "oak_log", "count": 1}]},
            observation_sources=(
                {
                    "path": "inventory.oak_log",
                    "kind": "primary",
                    "meaning": "MineRL inventory contains an oak log.",
                    "track": "native_perception",
                    "agent_access": "agent_visible",
                },
            ),
        ),
        "craft_planks": TaskSpec(
            id="craft_planks",
            name="Craft Planks",
            domain="building",
            instruction="Craft planks.",
            max_steps=2,
            environment_profile="forest_day",
            success={"all": [{"predicate": "inventory_at_least", "item": "oak_planks", "count": 4}]},
        ),
    }
    edges = (
        EdgeSpec("environment:spawned_world", "requires", "collect_log"),
        EdgeSpec("collect_log", "produces", "item:oak_log"),
        EdgeSpec("item:oak_log", "requires", "craft_planks"),
        EdgeSpec("craft_planks", "produces", "item:oak_planks"),
    )
    chains = {
        "test_chain": ChainSpec(
            id="test_chain",
            name="Test Chain",
            kind="vertical",
            task_ids=("collect_log", "craft_planks"),
            initial_states=("environment:spawned_world",),
            domains=("survival", "building"),
            difficulty="simple",
            environment_profile="forest_day",
        )
    }
    mission_events = {
        "event:collect_log_inventory": MissionEventSpec(
            id="event:collect_log_inventory",
            task_id="collect_log",
            produced_state="item:oak_log",
            kind="inventory_event",
            trigger={"path": "inventory.oak_log", "operator": ">=", "value": 1},
            implementation_status="implemented",
        )
    }
    return BenchmarkCatalog(
        states=states,
        tasks=tasks,
        edges=edges,
        chains=chains,
        mission_events=mission_events,
    )


def test_run_compiled_chain_completes_stages_and_builds_report():
    compiled = compile_chain(_catalog(), "test_chain")
    environment = ScriptedEnvironment(
        snapshots=[
            ObservationSnapshot(),
            ObservationSnapshot(inventory={"oak_log": 1}),
            ObservationSnapshot(inventory={"oak_log": 1, "oak_planks": 4}),
        ]
    )
    agent = ScriptedAgent()

    report = run_compiled_chain(compiled, environment, agent)

    assert report.completed is True
    assert [stage.status for stage in report.stages] == ["passed", "passed"]
    assert [stage.steps for stage in report.stages] == [1, 1]
    assert environment.reset_profiles == ["forest_day"]
    assert agent.instructions == ["Collect one log.", "Craft planks."]
    assert report.stages[0].diagnostics["observation_evidence"][0]["observed"] is True
    assert report.stages[0].diagnostics["observation_evidence"][0]["actual"] == 1
    assert report.stages[0].diagnostics["mission_events"][0]["id"] == "event:collect_log_inventory"


def test_run_compiled_chain_can_stop_at_an_exact_interaction_budget():
    compiled = compile_chain(_catalog(), "test_chain")
    environment = ScriptedEnvironment(snapshots=[ObservationSnapshot(), ObservationSnapshot()])

    report = run_compiled_chain(compiled, environment, ScriptedAgent(), max_total_steps=1)

    assert report.completed is False
    assert [(stage.status, stage.steps) for stage in report.stages] == [("budget_exhausted", 1)]
    assert report.metadata["interaction_budget_steps"] == 1
    assert report.metadata["interaction_steps"] == 1
    assert report.metadata["interaction_budget_exhausted"] is True


def test_optional_transition_capture_includes_final_after_state_and_copies_before():
    class Recorder(ScriptedAgent):
        transition_recording_enabled = True
        def __init__(self):
            super().__init__()
            self.transitions = []
        def on_transition(self, **kwargs):
            self.transitions.append(kwargs)

    raw = {"inventory": {}, "hidden_resource_coordinates": [123, 456]}
    class MutableEnvironment(ScriptedEnvironment):
        def step(self, action):
            raw["inventory"]["oak_log"] = 1
            return EnvironmentStep(ObservationSnapshot(inventory={"oak_log": 1}, raw_observation=raw))

    agent = Recorder()
    environment = MutableEnvironment([ObservationSnapshot(raw_observation=raw)])
    run_compiled_chain(compile_chain(_catalog(), "test_chain"), environment, agent, max_total_steps=1)
    assert len(agent.transitions) == 1
    event = agent.transitions[0]
    assert event["before"] == {"inventory": {}}
    assert event["after"]["inventory"] == {"oak_log": 1}
    assert "hidden_resource_coordinates" not in event["after"]
    assert "success" not in event
    assert event["stage_step"] == 0


def test_run_compiled_chain_delivers_only_terminal_episode_feedback():
    compiled = compile_chain(_catalog(), "test_chain")
    environment = ScriptedEnvironment(
        snapshots=[
            ObservationSnapshot(),
            ObservationSnapshot(inventory={"oak_log": 1}),
            ObservationSnapshot(inventory={"oak_log": 1, "oak_planks": 4}),
        ]
    )
    agent = FeedbackAgent()

    run_compiled_chain(compiled, environment, agent)

    assert agent.feedback == [
        ("Collect one log.", "passed", 1),
        ("Craft planks.", "passed", 1),
    ]


def test_run_compiled_chain_can_reset_on_stage_profile_changes():
    base = _catalog()
    craft_task = base.tasks["craft_planks"]
    catalog = BenchmarkCatalog(
        states=base.states,
        tasks={
            **base.tasks,
            "craft_planks": TaskSpec(
                id=craft_task.id,
                name=craft_task.name,
                domain=craft_task.domain,
                instruction=craft_task.instruction,
                max_steps=craft_task.max_steps,
                environment_profile="forest_dusk",
                success=craft_task.success,
                observation_sources=craft_task.observation_sources,
            ),
        },
        edges=base.edges,
        chains=base.chains,
        mission_events=base.mission_events,
    )
    compiled = compile_chain(catalog, "test_chain")
    environment = ScriptedEnvironment(
        snapshots=[
            ObservationSnapshot(),
            ObservationSnapshot(inventory={"oak_log": 1, "oak_planks": 4}),
        ]
    )

    report = run_compiled_chain(compiled, environment, ScriptedAgent(), per_stage_profiles=True)

    assert report.completed is True
    assert environment.reset_profiles == ["forest_day", "forest_dusk"]


def test_run_compiled_chain_can_keep_chain_profile_for_all_stages():
    base = _catalog()
    craft_task = base.tasks["craft_planks"]
    chain = base.chains["test_chain"]
    catalog = BenchmarkCatalog(
        states=base.states,
        tasks={
            **base.tasks,
            "craft_planks": TaskSpec(
                id=craft_task.id,
                name=craft_task.name,
                domain=craft_task.domain,
                instruction=craft_task.instruction,
                max_steps=craft_task.max_steps,
                environment_profile="forest_dusk",
                success=craft_task.success,
                observation_sources=craft_task.observation_sources,
            ),
        },
        edges=base.edges,
        chains={
            "test_chain": ChainSpec(
                id=chain.id,
                name=chain.name,
                kind=chain.kind,
                task_ids=chain.task_ids,
                initial_states=chain.initial_states,
                domains=chain.domains,
                difficulty=chain.difficulty,
                environment_profile="fixed_ore_progression_shaft",
                profile_policy="chain",
            )
        },
        mission_events=base.mission_events,
    )
    compiled = compile_chain(catalog, "test_chain")
    environment = ScriptedEnvironment(
        snapshots=[
            ObservationSnapshot(),
            ObservationSnapshot(inventory={"oak_log": 1}),
            ObservationSnapshot(inventory={"oak_log": 1, "oak_planks": 4}),
        ]
    )

    report = run_compiled_chain(compiled, environment, ScriptedAgent(), per_stage_profiles=True)

    assert report.completed is True
    assert environment.reset_profiles == ["fixed_ore_progression_shaft"]


def test_run_compiled_chain_stops_on_timeout():
    compiled = compile_chain(_catalog(), "test_chain")
    environment = ScriptedEnvironment(
        snapshots=[
            ObservationSnapshot(),
            ObservationSnapshot(),
            ObservationSnapshot(),
        ]
    )
    agent = ScriptedAgent()

    report = run_compiled_chain(compiled, environment, agent)

    assert report.completed is False
    assert len(report.stages) == 1
    assert report.stages[0].status == "timeout"
    assert report.stages[0].steps == 2


def test_failed_stage_records_consumed_resource_waste_event():
    compiled = compile_chain(_catalog(), "test_chain")
    craft_stage = compiled.stages[1]
    stage = type(
        "Stage",
        (),
        {
            "task": craft_stage.task,
            "mission_events": (),
            "consumed_resource_path": (
                {"source": "craft_planks", "relation": "consumes", "target": "item:oak_log", "count": 1},
            ),
        },
    )()

    diagnostics = _task_stage_diagnostics(
        stage,
        ObservationSnapshot(inventory={"oak_log": 0, "oak_planks": 0}),
        ObservationSnapshot(inventory={"oak_log": 1, "oak_planks": 0}),
        status="timeout",
    )

    assert diagnostics["start_snapshot"]["inventory"]["oak_log"] == 1
    assert diagnostics["resource_waste_events"] == [
        {
            "type": "consumed_resource_without_stage_success",
            "task_id": "craft_planks",
            "status": "timeout",
            "state": "item:oak_log",
            "item": "oak_log",
            "start_count": 1.0,
            "final_count": 0.0,
            "delta": 1.0,
            "expected_count": 1,
        }
    ]


def test_passed_stage_does_not_record_resource_waste_event():
    compiled = compile_chain(_catalog(), "test_chain")
    craft_stage = compiled.stages[1]
    stage = type(
        "Stage",
        (),
        {
            "task": craft_stage.task,
            "mission_events": (),
            "consumed_resource_path": (
                {"source": "craft_planks", "relation": "consumes", "target": "item:oak_log", "count": 1},
            ),
        },
    )()

    diagnostics = _task_stage_diagnostics(
        stage,
        ObservationSnapshot(inventory={"oak_log": 0, "oak_planks": 4}),
        ObservationSnapshot(inventory={"oak_log": 1, "oak_planks": 0}),
        status="passed",
    )

    assert "resource_waste_events" not in diagnostics


def test_run_compiled_chain_marks_night_survived_from_world_time():
    task = TaskSpec(
        id="survive_first_night",
        name="Survive Night",
        domain="survival",
        instruction="Survive.",
        max_steps=3,
        environment_profile="forest_night",
        success={"all": [{"predicate": "flag_is_true", "flag": "night_survived"}]},
    )
    catalog = BenchmarkCatalog(
        states={
            "environment:spawned_world": StateSpec(
                id="environment:spawned_world",
                kind="environment",
                description="Spawned.",
            ),
            "player:night_survived": StateSpec(
                id="player:night_survived",
                kind="player",
                description="Survived.",
            ),
        },
        tasks={"survive_first_night": task},
        edges=(
            EdgeSpec("environment:spawned_world", "requires", "survive_first_night"),
            EdgeSpec("survive_first_night", "produces", "player:night_survived"),
        ),
        chains={
            "night": ChainSpec(
                id="night",
                name="Night",
                kind="probe",
                task_ids=("survive_first_night",),
                initial_states=("environment:spawned_world",),
                domains=("survival",),
                difficulty="probe",
                environment_profile="forest_night",
            )
        },
    )
    compiled = compile_chain(catalog, "night")
    environment = ScriptedEnvironment(
        snapshots=[
            ObservationSnapshot(player_stats={"total_time": 10, "world_time": 14000, "is_alive": True}),
            ObservationSnapshot(player_stats={"total_time": 11, "world_time": 14001, "is_alive": True}),
            ObservationSnapshot(player_stats={"total_time": 12, "world_time": 14002, "is_alive": True}),
            ObservationSnapshot(player_stats={"total_time": 13, "world_time": 14003, "is_alive": True}),
        ]
    )

    report = run_compiled_chain(compiled, environment, ScriptedAgent())

    assert report.completed is True
    assert report.stages[0].status == "passed"
    assert report.stages[0].steps == 3
    assert report.stages[0].diagnostics["predicate_actuals"][0]["actual"] is True


def test_run_compiled_chain_applies_mission_event_effect_from_real_observation():
    task = TaskSpec(
        id="scout_coal_source",
        name="Scout Coal",
        domain="exploration",
        instruction="Find coal.",
        max_steps=2,
        environment_profile="fixed_coal_shaft",
        success={"all": [{"predicate": "flag_is_true", "flag": "coal_source_known"}]},
    )
    catalog = BenchmarkCatalog(
        states={
            "environment:spawned_world": StateSpec(
                id="environment:spawned_world",
                kind="environment",
                description="Spawned.",
            ),
            "location:coal_source_known": StateSpec(
                id="location:coal_source_known",
                kind="location",
                description="Coal known.",
            ),
        },
        tasks={"scout_coal_source": task},
        edges=(
            EdgeSpec("environment:spawned_world", "requires", "scout_coal_source"),
            EdgeSpec("scout_coal_source", "produces", "location:coal_source_known"),
        ),
        chains={
            "coal": ChainSpec(
                id="coal",
                name="Coal",
                kind="probe",
                task_ids=("scout_coal_source",),
                initial_states=("environment:spawned_world",),
                domains=("exploration",),
                difficulty="probe",
                environment_profile="fixed_coal_shaft",
            )
        },
        mission_events={
            "event:coal_source_observed": MissionEventSpec(
                id="event:coal_source_observed",
                task_id="scout_coal_source",
                produced_state="location:coal_source_known",
                kind="exploration_observation",
                trigger={
                    "any_of": [
                        {"path": "raw_observation.line_of_sight.coal_ore", "operator": ">=", "value": 1},
                        {"path": "raw_observation.nearby_blocks.coal_ore", "operator": ">=", "value": 1},
                    ]
                },
                snapshot_effect={"flags_add": ["coal_source_known"]},
                terminal_condition={"same_as": "trigger"},
                failure_condition={"path": "player_stats.is_alive", "operator": "==", "value": False},
                implementation_status="partial",
            )
        },
    )
    compiled = compile_chain(catalog, "coal")
    environment = ScriptedEnvironment(
        [
            ObservationSnapshot(raw_observation={"nearby_blocks": {"coal_ore": 0}}),
            ObservationSnapshot(raw_observation={"nearby_blocks": {"coal_ore": 2}}),
        ]
    )

    report = run_compiled_chain(compiled, environment, ScriptedAgent())

    assert report.completed is True
    assert report.stages[0].status == "passed"
    event_evidence = report.stages[0].diagnostics["mission_event_evidence"][0]
    assert event_evidence["passed"] is True
    assert event_evidence["trigger"]["children"][1]["actual"] == 2
    terminal_evidence = report.stages[0].diagnostics["mission_terminal_evidence"][0]
    assert terminal_evidence["terminal_condition"]["passed"] is True
    assert terminal_evidence["failure_condition"]["passed"] is False


def test_run_compiled_chain_stops_on_mission_failure_condition():
    task = TaskSpec(
        id="survive_first_night",
        name="Survive Night",
        domain="survival",
        instruction="Stay alive.",
        max_steps=3,
        environment_profile="forest_night",
        success={"all": [{"predicate": "flag_is_true", "flag": "night_survived"}]},
    )
    catalog = BenchmarkCatalog(
        states={
            "environment:spawned_world": StateSpec(
                id="environment:spawned_world",
                kind="environment",
                description="Spawned.",
            ),
            "player:night_survived": StateSpec(
                id="player:night_survived",
                kind="player",
                description="Survived.",
            ),
        },
        tasks={"survive_first_night": task},
        edges=(
            EdgeSpec("environment:spawned_world", "requires", "survive_first_night"),
            EdgeSpec("survive_first_night", "produces", "player:night_survived"),
        ),
        chains={
            "night": ChainSpec(
                id="night",
                name="Night",
                kind="probe",
                task_ids=("survive_first_night",),
                initial_states=("environment:spawned_world",),
                domains=("survival",),
                difficulty="probe",
                environment_profile="forest_night",
            )
        },
        mission_events={
            "event:night_interval_survived": MissionEventSpec(
                id="event:night_interval_survived",
                task_id="survive_first_night",
                produced_state="player:night_survived",
                kind="temporal_survival",
                trigger={
                    "operator": "elapsed_at_least",
                    "start_path": "stage_start.player_stats.total_time",
                    "end_path": "player_stats.total_time",
                    "value": 3,
                },
                snapshot_effect={"flags_add": ["night_survived"]},
                terminal_condition={"same_as": "trigger"},
                failure_condition={"path": "player_stats.is_alive", "operator": "==", "value": False},
                implementation_status="implemented",
            )
        },
    )
    compiled = compile_chain(catalog, "night")
    environment = ScriptedEnvironment(
        [
            ObservationSnapshot(player_stats={"total_time": 10, "is_alive": True}),
            ObservationSnapshot(player_stats={"total_time": 11, "is_alive": False}),
            ObservationSnapshot(player_stats={"total_time": 12, "is_alive": False}),
        ]
    )

    report = run_compiled_chain(compiled, environment, ScriptedAgent())

    assert report.completed is False
    assert report.stages[0].status == "failed"
    assert report.stages[0].steps == 1
    terminal_evidence = report.stages[0].diagnostics["mission_terminal_evidence"][0]
    assert terminal_evidence["failure_condition"]["passed"] is True


def test_mission_event_evidence_serializes_numpy_scalar_booleans():
    numpy = pytest.importorskip("numpy")
    task = TaskSpec(
        id="build_lit_shelter",
        name="Build Shelter",
        domain="building",
        instruction="Build.",
        max_steps=1,
        environment_profile="forest_dusk",
        success={"all": [{"predicate": "flag_is_true", "flag": "lit_shelter"}]},
    )
    stage = type(
        "Stage",
        (),
        {
            "task": task,
            "mission_events": (
                MissionEventSpec(
                    id="event:lit_shelter_observed",
                    task_id="build_lit_shelter",
                    produced_state="structure:lit_shelter",
                    kind="structure_observation",
                    trigger={
                        "path": "player_stats.can_see_sky",
                        "operator": "==",
                        "value": False,
                    },
                    snapshot_effect={"flags_add": ["lit_shelter"]},
                    implementation_status="partial",
                ),
            ),
        },
    )()
    snapshot = ObservationSnapshot(player_stats={"can_see_sky": numpy.bool_(False)})

    diagnostics = _task_stage_diagnostics(stage, snapshot, snapshot)

    assert diagnostics["mission_event_evidence"][0]["passed"] is True


def test_report_serializes_numpy_scalars():
    numpy = pytest.importorskip("numpy")
    from mcbench.reporting import ChainRunReport, StageReport

    report = ChainRunReport(
        chain_id="numpy",
        completed=numpy.bool_(False),
        stages=(
            StageReport(
                task_id="probe",
                status="timeout",
                steps=numpy.int64(1),
                failures=(),
                diagnostics={"actual": numpy.float32(1.5), "flag": numpy.bool_(True)},
            ),
        ),
    )

    payload = report.to_dict()

    assert payload["completed"] is False
    assert payload["stages"][0]["steps"] == 1
    assert payload["stages"][0]["diagnostics"]["actual"] == pytest.approx(1.5)
    assert payload["stages"][0]["diagnostics"]["flag"] is True


def test_run_report_marks_missing_observation_source_evidence():
    compiled = compile_chain(_catalog(), "test_chain")
    environment = ScriptedEnvironment(
        snapshots=[
            ObservationSnapshot(),
            ObservationSnapshot(inventory={"oak_log": 1}, raw_observation={}),
        ]
    )

    report = run_compiled_chain(compiled, environment, ScriptedAgent())

    evidence = report.stages[0].diagnostics["observation_evidence"][0]
    assert evidence["path"] == "inventory.oak_log"
    assert evidence["observed"] is True
    assert evidence["actual"] == 1


def test_run_report_expands_any_of_predicate_actuals():
    task = TaskSpec(
        id="craft_stone_sword",
        name="Craft Stone Sword",
        domain="combat",
        instruction="Craft sword.",
        max_steps=1,
        environment_profile="forest_day",
        success={
            "all": [
                {
                    "predicate": "any_of",
                    "options": [
                        {"predicate": "inventory_at_least", "item": "stone_sword", "count": 1},
                        {"predicate": "equipped_equals", "slot": "mainhand", "item": "stone_sword"},
                    ],
                }
            ]
        },
    )
    catalog = BenchmarkCatalog(
        states={
            "environment:spawned_world": StateSpec(
                id="environment:spawned_world",
                kind="environment",
                description="Spawned.",
            )
        },
        tasks={"craft_stone_sword": task},
        edges=(EdgeSpec("environment:spawned_world", "requires", "craft_stone_sword"),),
        chains={
            "sword": ChainSpec(
                id="sword",
                name="Sword",
                kind="probe",
                task_ids=("craft_stone_sword",),
                initial_states=("environment:spawned_world",),
                domains=("combat",),
                difficulty="probe",
                environment_profile="forest_day",
            )
        },
    )
    compiled = compile_chain(catalog, "sword")
    environment = ScriptedEnvironment([ObservationSnapshot(equipped={"mainhand": "stone_sword"})])

    report = run_compiled_chain(compiled, environment, ScriptedAgent())

    actual = report.stages[0].diagnostics["predicate_actuals"][0]
    assert actual["predicate"] == "any_of"
    assert actual["passed"] is True
    assert actual["options"][0]["passed"] is False
    assert actual["options"][1]["passed"] is True


def test_stage_diagnostics_include_graph_semantic_paths():
    compiled = compile_chain(_catalog(), "test_chain")
    stage = type(
        "Stage",
        (),
        {
            "task": compiled.stages[1].task,
            "mission_events": (),
            "hard_prerequisite_path": (
                {"source": "item:oak_log", "relation": "requires", "target": "craft_planks"},
            ),
            "soft_enabled_path": (
                {"source": "environment:work_area_ready", "relation": "enables", "target": "craft_planks"},
            ),
            "consumed_resource_path": (
                {"source": "craft_planks", "relation": "consumes", "target": "item:oak_log"},
            ),
            "abstract_ability_path": (
                {"source": "craft_planks", "relation": "abstracts_to", "target": "task_group:basic_crafting"},
            ),
        },
    )()

    diagnostics = _task_stage_diagnostics(stage, ObservationSnapshot(inventory={"oak_planks": 4}))

    assert diagnostics["graph_paths"]["hard_prerequisite_path"][0]["relation"] == "requires"
    assert diagnostics["graph_paths"]["soft_enabled_path"][0]["relation"] == "enables"
    assert diagnostics["graph_paths"]["consumed_resource_path"][0]["relation"] == "consumes"
    assert diagnostics["graph_paths"]["abstract_ability_path"][0]["relation"] == "abstracts_to"

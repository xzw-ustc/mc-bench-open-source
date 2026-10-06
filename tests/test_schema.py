import pytest

from mcbench.schema import BenchmarkSplitSpec, ChainSpec, EdgeSpec, MissionEventSpec, StateSpec, TaskSpec


def test_schema_models_accept_valid_benchmark_records():
    state = StateSpec(
        id="item:oak_log",
        kind="item",
        description="At least one oak log is available.",
    )
    task = TaskSpec(
        id="collect_log",
        name="Collect Log",
        domain="survival",
        instruction="Collect one oak log.",
        max_steps=200,
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
    )
    edge = EdgeSpec(source="collect_log", relation="produces", target="item:oak_log")
    chain = ChainSpec(
        id="warmup_survival",
        name="Warmup Survival",
        kind="vertical",
        task_ids=("collect_log",),
        initial_states=("environment:spawned_world",),
        domains=("survival",),
        difficulty="simple",
        environment_profile="forest_day",
    )

    assert state.kind == "item"
    assert task.max_steps == 200
    assert task.observation_sources[0]["path"] == "inventory.oak_log"
    assert edge.relation == "produces"
    assert edge.count == 1
    assert chain.task_ids == ("collect_log",)
    assert chain.profile_policy == "task"


def test_chain_schema_accepts_chain_profile_policy():
    chain = ChainSpec(
        id="fixed_resource_chain",
        name="Fixed Resource Chain",
        kind="vertical",
        task_ids=("collect_log",),
        initial_states=("environment:spawned_world",),
        domains=("survival",),
        difficulty="standard",
        environment_profile="fixed_ore_progression_shaft",
        profile_policy="chain",
    )

    assert chain.profile_policy == "chain"


def test_chain_schema_rejects_unknown_profile_policy():
    with pytest.raises(ValueError, match="chain.profile_policy"):
        ChainSpec(
            id="bad_policy",
            name="Bad Policy",
            kind="vertical",
            task_ids=("collect_log",),
            initial_states=("environment:spawned_world",),
            domains=("survival",),
            difficulty="standard",
            environment_profile="forest_day",
            profile_policy="sometimes",
        )


def test_schema_model_accepts_valid_benchmark_split_record():
    split = BenchmarkSplitSpec(
        id="core_progression",
        name="Core Progression",
        purpose="Primary chain tasks for capability progression evaluation.",
        task_ids=("collect_log", "craft_planks"),
        chain_ids=("wood_crafting_basics",),
        notes="Used for the main paper score.",
    )

    assert split.id == "core_progression"
    assert split.task_ids == ("collect_log", "craft_planks")
    assert split.chain_ids == ("wood_crafting_basics",)


def test_schema_model_accepts_valid_mission_event_record():
    event = MissionEventSpec(
        id="event:coal_source_observed",
        task_id="scout_coal_source",
        produced_state="location:coal_source_known",
        kind="exploration_observation",
        trigger={
            "any_of": [
                {"path": "raw_observation.line_of_sight.coal_ore", "operator": ">=", "value": 1}
            ]
        },
        observation_sources=(
            {
                "path": "raw_observation.line_of_sight.coal_ore",
                "kind": "primary",
                "meaning": "Ray observation sees coal ore.",
                "track": "structured_state",
                "agent_access": "evaluator_only",
            },
        ),
        snapshot_effect={"flags_add": ["coal_source_known"]},
        terminal_condition={"same_as": "trigger"},
        failure_condition={"path": "player_stats.is_alive", "operator": "==", "value": False},
        profiles=("fixed_coal_shaft",),
        implementation_status="partial",
    )

    assert event.to_dict()["id"] == "event:coal_source_observed"
    assert event.to_dict()["profiles"] == ("fixed_coal_shaft",)
    assert event.to_dict()["terminal_condition"] == {"same_as": "trigger"}
    assert event.to_dict()["failure_condition"]["path"] == "player_stats.is_alive"


def test_edge_spec_accepts_abstracts_to_relation():
    edge = EdgeSpec(source="item:oak_log", relation="abstracts_to", target="item:wood")

    assert edge.relation == "abstracts_to"


def test_edge_spec_accepts_positive_quantity():
    edge = EdgeSpec(source="craft_planks", relation="produces", target="item:oak_planks", count=4)

    assert edge.count == 4


def test_state_spec_accepts_abstract_group_kinds():
    state_group = StateSpec(
        id="state_group:wood_resource",
        kind="state_group",
        description="Wood resources.",
    )
    task_group = StateSpec(
        id="task_group:basic_crafting",
        kind="task_group",
        description="Basic crafting tasks.",
    )

    assert state_group.kind == "state_group"
    assert task_group.kind == "task_group"


@pytest.mark.parametrize("kind", ["unknown", "", "ITEM"])
def test_state_spec_rejects_unknown_kinds(kind):
    with pytest.raises(ValueError):
        StateSpec(id="bad", kind=kind, description="invalid")


@pytest.mark.parametrize("relation", ["links", "", "REQUIRES"])
def test_edge_spec_rejects_unknown_relations(relation):
    with pytest.raises(ValueError):
        EdgeSpec(source="collect_log", relation=relation, target="item:oak_log")


@pytest.mark.parametrize("count", [0, -1, 1.5, "1"])
def test_edge_spec_rejects_invalid_quantities(count):
    with pytest.raises(ValueError):
        EdgeSpec(source="collect_log", relation="produces", target="item:oak_log", count=count)


def test_task_spec_rejects_non_positive_step_budget():
    with pytest.raises(ValueError):
        TaskSpec(
            id="collect_log",
            name="Collect Log",
            domain="survival",
            instruction="Collect one oak log.",
            max_steps=0,
            environment_profile="forest_day",
            success={"all": []},
        )


def test_task_spec_rejects_invalid_observation_sources():
    with pytest.raises(ValueError):
        TaskSpec(
            id="collect_log",
            name="Collect Log",
            domain="survival",
            instruction="Collect one oak log.",
            max_steps=1,
            environment_profile="forest_day",
            success={"all": []},
            observation_sources=("inventory.oak_log",),
        )


def test_task_spec_rejects_observation_source_without_track():
    with pytest.raises(ValueError, match="track"):
        TaskSpec(
            id="collect_log",
            name="Collect Log",
            domain="survival",
            instruction="Collect one oak log.",
            max_steps=1,
            environment_profile="forest_day",
            success={"all": []},
            observation_sources=(
                {
                    "path": "inventory.oak_log",
                    "kind": "primary",
                    "meaning": "MineRL inventory contains an oak log.",
                    "agent_access": "agent_visible",
                },
            ),
        )


def test_mission_event_spec_rejects_invalid_trigger():
    with pytest.raises(ValueError):
        MissionEventSpec(
            id="event:broken",
            task_id="collect_log",
            produced_state="item:oak_log",
            kind="inventory_event",
            trigger=[],
        )


def test_mission_event_spec_rejects_invalid_terminal_conditions():
    with pytest.raises(ValueError):
        MissionEventSpec(
            id="event:broken_terminal",
            task_id="collect_log",
            produced_state="item:oak_log",
            kind="inventory_event",
            trigger={},
            terminal_condition=[],
        )
    with pytest.raises(ValueError):
        MissionEventSpec(
            id="event:broken_failure",
            task_id="collect_log",
            produced_state="item:oak_log",
            kind="inventory_event",
            trigger={},
            failure_condition=[],
        )

import pytest

from mcbench.catalog import BenchmarkCatalog
from mcbench.chains import ChainValidationError, compile_chain
from mcbench.schema import ChainSpec, EdgeSpec, StateSpec, TaskSpec


def _task(task_id):
    return TaskSpec(
        id=task_id,
        name=task_id,
        domain="survival",
        instruction="Do it.",
        max_steps=100,
        environment_profile="forest_day",
        success={"all": []},
    )


def _catalog_with_chain(task_order):
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
        "collect_log": _task("collect_log"),
        "craft_planks": _task("craft_planks"),
    }
    edges = (
        EdgeSpec("environment:spawned_world", "requires", "collect_log"),
        EdgeSpec("collect_log", "produces", "item:oak_log"),
        EdgeSpec("item:oak_log", "requires", "craft_planks"),
            EdgeSpec("craft_planks", "produces", "item:oak_planks", count=4),
    )
    chains = {
        "test_chain": ChainSpec(
            id="test_chain",
            name="Test Chain",
            kind="vertical",
            task_ids=tuple(task_order),
            initial_states=("environment:spawned_world",),
            domains=("survival",),
            difficulty="simple",
            environment_profile="forest_day",
        )
    }
    return BenchmarkCatalog(states=states, tasks=tasks, edges=edges, chains=chains)


def test_compile_chain_resolves_stage_dependencies_in_order():
    compiled = compile_chain(_catalog_with_chain(["collect_log", "craft_planks"]), "test_chain")

    assert [stage.task.id for stage in compiled.stages] == ["collect_log", "craft_planks"]
    assert compiled.stages[1].required_states == {"item:oak_log"}
    assert compiled.stages[1].produced_state_counts == {"item:oak_planks": 4}
    assert compiled.available_state_counts["item:oak_planks"] == 4
    assert compiled.available_states == {
        "environment:spawned_world",
        "item:oak_log",
        "item:oak_planks",
    }


def test_compile_chain_rejects_unmet_preconditions():
    with pytest.raises(ChainValidationError, match="item:oak_log"):
        compile_chain(_catalog_with_chain(["craft_planks", "collect_log"]), "test_chain")


def test_compile_chain_allows_insufficient_quantities_by_default_for_qualitative_chains():
    catalog = _catalog_with_chain(["collect_log", "craft_planks"])
    catalog = BenchmarkCatalog(
        states=catalog.states,
        tasks=catalog.tasks,
        edges=(
            EdgeSpec("environment:spawned_world", "requires", "collect_log"),
            EdgeSpec("collect_log", "produces", "item:oak_log"),
            EdgeSpec("item:oak_log", "requires", "craft_planks", count=2),
            EdgeSpec("craft_planks", "produces", "item:oak_planks", count=4),
        ),
        chains=catalog.chains,
    )

    compiled = compile_chain(catalog, "test_chain")

    assert [stage.task.id for stage in compiled.stages] == ["collect_log", "craft_planks"]


def test_compile_chain_can_strictly_reject_insufficient_state_quantities():
    catalog = _catalog_with_chain(["collect_log", "craft_planks"])
    catalog = BenchmarkCatalog(
        states=catalog.states,
        tasks=catalog.tasks,
        edges=(
            EdgeSpec("environment:spawned_world", "requires", "collect_log"),
            EdgeSpec("collect_log", "produces", "item:oak_log"),
            EdgeSpec("item:oak_log", "requires", "craft_planks", count=2),
            EdgeSpec("craft_planks", "produces", "item:oak_planks", count=4),
        ),
        chains=catalog.chains,
    )

    with pytest.raises(ChainValidationError, match="required=2 available=1"):
        compile_chain(catalog, "test_chain", strict_quantities=True)


def test_compile_chain_removes_consumed_states_from_later_availability():
    catalog = _catalog_with_chain(["collect_log", "craft_planks"])
    catalog = BenchmarkCatalog(
        states=catalog.states,
        tasks=catalog.tasks,
        edges=tuple(catalog.edges) + (EdgeSpec("craft_planks", "consumes", "item:oak_log"),),
        chains=catalog.chains,
    )

    compiled = compile_chain(catalog, "test_chain")

    assert compiled.stages[1].consumed_states == {"item:oak_log"}
    assert compiled.available_state_counts["item:oak_planks"] == 4
    assert compiled.available_states == {
        "environment:spawned_world",
        "item:oak_planks",
    }


def test_compile_chain_exposes_graph_semantic_paths():
    base = _catalog_with_chain(["collect_log", "craft_planks"])
    catalog = BenchmarkCatalog(
        states={
            **base.states,
            "state_group:wood_resource": StateSpec(
                id="state_group:wood_resource",
                kind="state_group",
                description="Wood resources.",
            ),
            "environment:work_area_ready": StateSpec(
                id="environment:work_area_ready",
                kind="environment",
                description="Work area.",
            ),
        },
        tasks=base.tasks,
        edges=tuple(base.edges)
        + (
            EdgeSpec("environment:work_area_ready", "enables", "craft_planks"),
            EdgeSpec("craft_planks", "consumes", "item:oak_log", count=1),
            EdgeSpec("item:oak_log", "abstracts_to", "state_group:wood_resource"),
            EdgeSpec("craft_planks", "abstracts_to", "state_group:wood_resource"),
        ),
        chains=base.chains,
    )

    compiled = compile_chain(catalog, "test_chain")
    stage = compiled.stages[1]

    assert stage.hard_prerequisite_path == (
        {"source": "item:oak_log", "relation": "requires", "target": "craft_planks", "count": 1},
    )
    assert stage.soft_enabled_path == (
        {"source": "environment:work_area_ready", "relation": "enables", "target": "craft_planks", "count": 1},
    )
    assert stage.consumed_resource_path == (
        {"source": "craft_planks", "relation": "consumes", "target": "item:oak_log", "count": 1},
    )
    assert stage.produced_resource_path == (
        {"source": "craft_planks", "relation": "produces", "target": "item:oak_planks", "count": 4},
    )
    assert {"source": "craft_planks", "relation": "abstracts_to", "target": "state_group:wood_resource"} in (
        stage.abstract_ability_path
    )
    assert {"source": "item:oak_log", "relation": "abstracts_to", "target": "state_group:wood_resource"} in (
        stage.abstract_ability_path
    )

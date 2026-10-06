import pytest

from mcbench.catalog import BenchmarkCatalog
from mcbench.graph import GraphError, TaskStateGraph
from mcbench.schema import EdgeSpec, StateSpec, TaskSpec


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


def test_task_state_graph_indexes_required_and_produced_states():
    catalog = BenchmarkCatalog(
        states={
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
        },
        tasks={"collect_log": _task("collect_log")},
        edges=(
            EdgeSpec("environment:spawned_world", "requires", "collect_log"),
            EdgeSpec("environment:spawned_world", "enables", "collect_log"),
            EdgeSpec("collect_log", "produces", "item:oak_log", count=2),
            EdgeSpec("collect_log", "consumes", "environment:spawned_world", count=1),
            EdgeSpec("item:oak_log", "abstracts_to", "environment:spawned_world"),
        ),
        chains={},
    )

    graph = TaskStateGraph.from_catalog(catalog)

    assert graph.required_states("collect_log") == {"environment:spawned_world"}
    assert graph.produced_states("collect_log") == {"item:oak_log"}
    assert graph.enabled_states("collect_log") == {"environment:spawned_world"}
    assert graph.consumed_states("collect_log") == {"environment:spawned_world"}
    assert graph.produced_state_counts("collect_log") == {"item:oak_log": 2}
    assert graph.consumed_state_counts("collect_log") == {"environment:spawned_world": 1}
    assert graph.abstractions["item:oak_log"] == {"environment:spawned_world"}


def test_task_state_graph_rejects_invalid_requires_direction():
    catalog = BenchmarkCatalog(
        states={
            "environment:spawned_world": StateSpec(
                id="environment:spawned_world",
                kind="environment",
                description="Spawned.",
            )
        },
        tasks={"collect_log": _task("collect_log")},
        edges=(EdgeSpec("collect_log", "requires", "environment:spawned_world"),),
        chains={},
    )

    with pytest.raises(GraphError, match="requires"):
        TaskStateGraph.from_catalog(catalog)

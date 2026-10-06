import json

import pytest

from mcbench.catalog import CatalogError, load_catalog_dir


def _write_catalog_file(path, name, payload):
    file_path = path / name
    file_path.write_text(json.dumps(payload), encoding="utf-8")
    return file_path


def test_load_catalog_dir_builds_indexed_catalog(tmp_path):
    _write_catalog_file(
        tmp_path,
        "states.json",
        [{"id": "environment:spawned_world", "kind": "environment", "description": "Spawned."}],
    )
    _write_catalog_file(
        tmp_path,
        "tasks.json",
        [
            {
                "id": "collect_log",
                "name": "Collect Log",
                "domain": "survival",
                "instruction": "Collect one log.",
                "max_steps": 200,
                "environment_profile": "forest_day",
                "success": {"all": [{"predicate": "inventory_at_least", "item": "oak_log", "count": 1}]},
                "observation_sources": [
                    {
                        "path": "inventory.oak_log",
                        "kind": "primary",
                        "meaning": "MineRL inventory contains an oak log.",
                        "track": "native_perception",
                        "agent_access": "agent_visible",
                    }
                ],
            }
        ],
    )
    _write_catalog_file(
        tmp_path,
        "edges.json",
        [{"source": "environment:spawned_world", "relation": "requires", "target": "collect_log", "count": 1}],
    )
    _write_catalog_file(
        tmp_path,
        "chains.json",
        [
            {
                "id": "warmup",
                "name": "Warmup",
                "kind": "vertical",
                "task_ids": ["collect_log"],
                "initial_states": ["environment:spawned_world"],
                "domains": ["survival"],
                "difficulty": "simple",
                "environment_profile": "forest_day",
            }
        ],
    )
    _write_catalog_file(
        tmp_path,
        "mission_events.json",
        [
            {
                "id": "event:collect_log_inventory",
                "task_id": "collect_log",
                "produced_state": "environment:spawned_world",
                "kind": "inventory_event",
                "trigger": {
                    "path": "inventory.oak_log",
                    "operator": ">=",
                    "value": 1,
                },
                "terminal_condition": {"same_as": "trigger"},
                "failure_condition": {
                    "path": "player_stats.is_alive",
                    "operator": "==",
                    "value": False,
                },
                "implementation_status": "implemented",
            }
        ],
    )
    _write_catalog_file(
        tmp_path,
        "splits.json",
        [
            {
                "id": "core_progression",
                "name": "Core Progression",
                "purpose": "Primary progression tasks.",
                "task_ids": ["collect_log"],
                "chain_ids": ["warmup"],
            }
        ],
    )

    catalog = load_catalog_dir(tmp_path)

    assert catalog.tasks["collect_log"].name == "Collect Log"
    assert catalog.tasks["collect_log"].observation_sources[0]["path"] == "inventory.oak_log"
    assert catalog.mission_events["event:collect_log_inventory"].task_id == "collect_log"
    assert catalog.mission_events["event:collect_log_inventory"].terminal_condition == {"same_as": "trigger"}
    assert catalog.mission_events["event:collect_log_inventory"].failure_condition["path"] == "player_stats.is_alive"
    assert catalog.states["environment:spawned_world"].kind == "environment"
    assert catalog.chains["warmup"].task_ids == ("collect_log",)
    assert catalog.splits["core_progression"].task_ids == ("collect_log",)
    assert catalog.splits["core_progression"].chain_ids == ("warmup",)
    assert len(catalog.edges) == 1
    assert catalog.edges[0].count == 1


def test_load_catalog_dir_rejects_edges_with_missing_nodes(tmp_path):
    _write_catalog_file(
        tmp_path,
        "states.json",
        [{"id": "environment:spawned_world", "kind": "environment", "description": "Spawned."}],
    )
    _write_catalog_file(tmp_path, "tasks.json", [])
    _write_catalog_file(
        tmp_path,
        "edges.json",
        [{"source": "missing_task", "relation": "produces", "target": "environment:spawned_world"}],
    )
    _write_catalog_file(tmp_path, "chains.json", [])

    with pytest.raises(CatalogError, match="missing_task"):
        load_catalog_dir(tmp_path)


def test_load_catalog_dir_rejects_chain_with_missing_task(tmp_path):
    _write_catalog_file(
        tmp_path,
        "states.json",
        [{"id": "environment:spawned_world", "kind": "environment", "description": "Spawned."}],
    )
    _write_catalog_file(tmp_path, "tasks.json", [])
    _write_catalog_file(tmp_path, "edges.json", [])
    _write_catalog_file(
        tmp_path,
        "chains.json",
        [
            {
                "id": "broken",
                "name": "Broken",
                "kind": "vertical",
                "task_ids": ["missing_task"],
                "initial_states": ["environment:spawned_world"],
                "domains": ["survival"],
                "difficulty": "simple",
                "environment_profile": "forest_day",
            }
        ],
    )

    with pytest.raises(CatalogError, match="missing_task"):
        load_catalog_dir(tmp_path)


def test_load_catalog_dir_rejects_mission_event_with_missing_task(tmp_path):
    _write_catalog_file(
        tmp_path,
        "states.json",
        [{"id": "environment:spawned_world", "kind": "environment", "description": "Spawned."}],
    )
    _write_catalog_file(tmp_path, "tasks.json", [])
    _write_catalog_file(tmp_path, "edges.json", [])
    _write_catalog_file(tmp_path, "chains.json", [])
    _write_catalog_file(
        tmp_path,
        "mission_events.json",
        [
            {
                "id": "event:broken",
                "task_id": "missing_task",
                "produced_state": "environment:spawned_world",
                "kind": "event",
                "trigger": {},
            }
        ],
    )

    with pytest.raises(CatalogError, match="missing_task"):
        load_catalog_dir(tmp_path)


def test_load_catalog_dir_rejects_split_with_missing_references(tmp_path):
    _write_catalog_file(
        tmp_path,
        "states.json",
        [{"id": "environment:spawned_world", "kind": "environment", "description": "Spawned."}],
    )
    _write_catalog_file(tmp_path, "tasks.json", [])
    _write_catalog_file(tmp_path, "edges.json", [])
    _write_catalog_file(tmp_path, "chains.json", [])
    _write_catalog_file(
        tmp_path,
        "splits.json",
        [
            {
                "id": "broken_split",
                "name": "Broken Split",
                "purpose": "References a missing task.",
                "task_ids": ["missing_task"],
                "chain_ids": [],
            }
        ],
    )

    with pytest.raises(CatalogError, match="missing_task"):
        load_catalog_dir(tmp_path)


def test_v1_catalog_declares_observation_tracks_for_all_sources():
    catalog = load_catalog_dir("benchmarks/v1")
    task_sources = [
        source
        for task in catalog.tasks.values()
        for source in task.observation_sources
    ]
    event_sources = [
        source
        for event in catalog.mission_events.values()
        for source in event.observation_sources
    ]
    sources = task_sources + event_sources

    assert len(catalog.tasks) == 80
    assert len(task_sources) >= 80
    assert {source["track"] for source in sources} == {"native_perception", "structured_state"}
    assert {source["agent_access"] for source in sources} == {"agent_visible", "evaluator_only"}

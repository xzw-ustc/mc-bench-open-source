import json
from dataclasses import replace

import pytest

from mcbench.catalog import BenchmarkCatalog
from mcbench.catalog import load_catalog_dir
from mcbench.profiles import (
    ProfileCatalogError,
    audit_controlled_resource_catalog,
    load_profile_catalog,
    validate_profile_references,
)
from mcbench.schema import ChainSpec, MissionEventSpec, TaskSpec
from mcbench.cli import _build_minerl_environment


def test_load_profile_catalog_reads_named_profiles(tmp_path):
    payload = [
        {
            "id": "forest_progression",
            "env_id": "MineRLTreechop-v0",
            "seed": 7,
            "day_phase": "dusk",
            "weather": "clear",
            "initial_inventory": {"oak_log": 1},
            "metadata": {"purpose": "mixed chain"},
        }
    ]
    (tmp_path / "profiles.json").write_text(json.dumps(payload), encoding="utf-8")

    profiles = load_profile_catalog(tmp_path)

    profile = profiles["forest_progression"]
    assert profile.env_id == "MineRLTreechop-v0"
    assert profile.seed == 7
    assert profile.initial_inventory["oak_log"] == 1


def test_load_profile_catalog_extends_a_parent_catalog(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    (parent / "profiles.json").write_text(
        json.dumps([{"id": "base", "env_id": "MineRLTreechop-v0"}]),
        encoding="utf-8",
    )
    child = tmp_path / "child"
    child.mkdir()
    (child / "profiles.json").write_text(
        json.dumps(
            {
                "extends": "../parent",
                "profiles": [{"id": "probe", "env_id": "MineRLTreechop-v0"}],
            }
        ),
        encoding="utf-8",
    )

    profiles = load_profile_catalog(child)

    assert set(profiles) == {"base", "probe"}


def test_controlled_resource_profiles_document_world_resource_placement():
    profiles = load_profile_catalog("benchmarks/v1")
    controlled_profiles = {
        profile_id: profile
        for profile_id, profile in profiles.items()
        if profile_id.startswith("fixed_") and profile_id.endswith("_shaft")
    }

    assert set(controlled_profiles) == {
        "fixed_coal_shaft",
        "fixed_iron_shaft",
        "fixed_gold_shaft",
        "fixed_redstone_shaft",
        "fixed_lapis_shaft",
        "fixed_diamond_shaft",
        "fixed_emerald_shaft",
        "fixed_ore_progression_shaft",
    }
    for profile in controlled_profiles.values():
        assert profile.initial_inventory == {}
        assert profile.metadata["known_blocks"]
        assert profile.metadata["controlled_resources"]
        assert "world_decorator" in profile.metadata
        for controlled_resource in profile.metadata["controlled_resources"]:
            placement = controlled_resource["placement"]
            assert placement["relative_to"] in {"start_position", "actual_spawn_position"}
            assert placement["y_band"][0] <= placement["y_band"][1]
            assert placement["horizontal_radius"] >= 4
            assert placement["vertical_radius"] >= 2
            assert controlled_resource["success_still_requires"]


def test_hard_resource_profiles_use_underground_controlled_pockets():
    profiles = load_profile_catalog("benchmarks/v1")
    expected_bands = {
        "fixed_iron_shaft": ("iron_ore", [70, 71]),
        "fixed_gold_shaft": ("gold_ore", [70, 71]),
        "fixed_redstone_shaft": ("redstone_ore", [70, 71]),
        "fixed_lapis_shaft": ("lapis_ore", [70, 71]),
        "fixed_diamond_shaft": ("diamond_ore", [70, 71]),
        "fixed_emerald_shaft": ("emerald_ore", [70, 71]),
    }

    for profile_id, (resource, y_band) in expected_bands.items():
        profile = profiles[profile_id]
        controlled_resource = profile.metadata["controlled_resources"][0]
        placement = controlled_resource["placement"]
        assert controlled_resource["resource"] == resource
        assert placement["type"] == "near_spawn_underground_controlled_pocket"
        assert placement["y_band"] == y_band
        assert profile.metadata["start_position"]["y"] == 72
        assert placement["relative_to"] == "actual_spawn_position"
        assert all(block["type"] == resource for block in profile.metadata["known_blocks"])
        assert all(y_band[0] <= block["y"] <= y_band[1] for block in profile.metadata["known_blocks"])


def test_ore_progression_profile_uses_underground_multi_level_gallery():
    profile = load_profile_catalog("benchmarks/v1")["fixed_ore_progression_shaft"]
    expected_bands = {
        "redstone_ore": [70, 71],
        "diamond_ore": [70, 71],
        "lapis_ore": [70, 71],
        "emerald_ore": [70, 71],
        "gold_ore": [70, 71],
        "iron_ore": [70, 71],
        "coal_ore": [70, 71],
    }
    resources = {
        item["resource"]: item["placement"]
        for item in profile.metadata["controlled_resources"]
    }

    assert profile.metadata["start_position"]["y"] == 72
    support = profile.metadata["spawn_support_decorator"]
    assert 'y1="71"' in support and 'y2="71"' in support
    assert 'type="stone"' in support
    assert resources.keys() == expected_bands.keys()
    for resource, y_band in expected_bands.items():
        placement = resources[resource]
        assert placement["type"] == "near_spawn_underground_multi_resource_gallery"
        assert placement["y_band"] == y_band
        assert placement["horizontal_radius"] == 6
        assert placement["relative_to"] == "actual_spawn_position"


def test_ore_progression_environment_appends_spawn_support_after_air_clear():
    profile = load_profile_catalog("benchmarks/v1")["fixed_ore_progression_shaft"]
    environment = _build_minerl_environment(profile, {"kind": "minerl"})
    assert environment.world_decorator.endswith(profile.metadata["spawn_support_decorator"])


def test_scarce_resource_tasks_use_controlled_resource_profiles_by_default():
    catalog = load_catalog_dir("benchmarks/v1")
    expected_profiles = {
        "scout_coal_source": "fixed_coal_shaft",
        "collect_coal": "fixed_coal_shaft",
        "craft_torch": "fixed_coal_shaft",
        "collect_iron_ore_basic": "fixed_ore_progression_shaft",
        "smelt_iron_ingot": "fixed_ore_progression_shaft",
        "collect_iron_ore": "fixed_ore_progression_shaft",
        "collect_gold_ore": "fixed_ore_progression_shaft",
        "collect_redstone": "fixed_ore_progression_shaft",
        "collect_lapis_lazuli": "fixed_ore_progression_shaft",
        "collect_diamond": "fixed_ore_progression_shaft",
        "collect_emerald": "fixed_ore_progression_shaft",
        "smelt_gold_ingot": "fixed_ore_progression_shaft",
        "craft_iron_pickaxe": "fixed_ore_progression_shaft",
    }

    for task_id, profile_id in expected_profiles.items():
        assert catalog.tasks[task_id].environment_profile == profile_id


def test_controlled_resource_catalog_audit_accepts_current_v1_problem_instances():
    catalog = load_catalog_dir("benchmarks/v1")
    profiles = load_profile_catalog("benchmarks/v1")

    payload = audit_controlled_resource_catalog(catalog, profiles)

    assert payload["status"] == "ready"
    assert payload["expected_task_profile_count"] == 13
    assert payload["controlled_profile_count"] == 8
    assert payload["resource_count"] == 14
    assert not payload["blockers"]


def test_controlled_resource_catalog_audit_blocks_item_grants_and_wrong_task_profiles():
    catalog = load_catalog_dir("benchmarks/v1")
    profiles = dict(load_profile_catalog("benchmarks/v1"))
    profiles["fixed_diamond_shaft"] = replace(
        profiles["fixed_diamond_shaft"],
        initial_inventory={"diamond": 1},
    )
    tasks = dict(catalog.tasks)
    tasks["collect_diamond"] = replace(tasks["collect_diamond"], environment_profile="forest_day")
    catalog = replace(catalog, tasks=tasks)

    payload = audit_controlled_resource_catalog(catalog, profiles)

    assert payload["status"] == "blocked"
    assert any("Task collect_diamond should use fixed_ore_progression_shaft" in item for item in payload["blockers"])
    assert any("fixed_diamond_shaft: controlled profile must not grant initial inventory items" in item for item in payload["blockers"])


def test_load_profile_catalog_rejects_duplicate_profile_ids(tmp_path):
    payload = [
        {"id": "same", "env_id": "A"},
        {"id": "same", "env_id": "B"},
    ]
    (tmp_path / "profiles.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProfileCatalogError, match="Duplicate environment profile id"):
        load_profile_catalog(tmp_path)


def test_validate_profile_references_rejects_missing_task_profile():
    catalog = BenchmarkCatalog(
        states={},
        tasks={
            "collect_log": TaskSpec(
                id="collect_log",
                name="Collect Log",
                domain="survival",
                instruction="Collect one log.",
                max_steps=100,
                environment_profile="missing",
                success={"all": []},
            )
        },
        edges=(),
        chains={
            "warmup": ChainSpec(
                id="warmup",
                name="Warmup",
                kind="vertical",
                task_ids=("collect_log",),
                initial_states=(),
                domains=("survival",),
                difficulty="simple",
                environment_profile="forest_day",
            )
        },
    )

    with pytest.raises(ProfileCatalogError, match="collect_log"):
        validate_profile_references(catalog, {})


def test_validate_profile_references_rejects_missing_mission_event_profile():
    catalog = BenchmarkCatalog(
        states={},
        tasks={},
        edges=(),
        chains={},
        mission_events={
            "event:coal_source_observed": MissionEventSpec(
                id="event:coal_source_observed",
                task_id="scout_coal_source",
                produced_state="location:coal_source_known",
                kind="exploration_observation",
                trigger={},
                profiles=("missing_profile",),
            )
        },
    )

    with pytest.raises(ProfileCatalogError, match="event:coal_source_observed"):
        validate_profile_references(catalog, {})


def test_controlled_profiles_keep_spawn_support_after_air_clearing():
    from pathlib import Path
    import xml.etree.ElementTree as ET

    root = Path(__file__).resolve().parents[1]
    profiles = load_profile_catalog(root / 'benchmarks/v1')
    controlled = [profile for key, profile in profiles.items() if key.startswith('fixed_')]
    assert len(controlled) == 8
    for profile in controlled:
        position = profile.metadata['start_position']
        support = ET.fromstring(profile.metadata['spawn_support_decorator'])
        assert support.tag == 'DrawCuboid'
        assert support.attrib['type'] == 'stone'
        assert int(support.attrib['y1']) == int(position['y']) - 1
        assert int(support.attrib['y2']) == int(position['y']) - 1
        assert int(support.attrib['x1']) <= position['x'] <= int(support.attrib['x2'])
        assert int(support.attrib['z1']) <= position['z'] <= int(support.attrib['z2'])
        env = _build_minerl_environment(profile, {})
        assert env.world_decorator.endswith(profile.metadata['spawn_support_decorator'])

from pathlib import Path

from mcbench.adapters.minerl import default_state_extractor
from mcbench.catalog import load_catalog_dir
from mcbench.verification import evaluate_success


ROOT = Path(__file__).resolve().parents[1]


def _task_success(task_id):
    catalog = load_catalog_dir(ROOT / "benchmarks/v1")
    return catalog.tasks[task_id].success


def _assert_task_passes_from_minerl_payload(task_id, observation, info=None):
    snapshot = default_state_extractor(observation=observation, info=info or {})
    result = evaluate_success(_task_success(task_id), snapshot)

    assert result.passed is True, result.failures


def test_inventory_tasks_pass_from_minerl_inventory_observation():
    cases = {
        "collect_log": {"inventory": {"oak_log": 1}},
        "craft_planks": {"inventory": {"oak_planks": 4}},
        "craft_table": {"inventory": {"crafting_table": 1}},
        "collect_coal": {"inventory": {"coal": 1}},
        "craft_torch": {"inventory": {"torch": 1}},
    }

    for task_id, observation in cases.items():
        _assert_task_passes_from_minerl_payload(task_id, observation)


def test_environment_flag_tasks_pass_from_minerl_world_observations():
    _assert_task_passes_from_minerl_payload(
        "scout_coal_source",
        {
            "inventory": {},
            "line_of_sight": {"coal_ore": 1, "distance": 3.0},
        },
    )
    _assert_task_passes_from_minerl_payload(
        "build_lit_shelter",
        {
            "inventory": {},
            "nearby_blocks": {"torch": 1, "solid_blocks": 80, "air": 263},
            "location_stats": {
                "effective_light_level": 9,
                "effective_sky_light_level": 0,
                "can_see_sky": 0,
            },
        },
    )


def test_combat_tasks_pass_from_equipment_and_kill_observations():
    _assert_task_passes_from_minerl_payload(
        "craft_stone_sword",
        {
            "inventory": {},
            "equipped_items": {"mainhand": {"type": "minecraft:stone_sword"}},
        },
    )
    _assert_task_passes_from_minerl_payload(
        "defeat_zombie",
        {
            "inventory": {},
            "kill_entity": {"zombie": 1},
        },
    )

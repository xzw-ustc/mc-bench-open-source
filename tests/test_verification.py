from mcbench.verification import ObservationSnapshot, evaluate_success


def test_evaluate_success_accepts_mixed_structured_predicates():
    snapshot = ObservationSnapshot(
        inventory={"torch": 2},
        flags={"lit_shelter"},
        player_stats={"health": 18.0},
        counters={"zombie_defeated": 1},
        equipped={"mainhand": "stone_sword"},
    )
    success = {
        "all": [
            {"predicate": "inventory_at_least", "item": "torch", "count": 1},
            {"predicate": "flag_is_true", "flag": "lit_shelter"},
            {"predicate": "player_stat_at_least", "stat": "health", "value": 10},
            {"predicate": "counter_at_least", "counter": "zombie_defeated", "count": 1},
            {"predicate": "equipped_equals", "slot": "mainhand", "item": "stone_sword"},
        ]
    }

    result = evaluate_success(success, snapshot)

    assert result.passed is True
    assert result.failures == ()


def test_evaluate_success_reports_failed_predicates():
    snapshot = ObservationSnapshot(inventory={"torch": 0})
    success = {
        "all": [
            {"predicate": "inventory_at_least", "item": "torch", "count": 1},
            {"predicate": "flag_is_true", "flag": "lit_shelter"},
        ]
    }

    result = evaluate_success(success, snapshot)

    assert result.passed is False
    assert "inventory_at_least(torch >= 1)" in result.failures
    assert "flag_is_true(lit_shelter)" in result.failures


def test_evaluate_success_accepts_any_of_predicate():
    success = {
        "all": [
            {
                "predicate": "any_of",
                "options": [
                    {"predicate": "inventory_at_least", "item": "stone_sword", "count": 1},
                    {"predicate": "equipped_equals", "slot": "mainhand", "item": "stone_sword"},
                ],
            }
        ]
    }

    inventory_result = evaluate_success(success, ObservationSnapshot(inventory={"stone_sword": 1}))
    equipped_result = evaluate_success(success, ObservationSnapshot(equipped={"mainhand": "stone_sword"}))
    failed_result = evaluate_success(success, ObservationSnapshot(inventory={"stone_sword": 0}))

    assert inventory_result.passed is True
    assert equipped_result.passed is True
    assert failed_result.passed is False
    assert failed_result.failures == (
        "any_of(inventory_at_least(stone_sword >= 1) OR equipped_equals(mainhand == stone_sword))",
    )


def test_evaluate_success_accepts_snapshot_path_comparisons():
    success = {
        "all": [
            {
                "predicate": "snapshot_path_compare",
                "path": "raw_observation.nearby_blocks.torch",
                "operator": ">=",
                "value": 1,
            },
            {
                "predicate": "snapshot_path_compare",
                "path": "player_stats.can_see_sky",
                "operator": "==",
                "value": False,
            },
        ]
    }
    snapshot = ObservationSnapshot(
        player_stats={"can_see_sky": False},
        raw_observation={"nearby_blocks": {"torch": 1}},
    )

    result = evaluate_success(success, snapshot)

    assert result.passed is True


def test_evaluate_success_reports_missing_snapshot_path():
    success = {
        "all": [
            {
                "predicate": "snapshot_path_compare",
                "path": "raw_observation.nearby_blocks.torch",
                "operator": ">=",
                "value": 1,
            }
        ]
    }

    result = evaluate_success(success, ObservationSnapshot())

    assert result.passed is False
    assert result.failures == ("snapshot_path_compare(raw_observation.nearby_blocks.torch >= 1)",)

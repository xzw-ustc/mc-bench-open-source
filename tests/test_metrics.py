from mcbench.metrics import (
    chain_metrics,
    evolution_transfer_gain,
    graph_aligned_transfer_gain,
    retention_score,
    self_evolution_gain_decomposition,
    transfer_measurement_regime,
    verified_milestone_progress,
)
from mcbench.reporting import StageReport
import pytest


def test_chain_metrics_reports_tsr_wgp_and_efficiency():
    stages = (
        StageReport(
            task_id="collect_log",
            status="passed",
            steps=3,
            failures=(),
            diagnostics={
                "graph_paths": {
                    "hard_prerequisite_path": [
                        {"source": "environment:spawned_world", "relation": "requires", "target": "collect_log", "count": 1}
                    ],
                    "produced_resource_path": [
                        {"source": "collect_log", "relation": "produces", "target": "item:oak_log", "count": 1}
                    ],
                    "abstract_ability_path": [
                        {"source": "collect_log", "relation": "abstracts_to", "target": "task_group:obtain_wood"}
                    ],
                }
            },
        ),
        StageReport(
            task_id="craft_planks",
            status="timeout",
            steps=5,
            failures=("inventory_at_least(oak_planks >= 4)",),
            diagnostics={
                "graph_paths": {
                    "hard_prerequisite_path": [
                        {"source": "item:oak_log", "relation": "requires", "target": "craft_planks", "count": 1}
                    ],
                    "produced_resource_path": [
                        {"source": "craft_planks", "relation": "produces", "target": "item:oak_planks", "count": 4}
                    ],
                }
            },
        ),
    )
    metrics = chain_metrics(
        stages,
        {
            "planned_stage_count": 2,
            "planned_step_budget": 20,
            "planned_execution_edges": 4,
            "planned_execution_edge_weight": 7,
        },
    )

    assert metrics["task_success_rate"] == 0.5
    assert metrics["graph_progress"]["execution_edges_completed"] == 2
    assert metrics["graph_progress"]["execution_edge_weight_completed"] == 2
    assert metrics["weighted_graph_progress"] == 2 / 7
    assert metrics["efficiency"]["total_steps"] == 8
    assert metrics["efficiency"]["budget_used_ratio"] == 0.4


def test_evolution_transfer_gain_reports_absolute_and_normalized_gain():
    metrics = evolution_transfer_gain(baseline_success_rate=0.25, evolved_success_rate=0.55)

    assert metrics["absolute_gain"] == pytest.approx(0.3)
    assert metrics["normalized_gain"] == pytest.approx(0.4)


def test_retention_score_reports_backward_transfer():
    metrics = retention_score(pre_success_rate=0.8, post_success_rate=0.6)

    assert metrics["backward_transfer"] == pytest.approx(-0.2)
    assert metrics["retention_ratio"] == pytest.approx(0.75)


def test_retention_ratio_is_not_estimable_without_a_preexisting_ability():
    metrics = retention_score(pre_success_rate=0.0, post_success_rate=0.0)

    assert metrics["backward_transfer"] == pytest.approx(0.0)
    assert metrics["retention_ratio"] is None


def test_normalized_etg_is_not_estimable_after_saturated_baseline():
    metrics = evolution_transfer_gain(baseline_success_rate=1.0, evolved_success_rate=1.0)

    assert metrics["absolute_gain"] == pytest.approx(0.0)
    assert metrics["normalized_gain"] is None


def test_graph_aligned_transfer_gain_removes_generic_and_order_controls():
    metrics = graph_aligned_transfer_gain(
        no_prior_success_rate=0.2,
        related_success_rate=0.7,
        unrelated_success_rate=0.3,
        shuffled_success_rate=0.4,
    )

    assert metrics["related_delta"] == pytest.approx(0.5)
    assert metrics["unrelated_delta"] == pytest.approx(0.1)
    assert metrics["shuffled_delta"] == pytest.approx(0.2)
    assert metrics["matched_control_delta"] == pytest.approx(0.15)
    assert metrics["graph_aligned_transfer_gain"] == pytest.approx(0.35)


def test_self_evolution_decomposition_distinguishes_gain_from_specificity():
    metrics = self_evolution_gain_decomposition(0.6, 0.5, 0.1, 0.1)

    assert metrics["actual_gain"] == pytest.approx(-0.1)
    assert metrics["specificity_gain"] == pytest.approx(0.4)
    assert metrics["joint_positive"] is False


def test_graph_aligned_gain_is_independent_of_no_prior_baseline():
    low_baseline = graph_aligned_transfer_gain(0.1, 0.6, 0.2, 0.4)
    high_baseline = graph_aligned_transfer_gain(0.9, 0.6, 0.2, 0.4)

    assert low_baseline["graph_aligned_transfer_gain"] == pytest.approx(0.3)
    assert high_baseline["graph_aligned_transfer_gain"] == pytest.approx(0.3)


def test_transfer_measurement_regime_marks_all_zero_scores_as_floor_limited():
    diagnostic = transfer_measurement_regime(0.0, 0.0, 0.0, 0.0)

    assert diagnostic["regime"] == "floor_limited"
    assert diagnostic["all_at_floor"] is True
    assert diagnostic["score_span"] == pytest.approx(0.0)


def test_transfer_measurement_regime_marks_interior_scores_as_interpretable():
    diagnostic = transfer_measurement_regime(0.2, 0.7, 0.3, 0.4)

    assert diagnostic["regime"] == "interior"
    assert diagnostic["all_at_floor"] is False
    assert diagnostic["all_at_ceiling"] is False
    assert diagnostic["score_span"] == pytest.approx(0.5)


def test_verified_milestone_progress_credits_only_new_observed_execution_states():
    stage = StageReport(
        task_id="craft_planks",
        status="timeout",
        steps=20,
        failures=("inventory_at_least(oak_planks >= 4)",),
        diagnostics={
            "start_snapshot": {"inventory": {}},
            "final_snapshot": {"inventory": {"oak_log": 1}},
            "graph_paths": {
                "hard_prerequisite_path": [
                    {"source": "item:oak_log", "relation": "requires", "target": "craft_planks", "count": 1}
                ],
                "produced_resource_path": [
                    {"source": "craft_planks", "relation": "produces", "target": "item:oak_planks", "count": 4}
                ],
            },
        },
    )

    progress = verified_milestone_progress((stage,))

    assert progress["completed_count"] == 1
    assert progress["eligible_count"] == 2
    assert progress["progress"] == pytest.approx(0.5)
    assert chain_metrics((stage,))["verified_milestone_progress"] == pytest.approx(0.5)


def test_verified_milestone_progress_does_not_credit_initial_profile_items():
    stage = StageReport(
        task_id="craft_planks",
        status="timeout",
        steps=1,
        failures=(),
        diagnostics={
            "start_snapshot": {"inventory": {"oak_log": 1}},
            "final_snapshot": {"inventory": {"oak_log": 1}},
            "graph_paths": {
                "hard_prerequisite_path": [
                    {"source": "item:oak_log", "relation": "requires", "target": "craft_planks", "count": 1}
                ]
            },
        },
    )

    progress = verified_milestone_progress((stage,))

    assert progress["eligible_count"] == 0
    assert progress["completed_count"] == 0
    assert progress["progress"] == pytest.approx(0.0)

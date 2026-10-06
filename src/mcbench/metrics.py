from __future__ import annotations

from typing import Any, Mapping, Sequence


EXECUTION_GRAPH_PATHS = (
    "hard_prerequisite_path",
    "produced_resource_path",
    "consumed_resource_path",
)


def chain_metrics(
    stages: Sequence[Any],
    metadata: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    metadata = metadata or {}
    stage_count = int(metadata.get("planned_stage_count") or len(stages))
    passed_stages = sum(1 for stage in stages if getattr(stage, "status", None) == "passed")
    total_steps = sum(int(getattr(stage, "steps", 0) or 0) for stage in stages)
    planned_step_budget = int(metadata.get("planned_step_budget") or 0)
    if planned_step_budget <= 0:
        planned_step_budget = total_steps

    planned_graph = _graph_totals_from_metadata(metadata)
    observed_graph = _graph_totals_from_passed_stages(stages)
    milestone_progress = verified_milestone_progress(stages)

    task_success_rate = passed_stages / stage_count if stage_count else 0.0
    weighted_graph_progress = (
        observed_graph["weight"] / planned_graph["weight"]
        if planned_graph["weight"]
        else task_success_rate
    )

    return {
        "stage_count": stage_count,
        "passed_stages": passed_stages,
        "completion_rate": task_success_rate,
        "task_success_rate": task_success_rate,
        "total_steps": total_steps,
        "evolution_score": task_success_rate,
        "weighted_graph_progress": weighted_graph_progress,
        "verified_milestone_progress": milestone_progress["progress"],
        "milestone_progress": milestone_progress,
        "graph_progress": {
            "execution_edges_completed": observed_graph["edges"],
            "execution_edges_total": planned_graph["edges"],
            "execution_edge_weight_completed": observed_graph["weight"],
            "execution_edge_weight_total": planned_graph["weight"],
            "weighted_graph_progress": weighted_graph_progress,
        },
        "efficiency": {
            "total_steps": total_steps,
            "planned_step_budget": planned_step_budget,
            "budget_used_ratio": total_steps / planned_step_budget if planned_step_budget else 0.0,
            "steps_per_passed_stage": total_steps / passed_stages if passed_stages else None,
            "deaths": _death_count(stages),
            "recovery_events": _recovery_event_count(stages),
            "resource_waste_events": _resource_waste_event_count(stages),
        },
    }


def compiled_chain_metric_metadata(compiled_chain: Any) -> Mapping[str, Any]:
    planned_graph = _graph_totals_from_compiled_stages(getattr(compiled_chain, "stages", ()))
    stages = tuple(getattr(compiled_chain, "stages", ()))
    return {
        "planned_stage_count": len(stages),
        "planned_task_ids": tuple(stage.task.id for stage in stages),
        "planned_step_budget": sum(stage.task.max_steps for stage in stages),
        "planned_execution_edges": planned_graph["edges"],
        "planned_execution_edge_weight": planned_graph["weight"],
    }


def evolution_transfer_gain(
    baseline_success_rate: float,
    evolved_success_rate: float,
) -> Mapping[str, float | None]:
    absolute_gain = evolved_success_rate - baseline_success_rate
    remaining_headroom = max(1.0 - baseline_success_rate, 0.0)
    normalized_gain = absolute_gain / remaining_headroom if remaining_headroom else None
    return {
        "baseline_success_rate": baseline_success_rate,
        "evolved_success_rate": evolved_success_rate,
        "absolute_gain": absolute_gain,
        "normalized_gain": normalized_gain,
    }


def graph_aligned_transfer_gain(
    no_prior_success_rate: float,
    related_success_rate: float,
    unrelated_success_rate: float,
    shuffled_success_rate: float,
) -> Mapping[str, float]:
    """Measure target-transfer specificity relative to matched controls.

    This contrast is not an improvement score: the no-prior baseline cancels
    algebraically. Use ``self_evolution_gain_decomposition`` for claims about
    beneficial capability acquisition.
    """

    decomposition = self_evolution_gain_decomposition(
        no_prior_success_rate,
        related_success_rate,
        unrelated_success_rate,
        shuffled_success_rate,
    )
    related_delta = decomposition["actual_gain"]
    unrelated_delta = unrelated_success_rate - no_prior_success_rate
    shuffled_delta = shuffled_success_rate - no_prior_success_rate
    matched_control_delta = 0.5 * (unrelated_delta + shuffled_delta)
    return {
        "no_prior_success_rate": no_prior_success_rate,
        "related_success_rate": related_success_rate,
        "unrelated_success_rate": unrelated_success_rate,
        "shuffled_success_rate": shuffled_success_rate,
        "related_delta": related_delta,
        "unrelated_delta": unrelated_delta,
        "shuffled_delta": shuffled_delta,
        "matched_control_delta": matched_control_delta,
        "graph_aligned_transfer_gain": decomposition["specificity_gain"],
    }


def self_evolution_gain_decomposition(
    no_prior_score: float,
    related_score: float,
    unrelated_score: float,
    shuffled_score: float,
) -> Mapping[str, float | bool]:
    """Separate beneficial improvement from graph-related specificity.

    ``actual_gain`` asks whether related experience improves over no prior.
    ``specificity_gain`` asks whether it beats matched unrelated/shuffled
    controls. A beneficial claim requires both contrasts to be positive;
    inference across seeds must additionally establish uncertainty.
    """

    actual_gain = related_score - no_prior_score
    specificity_gain = related_score - 0.5 * (unrelated_score + shuffled_score)
    return {
        "actual_gain": actual_gain,
        "specificity_gain": specificity_gain,
        "joint_positive": actual_gain > 0.0 and specificity_gain > 0.0,
    }


def transfer_measurement_regime(
    no_prior_score: float,
    related_score: float,
    unrelated_score: float,
    shuffled_score: float,
) -> Mapping[str, Any]:
    """Describe whether a four-role transfer contrast is floor or ceiling limited.

    This is a reporting diagnostic, not a replacement for GATG. In particular,
    a four-way all-zero target result says that strict endpoint transfer was not
    observed at the selected probe resolution; it does not establish that an
    agent has no internal adaptation whatsoever.
    """

    scores = {
        "no_prior": float(no_prior_score),
        "related": float(related_score),
        "unrelated": float(unrelated_score),
        "shuffled": float(shuffled_score),
    }
    minimum = min(scores.values())
    maximum = max(scores.values())
    epsilon = 1e-12
    all_at_floor = maximum <= epsilon
    all_at_ceiling = minimum >= 1.0 - epsilon
    if all_at_floor:
        regime = "floor_limited"
        interpretation = "All target roles are at zero on this metric; report the contrast, but do not interpret a zero gain as evidence against internal adaptation."
    elif all_at_ceiling:
        regime = "ceiling_limited"
        interpretation = "All target roles are saturated on this metric; report the contrast, but do not interpret a zero gain as evidence against transfer."
    else:
        regime = "interior"
        interpretation = "At least one target score lies away from the metric floor and ceiling; paired differences are interpretable at this metric resolution."
    return {
        "regime": regime,
        "score_min": minimum,
        "score_max": maximum,
        "score_span": maximum - minimum,
        "all_at_floor": all_at_floor,
        "all_at_ceiling": all_at_ceiling,
        "interpretation": interpretation,
    }


def verified_milestone_progress(stages: Sequence[Any]) -> Mapping[str, Any]:
    """Report observation-grounded execution-state acquisition without relaxing pass/fail.

    A milestone is an item/tool state referenced by a compiled execution edge.
    It receives credit only when it was absent from the first observed stage
    snapshot and later reaches the catalog edge's required count. This makes the
    diagnostic useful when a strict chain stops before a terminal verifier passes
    while keeping TSR and WGP unchanged.
    """

    milestones = _execution_state_milestones(stages)
    if not milestones:
        return {
            "progress": 0.0,
            "completed_count": 0,
            "eligible_count": 0,
            "initially_satisfied_count": 0,
            "milestones": (),
        }

    snapshots = _stage_observation_snapshots(stages)
    initial_snapshot = snapshots[0] if snapshots else {}
    rows = []
    for state_id, required_count in sorted(milestones.items()):
        initial_count = _state_observed_count(state_id, initial_snapshot)
        maximum_count = max(
            (_state_observed_count(state_id, snapshot) for snapshot in snapshots),
            default=initial_count,
        )
        initially_satisfied = initial_count >= required_count
        completed = not initially_satisfied and maximum_count >= required_count
        rows.append(
            {
                "state_id": state_id,
                "required_count": required_count,
                "initial_count": initial_count,
                "maximum_observed_count": maximum_count,
                "initially_satisfied": initially_satisfied,
                "completed": completed,
            }
        )

    eligible = [row for row in rows if not row["initially_satisfied"]]
    completed = [row for row in eligible if row["completed"]]
    return {
        "progress": len(completed) / len(eligible) if eligible else 0.0,
        "completed_count": len(completed),
        "eligible_count": len(eligible),
        "initially_satisfied_count": len(rows) - len(eligible),
        "milestones": tuple(rows),
    }


def retention_score(
    pre_success_rate: float,
    post_success_rate: float,
) -> Mapping[str, float | None]:
    return {
        "pre_success_rate": pre_success_rate,
        "post_success_rate": post_success_rate,
        "backward_transfer": post_success_rate - pre_success_rate,
        # No acquired pre-curriculum ability means there is nothing to retain.
        "retention_ratio": post_success_rate / pre_success_rate if pre_success_rate > 0 else None,
    }


def _execution_state_milestones(stages: Sequence[Any]) -> Mapping[str, int]:
    milestones: dict[str, int] = {}
    for stage in stages:
        diagnostics = getattr(stage, "diagnostics", {}) or {}
        graph_paths = diagnostics.get("graph_paths", {})
        if not isinstance(graph_paths, Mapping):
            continue
        for path_name in EXECUTION_GRAPH_PATHS:
            for edge in graph_paths.get(path_name, ()):
                if not isinstance(edge, Mapping):
                    continue
                count = _positive_int(edge.get("count", 1))
                for value in (edge.get("source"), edge.get("target")):
                    state_id = str(value or "")
                    if not state_id.startswith(("item:", "tool:")):
                        continue
                    milestones[state_id] = max(milestones.get(state_id, 0), count)
    return milestones


def _stage_observation_snapshots(stages: Sequence[Any]) -> tuple[Mapping[str, Any], ...]:
    snapshots: list[Mapping[str, Any]] = []
    for stage in stages:
        diagnostics = getattr(stage, "diagnostics", {}) or {}
        for key in ("start_snapshot", "final_snapshot"):
            snapshot = diagnostics.get(key, {})
            if isinstance(snapshot, Mapping):
                snapshots.append(snapshot)
    return tuple(snapshots)


def _state_observed_count(state_id: str, snapshot: Mapping[str, Any]) -> int:
    _, item_id = state_id.split(":", 1)
    inventory = snapshot.get("inventory", {})
    if isinstance(inventory, Mapping):
        inventory_count = _positive_int(inventory.get(item_id, 0))
        if inventory_count:
            return inventory_count
    if not state_id.startswith("tool:"):
        return 0
    equipped = snapshot.get("equipped", {})
    if not isinstance(equipped, Mapping):
        return 0
    return int(any(_equipped_item_id(value) == item_id for value in equipped.values()))


def _equipped_item_id(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("type", value.get("name", value.get("id", "")))
    return str(value or "").removeprefix("minecraft:")


def _positive_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _graph_totals_from_metadata(metadata: Mapping[str, Any]) -> Mapping[str, int]:
    edges = int(metadata.get("planned_execution_edges") or 0)
    weight = int(metadata.get("planned_execution_edge_weight") or 0)
    return {"edges": edges, "weight": weight}


def _graph_totals_from_compiled_stages(stages: Sequence[Any]) -> Mapping[str, int]:
    edges = 0
    weight = 0
    for stage in stages:
        for path_name in EXECUTION_GRAPH_PATHS:
            for edge in getattr(stage, path_name, ()):
                edges += 1
                weight += int(edge.get("count", 1))
    return {"edges": edges, "weight": weight}


def _graph_totals_from_passed_stages(stages: Sequence[Any]) -> Mapping[str, int]:
    edges = 0
    weight = 0
    for stage in stages:
        if getattr(stage, "status", None) != "passed":
            continue
        diagnostics = getattr(stage, "diagnostics", {}) or {}
        graph_paths = diagnostics.get("graph_paths", {})
        for path_name in EXECUTION_GRAPH_PATHS:
            for edge in graph_paths.get(path_name, ()):
                edges += 1
                weight += int(edge.get("count", 1))
    return {"edges": edges, "weight": weight}


def _death_count(stages: Sequence[Any]) -> int:
    return sum(1 for stage in stages if _stage_observed_dead(stage))


def _stage_observed_dead(stage: Any) -> bool:
    diagnostics = getattr(stage, "diagnostics", {}) or {}
    final_snapshot = diagnostics.get("final_snapshot", {})
    player_stats = final_snapshot.get("player_stats", {})
    is_alive = player_stats.get("is_alive")
    if is_alive is not None:
        return not bool(is_alive)
    life = player_stats.get("life", player_stats.get("health"))
    return isinstance(life, (int, float)) and life <= 0


def _recovery_event_count(stages: Sequence[Any]) -> int:
    return sum(_count_diagnostic_events(stage, "recovery_events") for stage in stages)


def _resource_waste_event_count(stages: Sequence[Any]) -> int:
    return sum(_count_diagnostic_events(stage, "resource_waste_events") for stage in stages)


def _count_diagnostic_events(stage: Any, key: str) -> int:
    diagnostics = getattr(stage, "diagnostics", {}) or {}
    value = diagnostics.get(key, ())
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, int):
        return value
    return 0

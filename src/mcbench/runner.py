from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy
from typing import Any, Mapping, Protocol

from .chains import CompiledChain, CompiledStage
from .metrics import compiled_chain_metric_metadata
from .reporting import ChainRunReport, StageReport
from .verification import ObservationSnapshot, evaluate_success


@dataclass(frozen=True)
class EnvironmentStep:
    snapshot: ObservationSnapshot
    done: bool = False
    info: Mapping[str, Any] = field(default_factory=dict)


class EnvironmentAdapter(Protocol):
    def reset(self, profile: str) -> ObservationSnapshot:
        ...

    def observe(self) -> ObservationSnapshot:
        ...

    def step(self, action: Mapping[str, Any]) -> EnvironmentStep:
        ...

    def close(self) -> None:
        ...


class AgentAdapter(Protocol):
    def reset(self, chain_context: CompiledChain) -> None:
        ...

    def act(
        self,
        observation: ObservationSnapshot,
        instruction: str,
        stage_context: CompiledStage,
    ) -> Mapping[str, Any]:
        ...


def _run_stage(
    stage: CompiledStage,
    environment: EnvironmentAdapter,
    agent: AgentAdapter,
    *,
    max_steps: int | None = None,
) -> StageReport:
    start_snapshot = environment.observe()
    snapshot = _augment_stage_snapshot(stage, start_snapshot, start_snapshot)
    latest_result = evaluate_success(stage.task.success, snapshot)
    if latest_result.passed:
        return StageReport(
            task_id=stage.task.id,
            status="passed",
            steps=0,
            failures=(),
            diagnostics=_task_stage_diagnostics(stage, snapshot, start_snapshot, status="passed"),
        )

    step_limit = stage.task.max_steps if max_steps is None else min(stage.task.max_steps, max(0, max_steps))
    for step_count in range(1, step_limit + 1):
        action = agent.act(snapshot, stage.task.instruction, stage)
        transition_callback = getattr(agent, "on_transition", None)
        record_transition = bool(getattr(agent, "transition_recording_enabled", False)) and callable(transition_callback)
        if record_transition:
            before_action = deepcopy({key: snapshot.raw_observation[key] for key in
                                      ("inventory", "location_stats", "player_pos") if key in snapshot.raw_observation})
            requested_action = deepcopy(action)
        step = environment.step(action)
        if record_transition:
            # Pass raw agent observations before hidden verifier augmentation.
            transition_callback(instruction=stage.task.instruction, stage_step=step_count - 1,
                                action=requested_action, before=before_action,
                                after=deepcopy({key: step.snapshot.raw_observation[key] for key in
                                                ("inventory", "location_stats", "player_pos")
                                                if key in step.snapshot.raw_observation}))
        snapshot = _augment_stage_snapshot(stage, step.snapshot, start_snapshot)
        latest_result = evaluate_success(stage.task.success, snapshot)
        if latest_result.passed:
            return StageReport(
                task_id=stage.task.id,
                status="passed",
                steps=step_count,
                failures=(),
                diagnostics=_task_stage_diagnostics(stage, snapshot, start_snapshot, status="passed"),
            )
        if _stage_failure_condition_passed(stage, snapshot, start_snapshot):
            return StageReport(
                task_id=stage.task.id,
                status="failed",
                steps=step_count,
                failures=latest_result.failures,
                diagnostics=_task_stage_diagnostics(stage, snapshot, start_snapshot, status="failed"),
            )
        if step.done:
            return StageReport(
                task_id=stage.task.id,
                status="terminated",
                steps=step_count,
                failures=latest_result.failures,
                diagnostics=_task_stage_diagnostics(stage, snapshot, start_snapshot, status="terminated"),
            )

    return StageReport(
        task_id=stage.task.id,
        status="timeout" if step_limit == stage.task.max_steps else "budget_exhausted",
        steps=step_limit,
        failures=latest_result.failures,
        diagnostics=_task_stage_diagnostics(
            stage,
            snapshot,
            start_snapshot,
            status="timeout" if step_limit == stage.task.max_steps else "budget_exhausted",
        ),
    )


def _stage_diagnostics(success_spec: Mapping[str, Any], snapshot: ObservationSnapshot) -> Mapping[str, Any]:
    return {
        "predicate_actuals": _predicate_actuals(success_spec, snapshot),
        "final_snapshot": snapshot_diagnostics(snapshot),
    }


def _task_stage_diagnostics(
    stage: CompiledStage,
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot | None = None,
    *,
    status: str | None = None,
) -> Mapping[str, Any]:
    diagnostics = dict(_stage_diagnostics(stage.task.success, snapshot))
    if start_snapshot is not None:
        diagnostics["start_snapshot"] = snapshot_diagnostics(start_snapshot)
    if stage.task.observation_sources:
        diagnostics["observation_sources"] = tuple(stage.task.observation_sources)
        diagnostics["observation_evidence"] = _observation_evidence(stage.task.observation_sources, snapshot)
    if stage.mission_events:
        diagnostics["mission_events"] = tuple(
            event.to_dict() if hasattr(event, "to_dict") else event for event in stage.mission_events
        )
        diagnostics["mission_event_evidence"] = _mission_event_evidence(stage, snapshot, start_snapshot)
        terminal_evidence = _mission_terminal_evidence(stage, snapshot, start_snapshot)
        if terminal_evidence:
            diagnostics["mission_terminal_evidence"] = terminal_evidence
    graph_paths = _stage_graph_paths(stage)
    if graph_paths:
        diagnostics["graph_paths"] = graph_paths
    resource_waste_events = _resource_waste_events(stage, start_snapshot, snapshot, status=status)
    if resource_waste_events:
        diagnostics["resource_waste_events"] = resource_waste_events
    return diagnostics


def _resource_waste_events(
    stage: CompiledStage,
    start_snapshot: ObservationSnapshot | None,
    final_snapshot: ObservationSnapshot,
    *,
    status: str | None,
) -> list[Mapping[str, Any]]:
    if status in (None, "passed") or start_snapshot is None:
        return []
    events = []
    for edge in getattr(stage, "consumed_resource_path", ()):
        state_id = str(edge.get("target", ""))
        if not state_id.startswith("item:"):
            continue
        item_id = state_id.split(":", 1)[1]
        start_count = _numeric_value(start_snapshot.inventory.get(item_id, 0))
        final_count = _numeric_value(final_snapshot.inventory.get(item_id, 0))
        delta = start_count - final_count
        if delta <= 0:
            continue
        events.append(
            {
                "type": "consumed_resource_without_stage_success",
                "task_id": stage.task.id,
                "status": status,
                "state": state_id,
                "item": item_id,
                "start_count": _jsonable(start_count),
                "final_count": _jsonable(final_count),
                "delta": _jsonable(delta),
                "expected_count": _jsonable(edge.get("count", 1)),
            }
        )
    return events


def _stage_graph_paths(stage: CompiledStage) -> Mapping[str, Any]:
    payload = {
        "hard_prerequisite_path": tuple(getattr(stage, "hard_prerequisite_path", ())),
        "soft_enabled_path": tuple(getattr(stage, "soft_enabled_path", ())),
        "consumed_resource_path": tuple(getattr(stage, "consumed_resource_path", ())),
        "produced_resource_path": tuple(getattr(stage, "produced_resource_path", ())),
        "abstract_ability_path": tuple(getattr(stage, "abstract_ability_path", ())),
    }
    return {key: value for key, value in payload.items() if value}


def snapshot_diagnostics(snapshot: ObservationSnapshot) -> Mapping[str, Any]:
    inventory = _jsonable_mapping(snapshot.inventory)
    nonzero_inventory = {
        key: value
        for key, value in inventory.items()
        if _numeric_value(value) != 0
    }
    return {
        "inventory_observed": "inventory" in snapshot.raw_observation or "inventory" in snapshot.info,
        "inventory": inventory,
        "inventory_nonzero": nonzero_inventory,
        "flags": sorted(snapshot.flags),
        "counters": _jsonable_mapping(snapshot.counters),
        "player_stats": _jsonable_mapping(snapshot.player_stats),
        "equipped": _jsonable_mapping(snapshot.equipped),
        "observation_values": _selected_observation_values(snapshot),
        "raw_observation_keys": sorted(snapshot.raw_observation.keys()),
        "info_keys": sorted(snapshot.info.keys()),
    }


def _augment_stage_snapshot(
    stage: CompiledStage,
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
) -> ObservationSnapshot:
    augmented = snapshot
    for event in stage.mission_events:
        if _evaluate_mission_event(event, augmented, start_snapshot)["passed"]:
            augmented = _apply_mission_event_effect(event, augmented)

    flags = set(augmented.flags)
    if stage.task.id == "survive_first_night" and _survived_night_interval(
        augmented,
        start_snapshot,
        target_ticks=stage.task.max_steps,
    ):
        flags.add("night_survived")
    if flags == augmented.flags:
        return augmented
    return ObservationSnapshot(
        inventory=augmented.inventory,
        flags=flags,
        player_stats=augmented.player_stats,
        counters=augmented.counters,
        equipped=augmented.equipped,
        raw_observation=augmented.raw_observation,
        info=augmented.info,
    )


def _survived_night_interval(
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
    *,
    target_ticks: int,
) -> bool:
    if not _is_alive(snapshot):
        return False
    current_total = _numeric_value(snapshot.player_stats.get("total_time"))
    start_total = _numeric_value(start_snapshot.player_stats.get("total_time"))
    if current_total > 0 and start_total > 0:
        return current_total - start_total >= target_ticks

    current_world = _numeric_value(snapshot.player_stats.get("world_time"))
    start_world = _numeric_value(start_snapshot.player_stats.get("world_time"))
    if current_world <= 0 and start_world <= 0:
        return False
    elapsed = (current_world - start_world) % 24000
    return elapsed >= target_ticks and _is_night_time(current_world)


def _is_alive(snapshot: ObservationSnapshot) -> bool:
    is_alive = snapshot.player_stats.get("is_alive")
    if is_alive is not None:
        return bool(is_alive)
    life = snapshot.player_stats.get("life", snapshot.player_stats.get("health"))
    return life is None or _numeric_value(life) > 0


def _is_night_time(world_time: float) -> bool:
    time_of_day = world_time % 24000
    return 12000 <= time_of_day <= 24000


def _mission_event_evidence(
    stage: CompiledStage,
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot | None,
) -> list[Mapping[str, Any]]:
    return [_evaluate_mission_event(event, snapshot, start_snapshot or snapshot) for event in stage.mission_events]


def _mission_terminal_evidence(
    stage: CompiledStage,
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot | None,
) -> list[Mapping[str, Any]]:
    return [
        evidence
        for event in stage.mission_events
        if (evidence := _evaluate_mission_terminal(event, snapshot, start_snapshot or snapshot)) is not None
    ]


def _stage_failure_condition_passed(
    stage: CompiledStage,
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
) -> bool:
    return any(
        bool(evidence.get("failure_condition", {}).get("passed"))
        for evidence in _mission_terminal_evidence(stage, snapshot, start_snapshot)
    )


def _evaluate_mission_event(
    event: Any,
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
) -> Mapping[str, Any]:
    event_payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    trigger_result = _evaluate_event_trigger(event_payload.get("trigger", {}), snapshot, start_snapshot)
    return {
        "id": event_payload.get("id"),
        "task_id": event_payload.get("task_id"),
        "produced_state": event_payload.get("produced_state"),
        "implementation_status": event_payload.get("implementation_status"),
        "passed": trigger_result["passed"],
        "trigger": trigger_result,
        "snapshot_effect": event_payload.get("snapshot_effect", {}),
    }


def _evaluate_mission_terminal(
    event: Any,
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
) -> Mapping[str, Any] | None:
    event_payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    terminal_condition = event_payload.get("terminal_condition")
    failure_condition = event_payload.get("failure_condition")
    if terminal_condition is None and failure_condition is None:
        return None
    payload = {
        "id": event_payload.get("id"),
        "task_id": event_payload.get("task_id"),
        "produced_state": event_payload.get("produced_state"),
        "implementation_status": event_payload.get("implementation_status"),
    }
    if terminal_condition is not None:
        payload["terminal_condition"] = _evaluate_event_trigger(
            _materialize_condition(terminal_condition, event_payload.get("trigger", {})),
            snapshot,
            start_snapshot,
        )
    if failure_condition is not None:
        payload["failure_condition"] = _evaluate_event_trigger(
            _materialize_condition(failure_condition, event_payload.get("trigger", {})),
            snapshot,
            start_snapshot,
        )
    return payload


def _materialize_condition(condition: Mapping[str, Any], trigger: Mapping[str, Any]) -> Mapping[str, Any]:
    if condition.get("same_as") == "trigger":
        return trigger
    return condition


def _evaluate_event_trigger(
    trigger: Mapping[str, Any],
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
) -> Mapping[str, Any]:
    if "all" in trigger:
        children = [_evaluate_event_trigger(child, snapshot, start_snapshot) for child in trigger["all"]]
        return {"operator": "all", "passed": bool(all(child["passed"] for child in children)), "children": children}
    if "any_of" in trigger:
        children = [_evaluate_event_trigger(child, snapshot, start_snapshot) for child in trigger["any_of"]]
        return {"operator": "any_of", "passed": bool(any(child["passed"] for child in children)), "children": children}

    operator = trigger.get("operator")
    if operator == "elapsed_at_least":
        return _evaluate_elapsed_at_least(trigger, snapshot, start_snapshot)
    if operator == "time_of_day_between":
        return _evaluate_time_of_day_between(trigger, snapshot, start_snapshot)
    return _evaluate_path_comparison(trigger, snapshot, start_snapshot)


def _evaluate_path_comparison(
    trigger: Mapping[str, Any],
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
) -> Mapping[str, Any]:
    path = trigger.get("path")
    operator = trigger.get("operator")
    expected = trigger.get("value")
    found, actual = _resolve_context_path(snapshot, start_snapshot, path) if isinstance(path, str) else (False, None)
    passed = False
    if found:
        passed = _compare_values(actual, operator, expected)
    return {
        "path": path,
        "operator": operator,
        "expected": _jsonable(expected),
        "observed": found,
        "actual": _jsonable(actual) if found else None,
        "passed": bool(passed),
    }


def _evaluate_elapsed_at_least(
    trigger: Mapping[str, Any],
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
) -> Mapping[str, Any]:
    start_found, start_value = _resolve_context_path(snapshot, start_snapshot, trigger.get("start_path", ""))
    end_found, end_value = _resolve_context_path(snapshot, start_snapshot, trigger.get("end_path", ""))
    used_fallback = False
    if not (start_found and end_found):
        start_found, start_value = _resolve_context_path(
            snapshot,
            start_snapshot,
            trigger.get("fallback_start_path", ""),
        )
        end_found, end_value = _resolve_context_path(
            snapshot,
            start_snapshot,
            trigger.get("fallback_end_path", ""),
        )
        used_fallback = True
    elapsed = None
    passed = False
    if start_found and end_found:
        start_numeric = _numeric_value(start_value)
        end_numeric = _numeric_value(end_value)
        elapsed = (end_numeric - start_numeric) % 24000 if used_fallback else end_numeric - start_numeric
        passed = elapsed >= _numeric_value(trigger.get("value"))
    return {
        "operator": "elapsed_at_least",
        "expected": _jsonable(trigger.get("value")),
        "observed": bool(start_found and end_found),
        "actual": _jsonable(elapsed) if elapsed is not None else None,
        "used_fallback": used_fallback,
        "passed": bool(passed),
    }


def _evaluate_time_of_day_between(
    trigger: Mapping[str, Any],
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
) -> Mapping[str, Any]:
    path = trigger.get("path")
    found, actual = _resolve_context_path(snapshot, start_snapshot, path) if isinstance(path, str) else (False, None)
    time_of_day = _numeric_value(actual) % 24000 if found else None
    lower = _numeric_value(trigger.get("min"))
    upper = _numeric_value(trigger.get("max"))
    passed = bool(found and lower <= (time_of_day or 0) <= upper)
    return {
        "path": path,
        "operator": "time_of_day_between",
        "min": _jsonable(trigger.get("min")),
        "max": _jsonable(trigger.get("max")),
        "observed": found,
        "actual": _jsonable(time_of_day) if found else None,
        "passed": bool(passed),
    }


def _compare_values(actual: Any, operator: str | None, expected: Any) -> bool:
    if operator == "==":
        return bool(actual == expected)
    if operator in {">=", ">", "<=", "<"}:
        actual_numeric = _numeric_value(actual)
        expected_numeric = _numeric_value(expected)
        if operator == ">=":
            return bool(actual_numeric >= expected_numeric)
        if operator == ">":
            return bool(actual_numeric > expected_numeric)
        if operator == "<=":
            return bool(actual_numeric <= expected_numeric)
        if operator == "<":
            return bool(actual_numeric < expected_numeric)
    return False


def _apply_mission_event_effect(event: Any, snapshot: ObservationSnapshot) -> ObservationSnapshot:
    event_payload = event.to_dict() if hasattr(event, "to_dict") else dict(event)
    effect = event_payload.get("snapshot_effect") or {}
    flags = set(snapshot.flags)
    counters = dict(snapshot.counters)
    inventory = dict(snapshot.inventory)
    equipped = dict(snapshot.equipped)
    player_stats = dict(snapshot.player_stats)

    for flag in effect.get("flags_add", ()):
        flags.add(str(flag))
    for counter, value in (effect.get("counters_at_least") or {}).items():
        counters[counter] = max(_numeric_value(counters.get(counter, 0)), _numeric_value(value))
    for item, value in (effect.get("inventory_at_least") or {}).items():
        inventory[item] = max(_numeric_value(inventory.get(item, 0)), _numeric_value(value))
    for slot, item in (effect.get("equipped_set") or {}).items():
        equipped[slot] = item
    for stat, value in (effect.get("player_stats_at_least") or {}).items():
        player_stats[stat] = max(_numeric_value(player_stats.get(stat, 0)), _numeric_value(value))

    return ObservationSnapshot(
        inventory=inventory,
        flags=flags,
        player_stats=player_stats,
        counters=counters,
        equipped=equipped,
        raw_observation=snapshot.raw_observation,
        info=snapshot.info,
    )


def _selected_observation_values(snapshot: ObservationSnapshot) -> Mapping[str, Any]:
    selected_keys = (
        "line_of_sight",
        "nearby_blocks",
        "location_stats",
        "life_stats",
        "world_stats",
        "known_blocks",
        "kill_entity",
        "mine_block",
        "pickup",
    )
    values = {}
    for key in selected_keys:
        if key not in snapshot.raw_observation:
            continue
        value = snapshot.raw_observation[key]
        if key == "world_stats" and isinstance(value, Mapping):
            value = {
                stat_key: value[stat_key]
                for stat_key in (
                    "world_time",
                    "total_time",
                    "WorldTime",
                    "TotalTime",
                    "light_level",
                    "effective_light_level",
                    "sky_light_level",
                    "effective_sky_light_level",
                    "block_light_level",
                    "skylight_subtracted",
                    "sun_brightness",
                    "can_see_sky",
                    "is_alive",
                )
                if stat_key in value
            }
        values[key] = _jsonable(value)
    return values


def _predicate_actuals(success_spec: Mapping[str, Any], snapshot: ObservationSnapshot) -> list[Mapping[str, Any]]:
    return [_predicate_actual(predicate, snapshot) for predicate in success_spec.get("all", ())]


def _predicate_actual(predicate: Mapping[str, Any], snapshot: ObservationSnapshot) -> Mapping[str, Any]:
    name = predicate.get("predicate")
    payload = dict(predicate)
    if name == "inventory_at_least":
        item = predicate["item"]
        actual = snapshot.inventory.get(item, 0)
        payload["actual"] = _jsonable(actual)
        payload["passed"] = actual >= predicate["count"]
    elif name == "flag_is_true":
        flag = predicate["flag"]
        actual = flag in snapshot.flags
        payload["actual"] = actual
        payload["passed"] = actual
    elif name == "player_stat_at_least":
        stat = predicate["stat"]
        actual = snapshot.player_stats.get(stat, 0)
        payload["actual"] = _jsonable(actual)
        payload["passed"] = actual >= predicate["value"]
    elif name == "counter_at_least":
        counter = predicate["counter"]
        actual = snapshot.counters.get(counter, 0)
        payload["actual"] = _jsonable(actual)
        payload["passed"] = actual >= predicate["count"]
    elif name == "equipped_equals":
        slot = predicate["slot"]
        actual = snapshot.equipped.get(slot)
        payload["actual"] = _jsonable(actual)
        payload["passed"] = actual == predicate["item"]
    elif name == "snapshot_path_compare":
        found, actual = _resolve_snapshot_path(snapshot, predicate["path"])
        payload["observed"] = found
        payload["actual"] = _jsonable(actual) if found else None
        payload["passed"] = found and _compare_values(actual, predicate["operator"], predicate["value"])
    elif name == "any_of":
        options = [_predicate_actual(option, snapshot) for option in predicate.get("options", ())]
        payload["options"] = options
        payload["actual"] = any(option.get("passed") for option in options)
        payload["passed"] = payload["actual"]
    return payload


def _observation_evidence(
    observation_sources: tuple[Mapping[str, Any], ...],
    snapshot: ObservationSnapshot,
) -> list[Mapping[str, Any]]:
    evidence = []
    for source in observation_sources:
        path = source.get("path")
        payload = dict(source)
        if isinstance(path, str):
            found, value = _resolve_snapshot_path(snapshot, path)
            payload["observed"] = found
            payload["actual"] = _jsonable(value) if found else None
        evidence.append(payload)
    return evidence


def _resolve_snapshot_path(snapshot: ObservationSnapshot, path: str) -> tuple[bool, Any]:
    return _resolve_path(_snapshot_roots(snapshot), path)


def _resolve_context_path(
    snapshot: ObservationSnapshot,
    start_snapshot: ObservationSnapshot,
    path: str,
) -> tuple[bool, Any]:
    roots = _snapshot_roots(snapshot)
    roots["stage_start"] = _snapshot_roots(start_snapshot)
    return _resolve_path(roots, path)


def _snapshot_roots(snapshot: ObservationSnapshot) -> dict[str, Any]:
    return {
        "inventory": snapshot.inventory,
        "flags": snapshot.flags,
        "player_stats": snapshot.player_stats,
        "counters": snapshot.counters,
        "equipped": snapshot.equipped,
        "raw_observation": snapshot.raw_observation,
        "info": snapshot.info,
    }


def _resolve_path(roots: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    parts = path.split(".")
    if not parts or parts[0] not in roots:
        return False, None
    value: Any = roots[parts[0]]
    for part in parts[1:]:
        if isinstance(value, Mapping):
            if part not in value:
                return False, None
            value = value[part]
        elif isinstance(value, set):
            return (part in value), part if part in value else None
        else:
            return False, None
    return True, value


def _jsonable_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {str(key): _jsonable(value) for key, value in payload.items()}


def _jsonable(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, Mapping):
        return _jsonable_mapping(value)
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _numeric_value(value: Any) -> float:
    value = _jsonable(value)
    return float(value) if isinstance(value, (int, float)) else 0.0


def run_compiled_chain(
    compiled_chain: CompiledChain,
    environment: EnvironmentAdapter,
    agent: AgentAdapter,
    environment_profile: str | None = None,
    per_stage_profiles: bool = False,
    max_total_steps: int | None = None,
) -> ChainRunReport:
    current_profile = _initial_environment_profile(compiled_chain, environment_profile, per_stage_profiles)
    agent.reset(compiled_chain)
    environment.reset(current_profile)
    stage_reports = []
    remaining_steps = max_total_steps

    try:
        for stage in compiled_chain.stages:
            if remaining_steps is not None and remaining_steps <= 0:
                break
            if _should_reset_for_stage_profile(compiled_chain, per_stage_profiles, stage, current_profile):
                current_profile = stage.task.environment_profile
                environment.reset(current_profile)
            stage_report = _run_stage(stage, environment, agent, max_steps=remaining_steps)
            stage_reports.append(stage_report)
            _notify_stage_end(agent, stage, stage_report)
            if remaining_steps is not None:
                remaining_steps -= stage_report.steps
            if stage_report.status != "passed":
                break
    finally:
        environment.close()

    completed = len(stage_reports) == len(compiled_chain.stages) and all(
        stage.status == "passed" for stage in stage_reports
    )
    runtime_metadata = _agent_runtime_metadata(agent)
    if max_total_steps is not None:
        runtime_metadata = {
            **runtime_metadata,
            "interaction_budget_steps": max_total_steps,
            "interaction_steps": sum(report.steps for report in stage_reports),
            "interaction_budget_exhausted": remaining_steps == 0,
        }
    return ChainRunReport(
        chain_id=compiled_chain.chain.id,
        completed=completed,
        stages=tuple(stage_reports),
        metadata={**compiled_chain_metric_metadata(compiled_chain), **runtime_metadata},
    )


def _notify_stage_end(agent: AgentAdapter, stage: CompiledStage, report: StageReport) -> None:
    """Send standard episode feedback to agents that opt into online updates.

    The callback deliberately exposes no verifier predicates, graph edges, mission
    diagnostics, or environment configuration. Agents receive only the natural
    language instruction already used for action selection plus terminal outcome
    feedback that an interactive learner would normally observe.
    """
    callback = getattr(agent, "on_stage_end", None)
    if callable(callback):
        callback(stage, report)


def _agent_runtime_metadata(agent: AgentAdapter) -> Mapping[str, Any]:
    callback = getattr(agent, "runtime_metadata", None)
    metadata = callback() if callable(callback) else {}
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _initial_environment_profile(
    compiled_chain: CompiledChain,
    environment_profile: str | None,
    per_stage_profiles: bool,
) -> str:
    if _chain_uses_chain_profile(compiled_chain):
        return environment_profile or compiled_chain.chain.environment_profile
    if per_stage_profiles and compiled_chain.stages:
        return compiled_chain.stages[0].task.environment_profile
    return environment_profile or compiled_chain.chain.environment_profile


def _should_reset_for_stage_profile(
    compiled_chain: CompiledChain,
    per_stage_profiles: bool,
    stage: CompiledStage,
    current_profile: str,
) -> bool:
    if not per_stage_profiles or _chain_uses_chain_profile(compiled_chain):
        return False
    return stage.task.environment_profile != current_profile


def _chain_uses_chain_profile(compiled_chain: CompiledChain) -> bool:
    return getattr(compiled_chain.chain, "profile_policy", "task") == "chain"

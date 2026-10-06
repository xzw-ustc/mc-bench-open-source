from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from typing import Any, Mapping, Tuple

from .catalog import BenchmarkCatalog
from .graph import TaskStateGraph
from .schema import ChainSpec, MissionEventSpec, TaskSpec


class ChainValidationError(ValueError):
    """Raised when a chain cannot satisfy task prerequisites in order."""


@dataclass(frozen=True)
class CompiledStage:
    task: TaskSpec
    required_states: set[str]
    produced_states: set[str]
    enabled_states: set[str]
    consumed_states: set[str]
    required_state_counts: Mapping[str, int] = field(default_factory=dict)
    produced_state_counts: Mapping[str, int] = field(default_factory=dict)
    enabled_state_counts: Mapping[str, int] = field(default_factory=dict)
    consumed_state_counts: Mapping[str, int] = field(default_factory=dict)
    mission_events: Tuple[MissionEventSpec, ...] = ()
    hard_prerequisite_path: Tuple[Mapping[str, Any], ...] = ()
    soft_enabled_path: Tuple[Mapping[str, Any], ...] = ()
    consumed_resource_path: Tuple[Mapping[str, Any], ...] = ()
    produced_resource_path: Tuple[Mapping[str, Any], ...] = ()
    abstract_ability_path: Tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class CompiledChain:
    chain: ChainSpec
    stages: Tuple[CompiledStage, ...]
    available_states: set[str]
    available_state_counts: Mapping[str, int] = field(default_factory=dict)


def compile_chain(
    catalog: BenchmarkCatalog,
    chain_id: str,
    *,
    strict_quantities: bool = False,
) -> CompiledChain:
    try:
        chain = catalog.chains[chain_id]
    except KeyError as exc:
        raise ChainValidationError(f"Unknown chain: {chain_id}") from exc
    return compile_chain_spec(catalog, chain, strict_quantities=strict_quantities)


def compile_chain_spec(
    catalog: BenchmarkCatalog,
    chain: ChainSpec,
    *,
    strict_quantities: bool = False,
    allow_unmet_prerequisites: bool = False,
) -> CompiledChain:
    """Compile an official chain or a frozen evaluation-only chain specification.

    Evaluation overlays use this entry point to retain V1 task and graph
    semantics without adding calibration probes to the official chain catalog.
    """

    graph = TaskStateGraph.from_catalog(catalog)
    available_counts: defaultdict[str, int] = defaultdict(int)
    for state_id in chain.initial_states:
        available_counts[state_id] += 1
    compiled_stages = []

    for task_id in chain.task_ids:
        task = catalog.tasks[task_id]
        required_states = graph.required_states(task_id)
        produced_states = graph.produced_states(task_id)
        enabled_states = graph.enabled_states(task_id)
        consumed_states = graph.consumed_states(task_id)
        required_state_counts = graph.required_state_counts(task_id)
        produced_state_counts = graph.produced_state_counts(task_id)
        enabled_state_counts = graph.enabled_state_counts(task_id)
        consumed_state_counts = graph.consumed_state_counts(task_id)
        abstract_nodes = {task_id} | required_states | produced_states | enabled_states | consumed_states
        if strict_quantities and not allow_unmet_prerequisites:
            missing_required = _missing_counts(required_state_counts, available_counts)
            if missing_required:
                raise ChainValidationError(
                    f"Task {task_id} has unmet required states: {_format_missing_counts(missing_required)}"
                )
            missing_consumed = _missing_counts(consumed_state_counts, available_counts)
            if missing_consumed:
                raise ChainValidationError(
                    f"Task {task_id} consumes unavailable states: {_format_missing_counts(missing_consumed)}"
                )
        elif not allow_unmet_prerequisites:
            missing_required_states = required_states - set(available_counts)
            if missing_required_states:
                formatted = ", ".join(sorted(missing_required_states))
                raise ChainValidationError(f"Task {task_id} has unmet required states: {formatted}")
            missing_consumed_states = consumed_states - set(available_counts)
            if missing_consumed_states:
                formatted = ", ".join(sorted(missing_consumed_states))
                raise ChainValidationError(f"Task {task_id} consumes unavailable states: {formatted}")
        compiled_stages.append(
            CompiledStage(
                task=task,
                required_states=required_states,
                produced_states=produced_states,
                enabled_states=enabled_states,
                consumed_states=consumed_states,
                required_state_counts=required_state_counts,
                produced_state_counts=produced_state_counts,
                enabled_state_counts=enabled_state_counts,
                consumed_state_counts=consumed_state_counts,
                mission_events=tuple(
                    event for event in catalog.mission_events.values() if event.task_id == task_id
                ),
                hard_prerequisite_path=_state_to_task_paths(
                    required_states,
                    "requires",
                    task_id,
                    required_state_counts,
                ),
                soft_enabled_path=_state_to_task_paths(enabled_states, "enables", task_id, enabled_state_counts),
                consumed_resource_path=_task_to_state_paths(task_id, "consumes", consumed_states, consumed_state_counts),
                produced_resource_path=_task_to_state_paths(task_id, "produces", produced_states, produced_state_counts),
                abstract_ability_path=_abstract_paths(graph, abstract_nodes),
            )
        )
        for state_id, count in consumed_state_counts.items():
            available_counts[state_id] -= count if strict_quantities else min(count, available_counts[state_id])
            if available_counts[state_id] <= 0:
                available_counts.pop(state_id, None)
        for state_id, count in produced_state_counts.items():
            available_counts[state_id] += count

    return CompiledChain(
        chain=chain,
        stages=tuple(compiled_stages),
        available_states={state_id for state_id, count in available_counts.items() if count > 0},
        available_state_counts={state_id: count for state_id, count in sorted(available_counts.items()) if count > 0},
    )


def _state_to_task_paths(
    states: set[str],
    relation: str,
    task_id: str,
    counts: Mapping[str, int],
) -> Tuple[Mapping[str, Any], ...]:
    return tuple(
        {"source": state_id, "relation": relation, "target": task_id, "count": counts.get(state_id, 1)}
        for state_id in sorted(states)
    )


def _task_to_state_paths(
    task_id: str,
    relation: str,
    states: set[str],
    counts: Mapping[str, int],
) -> Tuple[Mapping[str, Any], ...]:
    return tuple(
        {"source": task_id, "relation": relation, "target": state_id, "count": counts.get(state_id, 1)}
        for state_id in sorted(states)
    )


def _abstract_paths(graph: TaskStateGraph, nodes: set[str]) -> Tuple[Mapping[str, Any], ...]:
    return tuple(
        {"source": node_id, "relation": "abstracts_to", "target": target}
        for node_id in sorted(nodes)
        for target in sorted(graph.abstraction_targets(node_id))
    )


def _missing_counts(
    required: Mapping[str, int],
    available: Mapping[str, int],
) -> Mapping[str, Mapping[str, int]]:
    return {
        state_id: {"required": count, "available": available.get(state_id, 0)}
        for state_id, count in sorted(required.items())
        if available.get(state_id, 0) < count
    }


def _format_missing_counts(missing: Mapping[str, Mapping[str, int]]) -> str:
    return ", ".join(
        f"{state_id} required={payload['required']} available={payload['available']}"
        for state_id, payload in missing.items()
    )

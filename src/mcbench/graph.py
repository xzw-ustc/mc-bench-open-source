from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import DefaultDict, Mapping, Set

from .catalog import BenchmarkCatalog


class GraphError(ValueError):
    """Raised when task-state graph edges violate the benchmark contract."""


@dataclass(frozen=True)
class TaskStateGraph:
    required_by_task: Mapping[str, Set[str]]
    produced_by_task: Mapping[str, Set[str]]
    enabled_by_task: Mapping[str, Set[str]] = field(default_factory=dict)
    consumed_by_task: Mapping[str, Set[str]] = field(default_factory=dict)
    abstractions: Mapping[str, Set[str]] = field(default_factory=dict)
    required_counts_by_task: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    produced_counts_by_task: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    enabled_counts_by_task: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
    consumed_counts_by_task: Mapping[str, Mapping[str, int]] = field(default_factory=dict)

    @classmethod
    def from_catalog(cls, catalog: BenchmarkCatalog) -> "TaskStateGraph":
        required: DefaultDict[str, Set[str]] = defaultdict(set)
        produced: DefaultDict[str, Set[str]] = defaultdict(set)
        enabled: DefaultDict[str, Set[str]] = defaultdict(set)
        consumed: DefaultDict[str, Set[str]] = defaultdict(set)
        abstractions: DefaultDict[str, Set[str]] = defaultdict(set)
        required_counts: DefaultDict[str, dict[str, int]] = defaultdict(dict)
        produced_counts: DefaultDict[str, dict[str, int]] = defaultdict(dict)
        enabled_counts: DefaultDict[str, dict[str, int]] = defaultdict(dict)
        consumed_counts: DefaultDict[str, dict[str, int]] = defaultdict(dict)
        states = set(catalog.states)
        tasks = set(catalog.tasks)

        for edge in catalog.edges:
            if edge.relation in {"requires", "enables"}:
                if edge.source not in states or edge.target not in tasks:
                    raise GraphError(
                        f"{edge.relation} edges must point from a state to a task: {edge.source} -> {edge.target}"
                    )
                if edge.relation == "requires":
                    required[edge.target].add(edge.source)
                    _add_count(required_counts, edge.target, edge.source, edge.count)
                if edge.relation == "enables":
                    enabled[edge.target].add(edge.source)
                    _add_count(enabled_counts, edge.target, edge.source, edge.count)
            elif edge.relation in {"produces", "consumes"}:
                if edge.source not in tasks or edge.target not in states:
                    raise GraphError(
                        f"{edge.relation} edges must point from a task to a state: {edge.source} -> {edge.target}"
                    )
                if edge.relation == "produces":
                    produced[edge.source].add(edge.target)
                    _add_count(produced_counts, edge.source, edge.target, edge.count)
                if edge.relation == "consumes":
                    consumed[edge.source].add(edge.target)
                    _add_count(consumed_counts, edge.source, edge.target, edge.count)
            elif edge.relation == "abstracts_to":
                if edge.source not in states | tasks or edge.target not in states | tasks:
                    raise GraphError(
                        f"abstracts_to edges must connect known graph nodes: {edge.source} -> {edge.target}"
                    )
                abstractions[edge.source].add(edge.target)

        return cls(
            required_by_task=dict(required),
            produced_by_task=dict(produced),
            enabled_by_task=dict(enabled),
            consumed_by_task=dict(consumed),
            abstractions=dict(abstractions),
            required_counts_by_task={task: dict(counts) for task, counts in required_counts.items()},
            produced_counts_by_task={task: dict(counts) for task, counts in produced_counts.items()},
            enabled_counts_by_task={task: dict(counts) for task, counts in enabled_counts.items()},
            consumed_counts_by_task={task: dict(counts) for task, counts in consumed_counts.items()},
        )

    def required_states(self, task_id: str) -> Set[str]:
        return set(self.required_by_task.get(task_id, set()))

    def produced_states(self, task_id: str) -> Set[str]:
        return set(self.produced_by_task.get(task_id, set()))

    def enabled_states(self, task_id: str) -> Set[str]:
        return set(self.enabled_by_task.get(task_id, set()))

    def consumed_states(self, task_id: str) -> Set[str]:
        return set(self.consumed_by_task.get(task_id, set()))

    def abstraction_targets(self, node_id: str) -> Set[str]:
        return set(self.abstractions.get(node_id, set()))

    def required_state_counts(self, task_id: str) -> Mapping[str, int]:
        return dict(self.required_counts_by_task.get(task_id, {}))

    def produced_state_counts(self, task_id: str) -> Mapping[str, int]:
        return dict(self.produced_counts_by_task.get(task_id, {}))

    def enabled_state_counts(self, task_id: str) -> Mapping[str, int]:
        return dict(self.enabled_counts_by_task.get(task_id, {}))

    def consumed_state_counts(self, task_id: str) -> Mapping[str, int]:
        return dict(self.consumed_counts_by_task.get(task_id, {}))


def _add_count(index: DefaultDict[str, dict[str, int]], task_id: str, state_id: str, count: int) -> None:
    index[task_id][state_id] = index[task_id].get(state_id, 0) + count

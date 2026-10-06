from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Tuple


STATE_KINDS = {
    "item",
    "tool",
    "environment",
    "player",
    "location",
    "structure",
    "entity",
    "state_group",
    "task_group",
}

EDGE_RELATIONS = {"requires", "produces", "enables", "consumes", "abstracts_to"}
OBSERVATION_TRACKS = {"native_perception", "structured_state"}
OBSERVATION_ACCESS_LEVELS = {"agent_visible", "evaluator_only"}


def _require_non_empty(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class StateSpec:
    id: str
    kind: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_non_empty(self.id, "state.id"))
        object.__setattr__(self, "description", _require_non_empty(self.description, "state.description"))
        if self.kind not in STATE_KINDS:
            raise ValueError(f"Unsupported state kind: {self.kind}")


@dataclass(frozen=True)
class TaskSpec:
    id: str
    name: str
    domain: str
    instruction: str
    max_steps: int
    environment_profile: str
    success: Mapping[str, Any]
    observation_sources: Tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_non_empty(self.id, "task.id"))
        object.__setattr__(self, "name", _require_non_empty(self.name, "task.name"))
        object.__setattr__(self, "domain", _require_non_empty(self.domain, "task.domain"))
        object.__setattr__(self, "instruction", _require_non_empty(self.instruction, "task.instruction"))
        object.__setattr__(
            self,
            "environment_profile",
            _require_non_empty(self.environment_profile, "task.environment_profile"),
        )
        if not isinstance(self.max_steps, int) or self.max_steps <= 0:
            raise ValueError("task.max_steps must be a positive integer")
        if not isinstance(self.success, Mapping):
            raise ValueError("task.success must be a mapping")
        if not isinstance(self.observation_sources, Sequence) or isinstance(
            self.observation_sources,
            (str, bytes, bytearray),
        ):
            raise ValueError("task.observation_sources must be a sequence")
        for source in self.observation_sources:
            if not isinstance(source, Mapping):
                raise ValueError("task.observation_sources entries must be mappings")
            _validate_observation_source(source, "task.observation_sources")


@dataclass(frozen=True)
class MissionEventSpec:
    id: str
    task_id: str
    produced_state: str
    kind: str
    trigger: Mapping[str, Any]
    observation_sources: Tuple[Mapping[str, Any], ...] = ()
    snapshot_effect: Mapping[str, Any] | None = None
    terminal_condition: Mapping[str, Any] | None = None
    failure_condition: Mapping[str, Any] | None = None
    profiles: Tuple[str, ...] = ()
    implementation_status: str = "planned"
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_non_empty(self.id, "mission_event.id"))
        object.__setattr__(self, "task_id", _require_non_empty(self.task_id, "mission_event.task_id"))
        object.__setattr__(
            self,
            "produced_state",
            _require_non_empty(self.produced_state, "mission_event.produced_state"),
        )
        object.__setattr__(self, "kind", _require_non_empty(self.kind, "mission_event.kind"))
        if not isinstance(self.trigger, Mapping):
            raise ValueError("mission_event.trigger must be a mapping")
        if not isinstance(self.observation_sources, Sequence) or isinstance(
            self.observation_sources,
            (str, bytes, bytearray),
        ):
            raise ValueError("mission_event.observation_sources must be a sequence")
        for source in self.observation_sources:
            if not isinstance(source, Mapping):
                raise ValueError("mission_event.observation_sources entries must be mappings")
            _validate_observation_source(source, "mission_event.observation_sources")
        if self.snapshot_effect is not None and not isinstance(self.snapshot_effect, Mapping):
            raise ValueError("mission_event.snapshot_effect must be a mapping")
        if self.terminal_condition is not None and not isinstance(self.terminal_condition, Mapping):
            raise ValueError("mission_event.terminal_condition must be a mapping")
        if self.failure_condition is not None and not isinstance(self.failure_condition, Mapping):
            raise ValueError("mission_event.failure_condition must be a mapping")
        if not isinstance(self.profiles, Sequence) or isinstance(self.profiles, (str, bytes, bytearray)):
            raise ValueError("mission_event.profiles must be a sequence")
        if self.implementation_status not in {"implemented", "partial", "planned"}:
            raise ValueError(f"Unsupported mission_event implementation_status: {self.implementation_status}")

    def to_dict(self) -> Mapping[str, Any]:
        payload = {
            "id": self.id,
            "task_id": self.task_id,
            "produced_state": self.produced_state,
            "kind": self.kind,
            "trigger": self.trigger,
            "observation_sources": tuple(self.observation_sources),
            "implementation_status": self.implementation_status,
        }
        if self.snapshot_effect is not None:
            payload["snapshot_effect"] = self.snapshot_effect
        if self.terminal_condition is not None:
            payload["terminal_condition"] = self.terminal_condition
        if self.failure_condition is not None:
            payload["failure_condition"] = self.failure_condition
        if self.profiles:
            payload["profiles"] = self.profiles
        if self.notes:
            payload["notes"] = self.notes
        return payload


@dataclass(frozen=True)
class EdgeSpec:
    source: str
    relation: str
    target: str
    count: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _require_non_empty(self.source, "edge.source"))
        object.__setattr__(self, "target", _require_non_empty(self.target, "edge.target"))
        if self.relation not in EDGE_RELATIONS:
            raise ValueError(f"Unsupported edge relation: {self.relation}")
        if not isinstance(self.count, int) or self.count <= 0:
            raise ValueError("edge.count must be a positive integer")


def _validate_observation_source(source: Mapping[str, Any], field_name: str) -> None:
    for key in ("path", "kind", "meaning", "track", "agent_access"):
        if key not in source:
            raise ValueError(f"{field_name} entries must include {key}")
    if source["track"] not in OBSERVATION_TRACKS:
        raise ValueError(f"Unsupported observation track: {source['track']}")
    if source["agent_access"] not in OBSERVATION_ACCESS_LEVELS:
        raise ValueError(f"Unsupported observation access level: {source['agent_access']}")


@dataclass(frozen=True)
class ChainSpec:
    id: str
    name: str
    kind: str
    task_ids: Tuple[str, ...]
    initial_states: Tuple[str, ...]
    domains: Tuple[str, ...]
    difficulty: str
    environment_profile: str
    profile_policy: str = "task"

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_non_empty(self.id, "chain.id"))
        object.__setattr__(self, "name", _require_non_empty(self.name, "chain.name"))
        object.__setattr__(self, "kind", _require_non_empty(self.kind, "chain.kind"))
        object.__setattr__(
            self,
            "difficulty",
            _require_non_empty(self.difficulty, "chain.difficulty"),
        )
        object.__setattr__(
            self,
            "environment_profile",
            _require_non_empty(self.environment_profile, "chain.environment_profile"),
        )
        if self.profile_policy not in {"task", "chain"}:
            raise ValueError("chain.profile_policy must be 'task' or 'chain'")
        if not self.task_ids:
            raise ValueError("chain.task_ids must not be empty")
        if not self.domains:
            raise ValueError("chain.domains must not be empty")


@dataclass(frozen=True)
class BenchmarkSplitSpec:
    id: str
    name: str
    purpose: str
    task_ids: Tuple[str, ...] = ()
    chain_ids: Tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_non_empty(self.id, "split.id"))
        object.__setattr__(self, "name", _require_non_empty(self.name, "split.name"))
        object.__setattr__(self, "purpose", _require_non_empty(self.purpose, "split.purpose"))
        if not isinstance(self.task_ids, Sequence) or isinstance(self.task_ids, (str, bytes, bytearray)):
            raise ValueError("split.task_ids must be a sequence")
        if not isinstance(self.chain_ids, Sequence) or isinstance(self.chain_ids, (str, bytes, bytearray)):
            raise ValueError("split.chain_ids must be a sequence")

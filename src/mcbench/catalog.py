from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence

from .schema import BenchmarkSplitSpec, ChainSpec, EdgeSpec, MissionEventSpec, StateSpec, TaskSpec


class CatalogError(ValueError):
    """Raised when benchmark catalog files are inconsistent."""


@dataclass(frozen=True)
class BenchmarkCatalog:
    states: Mapping[str, StateSpec]
    tasks: Mapping[str, TaskSpec]
    edges: Sequence[EdgeSpec]
    chains: Mapping[str, ChainSpec]
    mission_events: Mapping[str, MissionEventSpec] = field(default_factory=dict)
    splits: Mapping[str, BenchmarkSplitSpec] = field(default_factory=dict)


def _load_json_list(path: Path) -> List[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"Missing catalog file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"Invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(payload, list):
        raise CatalogError(f"{path.name} must contain a JSON array")
    return payload


def _load_optional_json_list(path: Path) -> List[dict]:
    if not path.exists():
        return []
    return _load_json_list(path)


def _index_by_id(records: Iterable[object], record_type: str) -> Dict[str, object]:
    indexed: Dict[str, object] = {}
    for record in records:
        record_id = getattr(record, "id")
        if record_id in indexed:
            raise CatalogError(f"Duplicate {record_type} id: {record_id}")
        indexed[record_id] = record
    return indexed


def load_catalog_dir(catalog_dir: str | Path) -> BenchmarkCatalog:
    root = Path(catalog_dir)
    states = [
        StateSpec(
            id=item["id"],
            kind=item["kind"],
            description=item["description"],
        )
        for item in _load_json_list(root / "states.json")
    ]
    tasks = [
        TaskSpec(
            id=item["id"],
            name=item["name"],
            domain=item["domain"],
            instruction=item["instruction"],
            max_steps=item["max_steps"],
            environment_profile=item["environment_profile"],
            success=item["success"],
            observation_sources=tuple(item.get("observation_sources", ())),
        )
        for item in _load_json_list(root / "tasks.json")
    ]
    edges = [
        EdgeSpec(
            source=item["source"],
            relation=item["relation"],
            target=item["target"],
            count=item.get("count", 1),
        )
        for item in _load_json_list(root / "edges.json")
    ]
    chains = [
        ChainSpec(
            id=item["id"],
            name=item["name"],
            kind=item["kind"],
            task_ids=tuple(item["task_ids"]),
            initial_states=tuple(item["initial_states"]),
            domains=tuple(item["domains"]),
            difficulty=item["difficulty"],
            environment_profile=item["environment_profile"],
            profile_policy=item.get("profile_policy", "task"),
        )
        for item in _load_json_list(root / "chains.json")
    ]
    mission_events = [
        MissionEventSpec(
            id=item["id"],
            task_id=item["task_id"],
            produced_state=item["produced_state"],
            kind=item["kind"],
            trigger=item["trigger"],
            observation_sources=tuple(item.get("observation_sources", ())),
            snapshot_effect=item.get("snapshot_effect"),
            terminal_condition=item.get("terminal_condition"),
            failure_condition=item.get("failure_condition"),
            profiles=tuple(item.get("profiles", ())),
            implementation_status=item.get("implementation_status", "planned"),
            notes=item.get("notes", ""),
        )
        for item in _load_optional_json_list(root / "mission_events.json")
    ]
    splits = [
        BenchmarkSplitSpec(
            id=item["id"],
            name=item["name"],
            purpose=item["purpose"],
            task_ids=tuple(item.get("task_ids", ())),
            chain_ids=tuple(item.get("chain_ids", ())),
            notes=item.get("notes", ""),
        )
        for item in _load_optional_json_list(root / "splits.json")
    ]

    indexed_states = _index_by_id(states, "state")
    indexed_tasks = _index_by_id(tasks, "task")
    indexed_chains = _index_by_id(chains, "chain")
    indexed_mission_events = _index_by_id(mission_events, "mission_event")
    indexed_splits = _index_by_id(splits, "split")

    known_nodes = set(indexed_states) | set(indexed_tasks)
    for edge in edges:
        if edge.source not in known_nodes:
            raise CatalogError(f"Edge references missing source node: {edge.source}")
        if edge.target not in known_nodes:
            raise CatalogError(f"Edge references missing target node: {edge.target}")

    for chain in indexed_chains.values():
        for task_id in chain.task_ids:
            if task_id not in indexed_tasks:
                raise CatalogError(f"Chain {chain.id} references missing task: {task_id}")
        for state_id in chain.initial_states:
            if state_id not in indexed_states:
                raise CatalogError(f"Chain {chain.id} references missing initial state: {state_id}")

    for event in indexed_mission_events.values():
        if event.task_id not in indexed_tasks:
            raise CatalogError(f"Mission event {event.id} references missing task: {event.task_id}")
        if event.produced_state not in indexed_states:
            raise CatalogError(f"Mission event {event.id} references missing state: {event.produced_state}")

    for split in indexed_splits.values():
        for task_id in split.task_ids:
            if task_id not in indexed_tasks:
                raise CatalogError(f"Split {split.id} references missing task: {task_id}")
        for chain_id in split.chain_ids:
            if chain_id not in indexed_chains:
                raise CatalogError(f"Split {split.id} references missing chain: {chain_id}")

    return BenchmarkCatalog(
        states=indexed_states,
        tasks=indexed_tasks,
        edges=tuple(edges),
        chains=indexed_chains,
        mission_events=indexed_mission_events,
        splits=indexed_splits,
    )

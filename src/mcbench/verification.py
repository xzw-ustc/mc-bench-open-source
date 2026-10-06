from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence, Tuple


@dataclass(frozen=True)
class ObservationSnapshot:
    inventory: Mapping[str, int] = field(default_factory=dict)
    flags: set[str] = field(default_factory=set)
    player_stats: Mapping[str, float] = field(default_factory=dict)
    counters: Mapping[str, int] = field(default_factory=dict)
    equipped: Mapping[str, str] = field(default_factory=dict)
    raw_observation: Mapping[str, Any] = field(default_factory=dict)
    info: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    failures: Tuple[str, ...]


def evaluate_success(success_spec: Mapping[str, Any], snapshot: ObservationSnapshot) -> VerificationResult:
    predicates = success_spec.get("all", ())
    if not isinstance(predicates, Sequence):
        raise ValueError("success.all must be a sequence")

    failures = []
    for predicate in predicates:
        failure = _predicate_failure(predicate, snapshot)
        if failure:
            failures.append(failure)

    return VerificationResult(passed=not failures, failures=tuple(failures))


def _predicate_failure(predicate: Mapping[str, Any], snapshot: ObservationSnapshot) -> str | None:
    name = predicate.get("predicate")
    if name == "inventory_at_least":
        item = predicate["item"]
        count = predicate["count"]
        if snapshot.inventory.get(item, 0) < count:
            return f"inventory_at_least({item} >= {count})"
    elif name == "flag_is_true":
        flag = predicate["flag"]
        if flag not in snapshot.flags:
            return f"flag_is_true({flag})"
    elif name == "player_stat_at_least":
        stat = predicate["stat"]
        value = predicate["value"]
        if snapshot.player_stats.get(stat, 0) < value:
            return f"player_stat_at_least({stat} >= {value})"
    elif name == "counter_at_least":
        counter = predicate["counter"]
        count = predicate["count"]
        if snapshot.counters.get(counter, 0) < count:
            return f"counter_at_least({counter} >= {count})"
    elif name == "equipped_equals":
        slot = predicate["slot"]
        item = predicate["item"]
        if snapshot.equipped.get(slot) != item:
            return f"equipped_equals({slot} == {item})"
    elif name == "snapshot_path_compare":
        path = predicate["path"]
        operator = predicate["operator"]
        expected = predicate["value"]
        found, actual = _resolve_snapshot_path(snapshot, path)
        if not found or not _compare_values(actual, operator, expected):
            return f"snapshot_path_compare({path} {operator} {expected})"
    elif name == "any_of":
        options = predicate.get("options", ())
        if not isinstance(options, Sequence) or isinstance(options, (str, bytes, bytearray)):
            raise ValueError("any_of.options must be a sequence")
        failures = tuple(_predicate_failure(option, snapshot) for option in options)
        if any(failure is None for failure in failures):
            return None
        joined = " OR ".join(failure for failure in failures if failure)
        return f"any_of({joined})"
    else:
        raise ValueError(f"Unsupported verifier predicate: {name}")
    return None


def _resolve_snapshot_path(snapshot: ObservationSnapshot, path: str) -> tuple[bool, Any]:
    roots = {
        "inventory": snapshot.inventory,
        "flags": snapshot.flags,
        "player_stats": snapshot.player_stats,
        "counters": snapshot.counters,
        "equipped": snapshot.equipped,
        "raw_observation": snapshot.raw_observation,
        "info": snapshot.info,
    }
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


def _compare_values(actual: Any, operator: str, expected: Any) -> bool:
    if hasattr(actual, "item"):
        actual = actual.item()
    if hasattr(expected, "item"):
        expected = expected.item()
    if operator == "==":
        return bool(actual == expected)
    if operator == ">=":
        return bool(actual >= expected)
    if operator == ">":
        return bool(actual > expected)
    if operator == "<=":
        return bool(actual <= expected)
    if operator == "<":
        return bool(actual < expected)
    raise ValueError(f"Unsupported snapshot comparison operator: {operator}")

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from .catalog import BenchmarkCatalog


class ProfileCatalogError(ValueError):
    """Raised when environment profile definitions are inconsistent."""


CONTROLLED_RESOURCE_TASK_PROFILES: Mapping[str, str] = {
    "scout_coal_source": "fixed_coal_shaft",
    "collect_coal": "fixed_coal_shaft",
    "craft_torch": "fixed_coal_shaft",
    "collect_iron_ore_basic": "fixed_ore_progression_shaft",
    "smelt_iron_ingot": "fixed_ore_progression_shaft",
    "collect_iron_ore": "fixed_ore_progression_shaft",
    "collect_gold_ore": "fixed_ore_progression_shaft",
    "collect_redstone": "fixed_ore_progression_shaft",
    "collect_lapis_lazuli": "fixed_ore_progression_shaft",
    "collect_diamond": "fixed_ore_progression_shaft",
    "collect_emerald": "fixed_ore_progression_shaft",
    "smelt_gold_ingot": "fixed_ore_progression_shaft",
    "craft_iron_pickaxe": "fixed_ore_progression_shaft",
}
CONTROLLED_RESOURCE_RELATIVE_TO = {"start_position", "actual_spawn_position", "tunnel_entrance"}


@dataclass(frozen=True)
class EnvironmentProfile:
    id: str
    env_id: str
    seed: int | None = None
    day_phase: str | None = None
    weather: str | None = None
    initial_inventory: Mapping[str, int] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


def load_profile_catalog(profile_dir: str | Path) -> Mapping[str, EnvironmentProfile]:
    path = Path(profile_dir) / "profiles.json"
    return _load_profile_file(path, seen_paths=set())


def _load_profile_file(
    path: Path,
    *,
    seen_paths: set[Path],
) -> Mapping[str, EnvironmentProfile]:
    resolved_path = path.resolve()
    if resolved_path in seen_paths:
        raise ProfileCatalogError(f"Cyclic profile extension: {path}")
    seen_paths = {*seen_paths, resolved_path}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProfileCatalogError(f"Missing environment profile file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ProfileCatalogError(f"Invalid JSON in {path.name}: {exc}") from exc

    inherited: Mapping[str, EnvironmentProfile] = {}
    if isinstance(payload, Mapping):
        extends = payload.get("extends")
        records = payload.get("profiles")
        if not isinstance(extends, str) or not extends:
            raise ProfileCatalogError("extended profiles.json must define a non-empty extends path")
        if not isinstance(records, list):
            raise ProfileCatalogError("extended profiles.json must define profiles as a JSON array")
        parent = (path.parent / extends).resolve() / "profiles.json"
        inherited = _load_profile_file(parent, seen_paths=seen_paths)
        payload = records
    if not isinstance(payload, list):
        raise ProfileCatalogError("profiles.json must contain a JSON array")

    indexed: Dict[str, EnvironmentProfile] = dict(inherited)
    for item in payload:
        profile = EnvironmentProfile(
            id=item["id"],
            env_id=item["env_id"],
            seed=item.get("seed"),
            day_phase=item.get("day_phase"),
            weather=item.get("weather"),
            initial_inventory=item.get("initial_inventory", {}),
            metadata=item.get("metadata", {}),
        )
        if profile.id in indexed:
            raise ProfileCatalogError(f"Duplicate environment profile id: {profile.id}")
        indexed[profile.id] = profile
    return indexed


def validate_profile_references(
    catalog: BenchmarkCatalog,
    profiles: Mapping[str, EnvironmentProfile],
) -> None:
    known_profiles = set(profiles)
    for task in catalog.tasks.values():
        if task.environment_profile not in known_profiles:
            raise ProfileCatalogError(
                f"Task {task.id} references missing environment profile: {task.environment_profile}"
            )
    for chain in catalog.chains.values():
        if chain.environment_profile not in known_profiles:
            raise ProfileCatalogError(
                f"Chain {chain.id} references missing environment profile: {chain.environment_profile}"
            )
    for event in catalog.mission_events.values():
        for profile_id in event.profiles:
            if profile_id not in known_profiles:
                raise ProfileCatalogError(
                    f"Mission event {event.id} references missing environment profile: {profile_id}"
                )


def audit_controlled_resource_catalog(
    catalog: BenchmarkCatalog,
    profiles: Mapping[str, EnvironmentProfile],
) -> Mapping[str, Any]:
    """Audit controlled resource profiles as benchmark problem-instance metadata."""

    blockers: list[str] = []
    controlled_profiles = {
        profile_id: profile
        for profile_id, profile in profiles.items()
        if profile.metadata.get("controlled_resources")
    }
    for task_id, expected_profile_id in CONTROLLED_RESOURCE_TASK_PROFILES.items():
        task = catalog.tasks.get(task_id)
        if task is None:
            blockers.append(f"Controlled-resource task is missing from catalog: {task_id}")
            continue
        if task.environment_profile != expected_profile_id:
            blockers.append(
                f"Task {task_id} should use {expected_profile_id}, got {task.environment_profile}."
            )
        if expected_profile_id not in controlled_profiles:
            blockers.append(f"Expected controlled resource profile is missing: {expected_profile_id}")

    profile_summaries = []
    for profile_id, profile in sorted(controlled_profiles.items()):
        profile_blockers, resource_summaries = _audit_controlled_resource_profile(profile)
        blockers.extend(f"{profile_id}: {blocker}" for blocker in profile_blockers)
        profile_summaries.append(
            {
                "profile_id": profile_id,
                "resource_count": len(resource_summaries),
                "resources": resource_summaries,
                "initial_inventory_count": len(profile.initial_inventory),
            }
        )

    return {
        "id": "controlled_resource_catalog",
        "status": "ready" if not blockers else "blocked",
        "expected_task_profile_count": len(CONTROLLED_RESOURCE_TASK_PROFILES),
        "controlled_profile_count": len(controlled_profiles),
        "resource_count": sum(len(item["resources"]) for item in profile_summaries),
        "expected_task_profiles": dict(CONTROLLED_RESOURCE_TASK_PROFILES),
        "profile_summaries": profile_summaries,
        "blockers": blockers,
    }


def _audit_controlled_resource_profile(
    profile: EnvironmentProfile,
) -> tuple[list[str], list[Mapping[str, Any]]]:
    blockers: list[str] = []
    resources = profile.metadata.get("controlled_resources", ())
    known_blocks = profile.metadata.get("known_blocks", ())
    if profile.initial_inventory:
        blockers.append("controlled profile must not grant initial inventory items")
    if not profile.metadata.get("world_decorator"):
        blockers.append("controlled profile must define a world_decorator")
    if not isinstance(resources, Sequence) or isinstance(resources, (str, bytes, bytearray)):
        return blockers + ["controlled_resources must be a sequence"], []

    resource_summaries: list[Mapping[str, Any]] = []
    for index, item in enumerate(resources):
        if not isinstance(item, Mapping):
            blockers.append(f"controlled_resources[{index}] must be a mapping")
            continue
        resource = str(item.get("resource", ""))
        placement = item.get("placement", {})
        success_evidence = item.get("success_still_requires", ())
        if not resource:
            blockers.append(f"controlled_resources[{index}] is missing resource")
        if not isinstance(success_evidence, Sequence) or isinstance(
            success_evidence,
            (str, bytes, bytearray),
        ) or not success_evidence:
            blockers.append(f"{resource or index} must document success_still_requires evidence")
        placement_blockers, placement_summary = _audit_controlled_resource_placement(resource, placement)
        blockers.extend(placement_blockers)
        known_block_count = _known_resource_block_count(known_blocks, resource, placement_summary.get("y_band"))
        if resource and known_block_count == 0:
            blockers.append(f"{resource} has no known_blocks inside its documented y_band")
        resource_summaries.append(
            {
                "resource": resource,
                "placement": placement_summary,
                "known_block_count": known_block_count,
                "success_evidence_count": len(success_evidence) if isinstance(success_evidence, Sequence) else 0,
            }
        )
    if not resource_summaries:
        blockers.append("controlled profile must declare at least one resource")
    return blockers, resource_summaries


def _audit_controlled_resource_placement(
    resource: str,
    placement: Any,
) -> tuple[list[str], Mapping[str, Any]]:
    blockers: list[str] = []
    if not isinstance(placement, Mapping):
        return [f"{resource or 'resource'} placement must be a mapping"], {}
    y_band = placement.get("y_band")
    horizontal_radius = placement.get("horizontal_radius")
    vertical_radius = placement.get("vertical_radius")
    relative_to = placement.get("relative_to")
    if not _valid_numeric_band(y_band):
        blockers.append(f"{resource} placement must define an ordered two-value y_band")
        y_band_summary: list[int] = []
    else:
        y_band_summary = [int(y_band[0]), int(y_band[1])]
    if not isinstance(horizontal_radius, (int, float)) or horizontal_radius <= 0:
        blockers.append(f"{resource} placement must define positive horizontal_radius")
    if not isinstance(vertical_radius, (int, float)) or vertical_radius < 0:
        blockers.append(f"{resource} placement must define non-negative vertical_radius")
    if relative_to not in CONTROLLED_RESOURCE_RELATIVE_TO:
        blockers.append(f"{resource} placement has unsupported relative_to: {relative_to}")
    return blockers, {
        "type": placement.get("type", ""),
        "y_band": y_band_summary,
        "horizontal_radius": horizontal_radius,
        "vertical_radius": vertical_radius,
        "relative_to": relative_to,
    }


def _valid_numeric_band(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return False
    if len(value) != 2:
        return False
    if not all(isinstance(item, (int, float)) for item in value):
        return False
    return value[0] <= value[1]


def _known_resource_block_count(known_blocks: Any, resource: str, y_band: Any) -> int:
    if not resource or not isinstance(known_blocks, Sequence) or isinstance(
        known_blocks,
        (str, bytes, bytearray),
    ):
        return 0
    if not _valid_numeric_band(y_band):
        return 0
    count = 0
    for block in known_blocks:
        if not isinstance(block, Mapping):
            continue
        if block.get("type") != resource:
            continue
        y = block.get("y")
        if isinstance(y, (int, float)) and y_band[0] <= y <= y_band[1]:
            count += 1
    return count

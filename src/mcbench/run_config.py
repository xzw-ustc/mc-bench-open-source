from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class BenchmarkRunConfig:
    catalog_dir: str
    profile_dir: str
    chain_id: str
    environment_profile: str
    environment: Mapping[str, Any]
    agent: Mapping[str, Any]
    output_path: str
    max_stage_steps: int | None = None


@dataclass(frozen=True)
class BenchmarkSuiteConfig:
    catalog_dir: str
    profile_dir: str
    output_dir: str
    environment: Mapping[str, Any]
    agent: Mapping[str, Any]
    chain_ids: Sequence[str] = ()
    split_ids: Sequence[str] = ()
    max_stage_steps: int | None = None
    per_stage_profiles: bool = True


def _read_config(path: str | Path, allowed: set[str]) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Run configuration must be a JSON object.")
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"Unsupported configuration fields: {', '.join(sorted(unknown))}")
    return payload


def load_run_config(config_path: str | Path) -> BenchmarkRunConfig:
    payload = _read_config(config_path, set(BenchmarkRunConfig.__dataclass_fields__))
    return BenchmarkRunConfig(
        catalog_dir=payload["catalog_dir"],
        profile_dir=payload.get("profile_dir", payload["catalog_dir"]),
        chain_id=payload["chain_id"],
        environment_profile=payload["environment_profile"],
        environment=payload.get("environment", {"kind": "scripted"}),
        agent=payload["agent"],
        output_path=payload["output_path"],
        max_stage_steps=payload.get("max_stage_steps"),
    )


def load_suite_config(config_path: str | Path) -> BenchmarkSuiteConfig:
    payload = _read_config(config_path, set(BenchmarkSuiteConfig.__dataclass_fields__))
    return BenchmarkSuiteConfig(
        catalog_dir=payload["catalog_dir"],
        profile_dir=payload.get("profile_dir", payload["catalog_dir"]),
        output_dir=payload["output_dir"],
        environment=payload.get("environment", {"kind": "scripted"}),
        agent=payload["agent"],
        chain_ids=tuple(payload.get("chain_ids", ())),
        split_ids=tuple(payload.get("split_ids", ())),
        max_stage_steps=payload.get("max_stage_steps"),
        per_stage_profiles=bool(payload.get("per_stage_profiles", True)),
    )

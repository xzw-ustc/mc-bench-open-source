from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Tuple

from .metrics import chain_metrics


@dataclass(frozen=True)
class StageReport:
    task_id: str
    status: str
    steps: int
    failures: Tuple[str, ...]
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Mapping[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True)
class ChainRunReport:
    chain_id: str
    completed: bool
    stages: Tuple[StageReport, ...]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def metrics(self) -> Mapping[str, Any]:
        return chain_metrics(self.stages, self.metadata)

    def to_dict(self) -> Mapping[str, Any]:
        return _jsonable({
            "chain_id": self.chain_id,
            "completed": self.completed,
            "stages": [stage.to_dict() for stage in self.stages],
            "metrics": dict(self.metrics()),
            "metadata": dict(self.metadata),
        })


def write_report_json(report: ChainRunReport, output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist"):
        try:
            return _jsonable(value.tolist())
        except (TypeError, ValueError):
            pass
    return value

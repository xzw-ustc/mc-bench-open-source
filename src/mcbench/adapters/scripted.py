from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..runner import EnvironmentStep
from ..verification import ObservationSnapshot


class ScriptedEnvironmentAdapter:
    def __init__(self, snapshots: Sequence[ObservationSnapshot]) -> None:
        if not snapshots:
            raise ValueError("scripted environment requires at least one snapshot")
        self._snapshots = list(snapshots)
        self._index = 0
        self.profile = None

    def reset(self, profile: str) -> ObservationSnapshot:
        self.profile = profile
        self._index = 0
        return self._snapshots[0]

    def observe(self) -> ObservationSnapshot:
        return self._snapshots[self._index]

    def step(self, action: Mapping[str, Any]) -> EnvironmentStep:
        self._index = min(self._index + 1, len(self._snapshots) - 1)
        return EnvironmentStep(
            snapshot=self._snapshots[self._index],
            done=False,
            info={"action": dict(action)},
        )

    def close(self) -> None:
        return None


class ScriptedAgentAdapter:
    def __init__(self, action: Mapping[str, Any] | None = None) -> None:
        self._action = dict(action or {"noop": 1})
        self.instructions = []

    def reset(self, chain_context) -> None:
        return None

    def act(self, observation, instruction: str, stage_context) -> Mapping[str, Any]:
        self.instructions.append(instruction)
        return dict(self._action)


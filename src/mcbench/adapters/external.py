from __future__ import annotations

import inspect
from importlib import import_module
from typing import Any, Callable, Mapping

from .base import ExternalAdapterError


class ExternalPolicyAgentAdapter:
    """Generic adapter for third-party Minecraft agents.

    The adapter intentionally keeps MC-EvoBench method-agnostic: external
    projects provide a policy factory through a ``module:attribute`` entrypoint,
    and the policy only needs to expose ``act(...)``.
    """

    def __init__(
        self,
        *,
        agent_label: str = "external",
        runtime_module: str | None = None,
        policy_entrypoint: str | None = None,
        action_adapter_entrypoint: str | None = None,
        device: str = "cuda",
        prompt_template: str = "{instruction}",
        policy_kwargs: Mapping[str, Any] | None = None,
    ) -> None:
        self.agent_label = agent_label
        self.runtime_module = runtime_module
        self.policy_entrypoint = policy_entrypoint
        self.action_adapter_entrypoint = action_adapter_entrypoint
        self.device = device
        self.prompt_template = prompt_template
        self.policy_kwargs = dict(policy_kwargs or {})
        self._policy = None
        self._action_adapter = None

    def reset(self, chain_context) -> None:
        if self.runtime_module:
            try:
                import_module(self.runtime_module)
            except ModuleNotFoundError as exc:
                raise ExternalAdapterError(
                    f"{self.agent_label} runtime is unavailable. "
                    f"Install/import '{self.runtime_module}' before using this adapter."
                ) from exc
        factory = self._load_entrypoint(self.policy_entrypoint)
        self._action_adapter = self._load_entrypoint(self.action_adapter_entrypoint, required=False)
        if factory is None:
            raise ExternalAdapterError(
                f"{self.agent_label} adapter requires agent.policy_entrypoint. "
                "The entrypoint must create a policy object exposing act(...)."
            )
        self._policy = self._call_factory(factory, chain_context)
        if hasattr(self._policy, "reset"):
            self._policy.reset()

    def act(self, observation, instruction: str, stage_context) -> Mapping[str, Any]:
        if self._policy is None or not hasattr(self._policy, "act"):
            raise ExternalAdapterError(
                f"{self.agent_label} adapter needs a policy object exposing act(...)."
            )
        prompt = self._format_prompt(instruction, stage_context)
        try:
            action = self._policy.act(
                observation.raw_observation or observation,
                prompt,
                stage_context=stage_context,
                snapshot=observation,
            )
        except TypeError as exc:
            if not _is_call_signature_error(exc):
                raise
            try:
                action = self._policy.act(observation.raw_observation or observation, prompt)
            except TypeError as fallback_exc:
                if not _is_call_signature_error(fallback_exc):
                    raise
                action = self._policy.act(prompt)

        if self._action_adapter is not None:
            action = self._action_adapter(action)
        if not isinstance(action, Mapping):
            raise ExternalAdapterError(f"{self.agent_label} policy returned a non-mapping action.")
        return dict(action)

    def on_stage_end(self, stage_context, report) -> None:
        """Forward only ordinary episode feedback to policies with online memory."""
        if self._policy is None:
            return
        callback = getattr(self._policy, "on_stage_end", None)
        if not callable(callback):
            return
        callback(
            instruction=stage_context.task.instruction,
            status=report.status,
            steps=report.steps,
        )

    @property
    def transition_recording_enabled(self):
        return bool(getattr(self._policy, "execution_trace_enabled", False))

    def on_transition(self, **kwargs) -> None:
        callback = getattr(self._policy, "on_transition", None)
        if callable(callback):
            callback(**kwargs)

    def runtime_metadata(self) -> Mapping[str, Any]:
        """Return optional, policy-provided runtime accounting for run reports."""
        if self._policy is None:
            return {}
        callback = getattr(self._policy, "runtime_metadata", None)
        metadata = callback() if callable(callback) else {}
        return dict(metadata) if isinstance(metadata, Mapping) else {}

    @staticmethod
    def _load_entrypoint(entrypoint: str | None, *, required: bool = True) -> Callable[..., Any] | None:
        if entrypoint is None:
            return None
        if ":" not in entrypoint:
            raise ExternalAdapterError("Entrypoints must use 'module:attribute' format.")
        module_name, attribute_name = entrypoint.split(":", 1)
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            raise ExternalAdapterError(f"Could not import external agent entrypoint module: {module_name}") from exc
        target = module
        for part in attribute_name.split("."):
            if not hasattr(target, part):
                raise ExternalAdapterError(f"External agent entrypoint is missing attribute: {entrypoint}")
            target = getattr(target, part)
        if not callable(target):
            raise ExternalAdapterError(f"External agent entrypoint is not callable: {entrypoint}")
        return target

    def _call_factory(self, factory: Callable[..., Any], chain_context) -> Any:
        kwargs = {
            "agent_label": self.agent_label,
            "device": self.device,
            "prompt_template": self.prompt_template,
            "chain_context": chain_context,
            **self.policy_kwargs,
        }
        kwargs = {key: value for key, value in kwargs.items() if value is not None}
        try:
            signature = inspect.signature(factory)
        except (TypeError, ValueError):
            return factory(**kwargs)

        if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
            return factory(**kwargs)
        accepted = {
            key: value
            for key, value in kwargs.items()
            if key in signature.parameters
        }
        return factory(**accepted)

    def _format_prompt(self, instruction: str, stage_context) -> str:
        return self.prompt_template.format(
            instruction=instruction,
            task_id=getattr(getattr(stage_context, "task", None), "id", ""),
            task_name=getattr(getattr(stage_context, "task", None), "name", ""),
            domain=getattr(getattr(stage_context, "task", None), "domain", ""),
        )


def _is_call_signature_error(error: TypeError) -> bool:
    """Distinguish adapter arity fallbacks from TypeErrors raised inside a policy."""
    message = str(error).lower()
    markers = (
        "unexpected keyword argument",
        "required positional argument",
        "positional arguments but",
        "takes ",
    )
    return any(marker in message for marker in markers)

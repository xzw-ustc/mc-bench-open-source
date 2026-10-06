from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import time
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .adapters.base import ExternalAdapterError
from .adapters.external import ExternalPolicyAgentAdapter
from .adapters.minerl import MineRLEnvironmentAdapter
from .adapters.scripted import ScriptedAgentAdapter, ScriptedEnvironmentAdapter
from .catalog import load_catalog_dir
from .chains import CompiledChain, compile_chain
from .profiles import load_profile_catalog, validate_profile_references
from .reporting import write_report_json
from .runner import run_compiled_chain
from .run_config import load_run_config, load_suite_config
from .verification import ObservationSnapshot


def _advance_snapshot(snapshot: ObservationSnapshot, success_spec) -> ObservationSnapshot:
    inventory = dict(snapshot.inventory)
    flags = set(snapshot.flags)
    counters = dict(snapshot.counters)
    player_stats = dict(snapshot.player_stats)
    equipped = dict(snapshot.equipped)
    raw_observation = dict(snapshot.raw_observation)
    info = dict(snapshot.info)

    for predicate in success_spec.get("all", ()):
        _advance_snapshot_for_predicate(
            predicate,
            inventory,
            flags,
            counters,
            player_stats,
            equipped,
            raw_observation,
            info,
        )

    return ObservationSnapshot(
        inventory=inventory,
        flags=flags,
        counters=counters,
        player_stats=player_stats,
        equipped=equipped,
        raw_observation=raw_observation,
        info=info,
    )


def _advance_snapshot_for_predicate(
    predicate: Mapping[str, Any],
    inventory: dict[str, Any],
    flags: set[str],
    counters: dict[str, Any],
    player_stats: dict[str, Any],
    equipped: dict[str, Any],
    raw_observation: dict[str, Any],
    info: dict[str, Any],
) -> None:
    name = predicate.get("predicate")
    if name == "inventory_at_least":
        item = predicate["item"]
        inventory[item] = max(inventory.get(item, 0), predicate["count"])
    elif name == "flag_is_true":
        flags.add(predicate["flag"])
    elif name == "counter_at_least":
        counter = predicate["counter"]
        counters[counter] = max(counters.get(counter, 0), predicate["count"])
    elif name == "player_stat_at_least":
        stat = predicate["stat"]
        player_stats[stat] = max(player_stats.get(stat, 0), predicate["value"])
    elif name == "equipped_equals":
        equipped[predicate["slot"]] = predicate["item"]
    elif name == "snapshot_path_compare":
        _set_snapshot_path(
            predicate["path"],
            predicate["value"],
            inventory=inventory,
            flags=flags,
            counters=counters,
            player_stats=player_stats,
            equipped=equipped,
            raw_observation=raw_observation,
            info=info,
        )
    elif name == "any_of":
        for option in predicate.get("options", ()):
            _advance_snapshot_for_predicate(
                option,
                inventory,
                flags,
                counters,
                player_stats,
                equipped,
                raw_observation,
                info,
            )


def _set_snapshot_path(
    path: str,
    value: Any,
    *,
    inventory: dict[str, Any],
    flags: set[str],
    counters: dict[str, Any],
    player_stats: dict[str, Any],
    equipped: dict[str, Any],
    raw_observation: dict[str, Any],
    info: dict[str, Any],
) -> None:
    roots = {
        "inventory": inventory,
        "flags": flags,
        "counters": counters,
        "player_stats": player_stats,
        "equipped": equipped,
        "raw_observation": raw_observation,
        "info": info,
    }
    parts = path.split(".")
    if not parts or parts[0] not in roots:
        raise ValueError(f"Unsupported synthetic snapshot path: {path}")
    target = roots[parts[0]]
    if isinstance(target, set):
        if len(parts) != 2:
            raise ValueError(f"Unsupported synthetic set path: {path}")
        target.add(parts[1])
        return
    for part in parts[1:-1]:
        nested = target.get(part)
        if not isinstance(nested, dict):
            nested = {}
            target[part] = nested
        target = nested
    if len(parts) == 1:
        raise ValueError(f"Synthetic snapshot path must address a field: {path}")
    target[parts[-1]] = value


def _dry_run_snapshots(compiled_chain) -> Sequence[ObservationSnapshot]:
    snapshots = [ObservationSnapshot()]
    current = snapshots[0]
    for stage in compiled_chain.stages:
        current = _advance_snapshot(current, stage.task.success)
        snapshots.append(current)
    return snapshots


def _cmd_validate(catalog_dir: str) -> int:
    catalog = load_catalog_dir(Path(catalog_dir))
    profiles = load_profile_catalog(Path(catalog_dir))
    validate_profile_references(catalog, profiles)
    for chain_id in catalog.chains:
        compile_chain(catalog, chain_id)
    payload = {
        "states": len(catalog.states),
        "tasks": len(catalog.tasks),
        "edges": len(catalog.edges),
        "chains": len(catalog.chains),
        "mission_events": len(catalog.mission_events),
        "observation_tracks": _observation_track_counts(catalog),
        "profiles": len(profiles),
        "splits": len(catalog.splits),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _observation_track_counts(catalog: Any) -> Mapping[str, int]:
    counts = {"native_perception": 0, "structured_state": 0}
    for task in catalog.tasks.values():
        for source in task.observation_sources:
            track = source.get("track")
            if track in counts:
                counts[track] += 1
    for event in catalog.mission_events.values():
        for source in event.observation_sources:
            track = source.get("track")
            if track in counts:
                counts[track] += 1
    return counts


def _cmd_dry_run(catalog_dir: str, chain_id: str) -> int:
    catalog = load_catalog_dir(Path(catalog_dir))
    compiled = compile_chain(catalog, chain_id)
    environment = ScriptedEnvironmentAdapter(_dry_run_snapshots(compiled))
    agent = ScriptedAgentAdapter()
    report = run_compiled_chain(compiled, environment, agent)
    report = replace(report, metadata={**dict(report.metadata), "synthetic": True})
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


def _build_environment(
    environment_config: Mapping[str, Any],
    compiled: CompiledChain,
    profile: Any,
    profiles: Mapping[str, Any],
    *,
    per_stage_profiles: bool,
):
    if environment_config.get("kind") == "scripted":
        return ScriptedEnvironmentAdapter(_dry_run_snapshots(compiled))
    if environment_config.get("kind") == "minerl":
        return (
            _ProfiledMineRLEnvironmentAdapter(profiles, environment_config)
            if per_stage_profiles
            else _build_minerl_environment(profile, environment_config)
        )
    raise ValueError(f"Unsupported environment kind: {environment_config.get('kind')}")


def _with_stage_step_limit(compiled: CompiledChain, max_stage_steps: int) -> CompiledChain:
    if not isinstance(max_stage_steps, int) or max_stage_steps <= 0:
        raise ValueError("max_stage_steps must be a positive integer")
    stages = tuple(
        replace(stage, task=replace(stage.task, max_steps=min(stage.task.max_steps, max_stage_steps)))
        for stage in compiled.stages
    )
    return replace(compiled, stages=stages)


def _day_phase_start_time(day_phase: str) -> int | None:
    return {
        "day": 1000,
        "dusk": 12000,
        "night": 14000,
        "progression": None,
    }.get(day_phase)


def _build_minerl_environment(profile, environment_config: Mapping[str, Any]) -> MineRLEnvironmentAdapter:
    profile_metadata = dict(profile.metadata)
    initial_inventory = {
        **dict(profile.initial_inventory),
        **dict(environment_config.get("initial_inventory", {})),
    }
    start_time = environment_config.get(
        "start_time",
        profile_metadata.get("start_time", _day_phase_start_time(profile.day_phase)),
    )
    world_decorator = environment_config.get("world_decorator", profile_metadata.get("world_decorator"))
    spawn_support = environment_config.get(
        "spawn_support_decorator", profile_metadata.get("spawn_support_decorator")
    )
    if spawn_support:
        if not isinstance(spawn_support, str):
            raise ValueError("spawn_support_decorator must be a Malmo XML string")
        # Apply support after the profile's air-clearing decorator.  The
        # fixed ore shaft intentionally clears y=70..76; without this small
        # floor under the declared y=72 spawn, vanilla gravity drops the
        # player to y=70 during reset warmup and EnvServer closes the mission
        # socket as a placement mismatch.
        world_decorator = f"{world_decorator or ''}{spawn_support}"
    spawn_clearance = environment_config.get(
        "spawn_clearance_decorator",
        profile_metadata.get("spawn_clearance_decorator"),
    )
    if spawn_clearance:
        if not isinstance(spawn_clearance, str):
            raise ValueError("spawn_clearance_decorator must be a Malmo XML string")
        world_decorator = f"{spawn_clearance}{world_decorator or ''}"

    return MineRLEnvironmentAdapter(
        environment_config.get("env_id", profile.env_id),
        video_path=environment_config.get("video_path"),
        video_source=environment_config.get("video_source", "pov"),
        video_fps=environment_config.get("video_fps", 20),
        video_every_n_steps=environment_config.get("video_every_n_steps", 1),
        video_scale=environment_config.get("video_scale"),
        video_size=environment_config.get("video_size", "1280x1024"),
        env_resolution=environment_config.get("env_resolution"),
        max_video_frames=environment_config.get("max_video_frames"),
        seed=environment_config.get("seed", profile.seed),
        initial_inventory=initial_inventory,
        start_time=start_time,
        weather=environment_config.get("weather", profile.weather),
        allow_time=environment_config.get("allow_time", profile_metadata.get("allow_time", True)),
        allow_spawning=environment_config.get("allow_spawning", profile_metadata.get("allow_spawning", True)),
        start_position=environment_config.get("start_position", profile_metadata.get("start_position")),
        world_decorator=world_decorator,
        known_blocks=environment_config.get("known_blocks", profile_metadata.get("known_blocks")),
    )


class _ProfiledMineRLEnvironmentAdapter:
    def __init__(self, profiles: Mapping[str, Any], environment_config: Mapping[str, Any]) -> None:
        self.profiles = profiles
        self.environment_config = environment_config
        self._environment: MineRLEnvironmentAdapter | None = None

    def reset(self, profile_id: str) -> ObservationSnapshot:
        try:
            profile = self.profiles[profile_id]
        except KeyError as exc:
            raise ValueError(f"Unknown environment profile: {profile_id}") from exc
        retries = self.environment_config.get("reset_retries", 0)
        startup_delay = self.environment_config.get("reset_startup_delay_seconds", 0)
        if type(retries) is not int or retries < 0:
            raise ValueError("environment.reset_retries must be a non-negative integer")
        if isinstance(startup_delay, bool) or not isinstance(startup_delay, (int, float)) or startup_delay < 0:
            raise ValueError("environment.reset_startup_delay_seconds must be non-negative")
        last_error = None
        for attempt in range(retries + 1):
            self.close()
            self._environment = _build_minerl_environment(profile, self.environment_config)
            try:
                if startup_delay:
                    time.sleep(float(startup_delay))
                return self._environment.reset(profile_id)
            except (TypeError, ConnectionError, OSError) as exc:
                last_error = exc
                self.close()
                if attempt >= retries:
                    raise
        raise RuntimeError("unreachable MineRL reset retry loop") from last_error

    def observe(self) -> ObservationSnapshot:
        if self._environment is None:
            raise ExternalAdapterError("Profiled MineRL environment has not been reset.")
        return self._environment.observe()

    def step(self, action: Mapping[str, Any]):
        if self._environment is None:
            raise ExternalAdapterError("Profiled MineRL environment has not been reset.")
        return self._environment.step(action)

    def close(self) -> None:
        if self._environment is not None:
            environment = self._environment
            self._environment = None
            environment.close()


def _cmd_benchmark(catalog_dir: str, profile_dir: str | None, output_dir: str) -> int:
    catalog = load_catalog_dir(Path(catalog_dir))
    profiles = load_profile_catalog(Path(profile_dir or catalog_dir))
    validate_profile_references(catalog, profiles)

    output_root = Path(output_dir)
    chain_payloads = []
    for chain_id in sorted(catalog.chains):
        compiled = compile_chain(catalog, chain_id)
        profile = profiles[compiled.chain.environment_profile]
        environment = ScriptedEnvironmentAdapter(_dry_run_snapshots(compiled))
        agent = ScriptedAgentAdapter()
        report = run_compiled_chain(compiled, environment, agent, environment_profile=profile.id)
        report_with_metadata = type(report)(
            chain_id=report.chain_id,
            completed=report.completed,
            stages=report.stages,
            metadata={
                **dict(report.metadata),
                "environment_profile": profile.id,
                "env_id": profile.env_id,
                "synthetic": True,
                "environment": {"kind": "scripted"},
                "agent": {"kind": "scripted"},
            },
        )
        report_path = write_report_json(report_with_metadata, output_root / f"{chain_id}.json")
        chain_payloads.append(
            {
                "chain_id": chain_id,
                "completed": report_with_metadata.completed,
                "report_path": str(report_path),
                "metrics": dict(report_with_metadata.metrics()),
            }
        )

    summary = dict(_benchmark_summary_payload(catalog, chain_payloads))
    summary["synthetic"] = True
    summary_path = output_root / "summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _suite_chain_ids(
    catalog: Any,
    configured_chain_ids: Sequence[str],
    configured_split_ids: Sequence[str],
) -> Sequence[str]:
    if configured_chain_ids and configured_split_ids:
        raise ValueError("Suite config may specify chain_ids or split_ids, not both.")
    if configured_chain_ids:
        missing = [chain_id for chain_id in configured_chain_ids if chain_id not in catalog.chains]
        if missing:
            raise ValueError(f"Unknown chain ids in suite config: {', '.join(missing)}")
        return tuple(configured_chain_ids)
    if configured_split_ids:
        chain_ids = []
        for split_id in configured_split_ids:
            if split_id not in catalog.splits:
                raise ValueError(f"Unknown split id in suite config: {split_id}")
            for chain_id in catalog.splits[split_id].chain_ids:
                if chain_id not in chain_ids:
                    chain_ids.append(chain_id)
        return tuple(chain_ids)
    return tuple(sorted(catalog.chains))


def _benchmark_summary_payload(
    catalog: Any,
    chain_payloads: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any]:
    completed_chains = sum(1 for item in chain_payloads if item["completed"])
    return {
        "completed": completed_chains == len(chain_payloads),
        "chains": list(chain_payloads),
        "splits": _benchmark_split_summary(catalog, chain_payloads),
        "summary": {
            "chain_count": len(chain_payloads),
            "completed_chains": completed_chains,
            "completion_rate": completed_chains / len(chain_payloads) if chain_payloads else 0.0,
            "total_steps": sum(item["metrics"]["total_steps"] for item in chain_payloads),
            "deaths": _efficiency_sum(chain_payloads, "deaths"),
            "recovery_events": _efficiency_sum(chain_payloads, "recovery_events"),
            "resource_waste_events": _efficiency_sum(chain_payloads, "resource_waste_events"),
            "task_success_rate": _weighted_average_metric(chain_payloads, "passed_stages", "stage_count"),
            "weighted_graph_progress": _weighted_average_nested_metric(
                chain_payloads,
                "graph_progress",
                "execution_edge_weight_completed",
                "execution_edge_weight_total",
            ),
            "verified_milestone_progress": _weighted_average_nested_metric(
                chain_payloads,
                "milestone_progress",
                "completed_count",
                "eligible_count",
            ),
        },
    }


def _benchmark_split_summary(catalog: Any, chain_payloads: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]:
    by_chain = {item["chain_id"]: item for item in chain_payloads}
    payload = {}
    for split_id, split in sorted(catalog.splits.items()):
        split_chains = [by_chain[chain_id] for chain_id in split.chain_ids if chain_id in by_chain]
        payload[split_id] = {
            "name": split.name,
            "purpose": split.purpose,
            "chain_count": len(split_chains),
            "task_count": len(split.task_ids),
            "completed_chains": sum(1 for item in split_chains if item["completed"]),
            "task_success_rate": _weighted_average_metric(split_chains, "passed_stages", "stage_count"),
            "weighted_graph_progress": _weighted_average_nested_metric(
                split_chains,
                "graph_progress",
                "execution_edge_weight_completed",
                "execution_edge_weight_total",
            ),
            "verified_milestone_progress": _weighted_average_nested_metric(
                split_chains,
                "milestone_progress",
                "completed_count",
                "eligible_count",
            ),
            "total_steps": sum(item["metrics"]["total_steps"] for item in split_chains),
            "deaths": _efficiency_sum(split_chains, "deaths"),
            "recovery_events": _efficiency_sum(split_chains, "recovery_events"),
            "resource_waste_events": _efficiency_sum(split_chains, "resource_waste_events"),
        }
    return payload


def _efficiency_sum(
    chain_payloads: Sequence[Mapping[str, Any]],
    key: str,
) -> int:
    return sum(int(item["metrics"].get("efficiency", {}).get(key, 0) or 0) for item in chain_payloads)


def _weighted_average_metric(
    chain_payloads: Sequence[Mapping[str, Any]],
    numerator_key: str,
    denominator_key: str,
) -> float:
    numerator = sum(item["metrics"].get(numerator_key, 0) for item in chain_payloads)
    denominator = sum(item["metrics"].get(denominator_key, 0) for item in chain_payloads)
    return numerator / denominator if denominator else 0.0


def _weighted_average_nested_metric(
    chain_payloads: Sequence[Mapping[str, Any]],
    parent_key: str,
    numerator_key: str,
    denominator_key: str,
) -> float:
    numerator = sum(item["metrics"].get(parent_key, {}).get(numerator_key, 0) for item in chain_payloads)
    denominator = sum(item["metrics"].get(parent_key, {}).get(denominator_key, 0) for item in chain_payloads)
    return numerator / denominator if denominator else 0.0


def _build_agent(agent_config: Mapping[str, Any]):
    kind = agent_config.get("kind")
    if kind == "scripted":
        return ScriptedAgentAdapter(action=agent_config.get("action"))
    if kind == "external":
        return ExternalPolicyAgentAdapter(
            agent_label=agent_config.get("agent_label", "external"),
            runtime_module=agent_config.get("runtime_module"),
            policy_entrypoint=agent_config.get("policy_entrypoint"),
            action_adapter_entrypoint=agent_config.get("action_adapter_entrypoint"),
            device=agent_config.get("device", "cpu"),
            prompt_template=agent_config.get("prompt_template", "{instruction}"),
            policy_kwargs=agent_config.get("policy_kwargs"),
        )
    raise ValueError(f"Unsupported agent kind: {kind}; use 'scripted' or 'external'.")


def _seed_agent(seed: int | None) -> None:
    if seed is None:
        return
    if type(seed) is not int or seed < 0:
        raise ValueError("agent.random_seed must be a non-negative integer")
    random.seed(seed)
    for module_name in ("numpy", "torch"):
        if find_spec(module_name) is None:
            continue
        if module_name == "numpy":
            import numpy
            numpy.random.seed(seed)
        else:
            import torch
            torch.manual_seed(seed)
            if torch.cuda.is_available():
                torch.cuda.manual_seed_all(seed)


def _execute_chain(catalog, profiles, chain_id, environment_config, agent_config,
                   *, profile_id=None, max_stage_steps=None, per_stage_profiles=True):
    compiled = compile_chain(catalog, chain_id)
    if max_stage_steps is not None:
        compiled = _with_stage_step_limit(compiled, max_stage_steps)
    profile = profiles[profile_id or compiled.chain.environment_profile]
    if type(environment_config.get("seed", profile.seed)) is not int:
        raise ValueError("environment.seed must be an integer")
    per_stage_profiles = bool(environment_config.get("per_stage_profiles", per_stage_profiles))
    _seed_agent(agent_config.get("random_seed"))
    agent = _build_agent(agent_config)
    environment = _build_environment(environment_config, compiled, profile, profiles,
                                     per_stage_profiles=per_stage_profiles)
    # Ensure failed policy/environment resets also release the runtime.
    try:
        report = run_compiled_chain(compiled, environment, agent,
                                    environment_profile=profile.id,
                                    per_stage_profiles=per_stage_profiles)
    except Exception:
        environment.close()
        raise
    return replace(report, metadata={
        **dict(report.metadata),
        "environment_profile": profile.id,
        "env_id": environment_config.get("env_id", profile.env_id),
        "environment": dict(environment_config),
        "agent": dict(agent_config),
        "max_stage_steps": max_stage_steps,
        "per_stage_profiles": per_stage_profiles,
        "synthetic": environment_config.get("kind") == "scripted",
    })


def _cmd_run_config(config_path: str) -> int:
    config = load_run_config(config_path)
    catalog = load_catalog_dir(config.catalog_dir)
    profiles = load_profile_catalog(config.profile_dir)
    validate_profile_references(catalog, profiles)
    report = _execute_chain(catalog, profiles, config.chain_id, config.environment,
                            config.agent, profile_id=config.environment_profile,
                            max_stage_steps=config.max_stage_steps)
    write_report_json(report, config.output_path)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_run_suite_config(config_path: str) -> int:
    config = load_suite_config(config_path)
    catalog = load_catalog_dir(config.catalog_dir)
    profiles = load_profile_catalog(config.profile_dir)
    validate_profile_references(catalog, profiles)
    chain_ids = _suite_chain_ids(catalog, config.chain_ids, config.split_ids)
    if len(set(chain_ids)) != len(chain_ids):
        raise ValueError("Duplicate chain_ids would overwrite reports and double-count scores.")
    output_root = Path(config.output_dir)
    payloads = []
    for chain_id in chain_ids:
        report = _execute_chain(catalog, profiles, chain_id, config.environment, config.agent,
                                max_stage_steps=config.max_stage_steps,
                                per_stage_profiles=config.per_stage_profiles)
        path = write_report_json(report, output_root / f"{chain_id}.json")
        payloads.append({"chain_id": chain_id, "completed": report.completed,
                         "report_path": str(path), "metrics": dict(report.metrics())})
    summary = dict(_benchmark_summary_payload(catalog, payloads))
    summary["synthetic"] = config.environment.get("kind") == "scripted"
    summary["config"] = {"environment": dict(config.environment), "agent": dict(config.agent),
                         "chain_ids": list(chain_ids), "split_ids": list(config.split_ids),
                         "max_stage_steps": config.max_stage_steps,
                         "per_stage_profiles": config.per_stage_profiles}
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                              encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mcbench", description="MC-EvoBench benchmark core")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate catalog, profiles and chain dependencies.")
    validate.add_argument("catalog_dir")
    dry_run = commands.add_parser("dry-run", help="Synthetic chain check; not an agent evaluation.")
    dry_run.add_argument("catalog_dir")
    dry_run.add_argument("chain_id")
    benchmark = commands.add_parser("benchmark", help="Synthetic check of all official chains.")
    benchmark.add_argument("catalog_dir")
    benchmark.add_argument("--profile-dir")
    benchmark.add_argument("--output-dir", default="runs/benchmark")
    for name in ("run-config", "run-suite-config"):
        command = commands.add_parser(name, help="Run benchmark evaluation from a JSON configuration.")
        command.add_argument("config_path")
    commands.add_parser("doctor", help="Check optional runtime dependencies; does not start Minecraft.")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "validate":
            return _cmd_validate(args.catalog_dir)
        if args.command == "dry-run":
            return _cmd_dry_run(args.catalog_dir, args.chain_id)
        if args.command == "benchmark":
            return _cmd_benchmark(args.catalog_dir, args.profile_dir, args.output_dir)
        if args.command == "run-config":
            return _cmd_run_config(args.config_path)
        if args.command == "run-suite-config":
            return _cmd_run_suite_config(args.config_path)
        if args.command == "doctor":
            payload = {name: find_spec(name) is not None for name in ("gym", "minerl", "numpy")}
            payload["java"] = shutil.which("java") is not None
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
    except (ExternalAdapterError, ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbench.cli import main

ROOT = Path(__file__).resolve().parents[1]
CATALOG_DIR = ROOT / 'benchmarks/v1'


def _write_config(tmp_path, **extra):
    payload = {
        'catalog_dir': str(CATALOG_DIR),
        'profile_dir': str(CATALOG_DIR),
        'environment': {'kind': 'scripted'},
        'agent': {'kind': 'scripted'},
        **extra,
    }
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(payload), encoding='utf-8')
    return str(path)


def test_run_config_writes_synthetic_report(tmp_path, capsys):
    output = tmp_path / 'chain.json'
    path = _write_config(tmp_path, chain_id='cross_domain_safe_night',
                         environment_profile='forest_progression', output_path=str(output))
    assert main(['run-config', path]) == 0
    report = json.loads(output.read_text())
    assert report == json.loads(capsys.readouterr().out)
    assert report['completed']
    assert report['metadata']['synthetic'] is True


def test_suite_selects_formal_splits_and_writes_individual_reports(tmp_path, capsys):
    output = tmp_path / 'suite'
    path = _write_config(tmp_path, output_dir=str(output),
                         split_ids=['core_progression', 'transfer', 'supplementary_diversity'],
                         per_stage_profiles=False)
    assert main(['run-suite-config', path]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['summary']['chain_count'] == 12
    assert report['completed'] is True
    assert report['synthetic'] is True
    assert report['splits']['calibration_and_probe']['chain_count'] == 0
    assert len(list(output.glob('*.json'))) == 13
    assert json.loads((output / 'summary.json').read_text()) == report


@pytest.mark.parametrize('selection', [
    {'chain_ids': ['missing_chain']},
    {'split_ids': ['missing_split']},
    {'chain_ids': ['collect_log_smoke'], 'split_ids': ['core_progression']},
    {'chain_ids': ['collect_log_smoke', 'collect_log_smoke']},
])
def test_invalid_suite_selection_creates_no_reports(tmp_path, capsys, selection):
    output = tmp_path / 'suite'
    path = _write_config(tmp_path, output_dir=str(output), **selection)
    assert main(['run-suite-config', path]) == 1
    assert 'error' in json.loads(capsys.readouterr().err)
    assert not output.exists()


def test_generic_policy_connects_without_method_dependencies(tmp_path, capsys, monkeypatch):
    import sys
    calls = []

    class Policy:
        def act(self, observation, instruction, **kwargs):
            calls.append(instruction)
            return {'__adapter_action__': 'noop'}

    monkeypatch.setitem(sys.modules, 'example_policy', SimpleNamespace(create_policy=lambda: Policy()))
    output = tmp_path / 'external.json'
    path = _write_config(tmp_path, chain_id='collect_log_smoke', environment_profile='forest_day',
                         output_path=str(output),
                         agent={'kind': 'external', 'policy_entrypoint': 'example_policy:create_policy'})
    assert main(['run-config', path]) == 0
    assert json.loads(capsys.readouterr().out)['completed']
    assert calls


def test_rejects_unknown_config_fields(tmp_path, capsys):
    path = _write_config(tmp_path, chain_id='collect_log_smoke', environment_profile='forest_day',
                         output_path=str(tmp_path / 'report.json'), unexpected={})
    assert main(['run-config', path]) == 1
    assert 'Unsupported configuration fields' in capsys.readouterr().err


def test_runtime_is_closed_when_agent_reset_fails(tmp_path, capsys, monkeypatch):
    from mcbench import cli
    closed = []

    class Agent:
        def reset(self, chain):
            raise ValueError('policy reset failed')

    monkeypatch.setattr(cli, '_build_agent', lambda config: Agent())
    monkeypatch.setattr(cli, '_build_environment', lambda *args, **kwargs:
                        SimpleNamespace(close=lambda: closed.append(True)))
    path = _write_config(tmp_path, chain_id='collect_log_smoke', environment_profile='forest_day',
                         output_path=str(tmp_path / 'report.json'))
    assert main(['run-config', path]) == 1
    assert closed == [True]
    assert 'policy reset failed' in capsys.readouterr().err


def test_cli_validate_reports_catalog_summary(capsys):
    exit_code = main(["validate", str(CATALOG_DIR)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["chains"] >= 3
    assert payload["tasks"] >= 10
    assert payload["mission_events"] >= 4
    assert payload["observation_tracks"]["native_perception"] >= 1
    assert payload["observation_tracks"]["structured_state"] >= 1
    assert payload["profiles"] >= 4
    assert payload["splits"] >= 4


def test_cli_dry_run_emits_completed_report(capsys):
    exit_code = main(
        [
            "dry-run",
            str(CATALOG_DIR),
            "cross_domain_safe_night",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["chain_id"] == "cross_domain_safe_night"
    assert payload["completed"] is True
    assert len(payload["stages"]) == 10
    assert payload["metrics"]["completion_rate"] == 1.0


def test_cli_benchmark_runs_all_official_chains_and_writes_summary(tmp_path, capsys):
    exit_code = main(
        [
            "benchmark",
            str(CATALOG_DIR),
            "--output-dir",
            str(tmp_path / "benchmark"),
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["completed"] is True
    assert payload["summary"]["chain_count"] >= 3
    assert payload["summary"]["completion_rate"] == 1.0
    assert payload["summary"]["task_success_rate"] == 1.0
    assert payload["summary"]["weighted_graph_progress"] == 1.0
    assert payload["summary"]["deaths"] == 0
    assert payload["summary"]["recovery_events"] == 0
    assert payload["summary"]["resource_waste_events"] == 0
    assert "core_progression" in payload["splits"]
    assert payload["splits"]["core_progression"]["task_success_rate"] == 1.0
    assert payload["splits"]["core_progression"]["weighted_graph_progress"] == 1.0
    assert payload["splits"]["core_progression"]["deaths"] == 0
    assert payload["splits"]["core_progression"]["recovery_events"] == 0
    assert payload["splits"]["core_progression"]["resource_waste_events"] == 0
    assert (tmp_path / "benchmark" / "summary.json").exists()

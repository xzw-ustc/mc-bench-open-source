import json

from mcbench.reporting import ChainRunReport, StageReport, write_report_json


def test_write_report_json_persists_machine_readable_output(tmp_path):
    report = ChainRunReport(
        chain_id="cross_domain_safe_night",
        completed=True,
        stages=(StageReport(task_id="collect_log", status="passed", steps=1, failures=()),),
        metadata={"profile": "forest_progression"},
    )
    output = tmp_path / "report.json"

    write_report_json(report, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["chain_id"] == "cross_domain_safe_night"
    assert payload["metadata"]["profile"] == "forest_progression"
    assert payload["metrics"]["completion_rate"] == 1.0
    assert payload["metrics"]["task_success_rate"] == 1.0
    assert payload["metrics"]["weighted_graph_progress"] == 1.0
    assert "efficiency" in payload["metrics"]
    assert payload["metrics"]["total_steps"] == 1

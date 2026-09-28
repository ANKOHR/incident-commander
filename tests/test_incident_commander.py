from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from incident_commander.core import (
    HONESTY,
    generate_fixtures,
    ingest,
    json_bytes,
    rollback_options,
    score_causes,
    write_ingest,
)


ROOT = Path(__file__).resolve().parents[1]


def make_case(path: Path) -> Path:
    generate_fixtures(path)
    return path


def test_fixture_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first = make_case(tmp_path / "first")
    second = make_case(tmp_path / "second")
    first_files = sorted(item.relative_to(first) for item in first.rglob("*") if item.is_file())
    second_files = sorted(item.relative_to(second) for item in second.rglob("*") if item.is_file())
    assert first_files == second_files
    assert {name: (first / name).read_bytes() for name in first_files} == {
        name: (second / name).read_bytes() for name in second_files
    }


def test_ingest_counts_and_normalized_event_shape(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    events = ingest(case)
    assert len(events) == 12
    assert Counter(event["source"] for event in events) == {"log": 6, "alert": 2, "deploy": 2, "commit": 2}
    assert all({"timestamp", "source", "type", "severity", "raw_reference"} <= event.keys() for event in events)
    assert all(set(event["raw_reference"]) == {"file", "line"} for event in events)


def test_timeline_is_ordered_and_every_citation_resolves(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    events = ingest(case)
    timestamps = [event["timestamp"] for event in events]
    assert timestamps == sorted(timestamps)
    for event in events:
        ref = event["raw_reference"]
        source = case / ref["file"]
        lines = source.read_text(encoding="utf-8").splitlines()
        assert 1 <= ref["line"] <= len(lines)


def test_ingest_json_is_byte_identical_for_same_fixtures(tmp_path: Path) -> None:
    first, second = make_case(tmp_path / "first"), make_case(tmp_path / "second")
    first_events = write_ingest(first, tmp_path / "work1")
    second_events = write_ingest(second, tmp_path / "work2")
    assert (first / "normalized-events.json").read_bytes() == (second / "normalized-events.json").read_bytes()
    assert json_bytes(first_events) == json_bytes(second_events)


def test_planted_config_change_ranks_first_with_expected_citations(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    first_run = score_causes(case)
    second_run = score_causes(case)
    assert first_run == second_run
    assert json_bytes(first_run) == json_bytes(second_run)
    assert first_run[0]["id"] == "config_change"
    assert first_run[0]["score"] == 10
    assert {
        "commits/commits.jsonl:2",
        "deploys/deploys.jsonl:2",
        "logs/app.log:5",
        "alerts/alerts.jsonl:1",
    } <= set(first_run[0]["evidence"])


def test_rollback_targets_diffs_and_migration_risks(tmp_path: Path) -> None:
    case = make_case(tmp_path / "case")
    options = rollback_options(case)
    assert [(item["deployed_version"], item["rollback_target"]) for item in options] == [
        ("v2.4.0", "v2.3.9"),
        ("v2.4.1", "v2.4.0"),
    ]
    assert all(item["diff_summary"] for item in options)
    assert "No post-deploy data migration" in options[0]["risk_notes"]
    assert "schema migration ran" in options[1]["risk_notes"]
    assert "10:12:00Z" in options[1]["risk_notes"]
    assert "deploys/deploys.jsonl:2" in options[1]["evidence"]


def test_cli_audit_records_each_run_and_honesty_banner(tmp_path: Path) -> None:
    case = tmp_path / "fictional"
    audit_file = tmp_path / "ic-audit.jsonl"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    def run(*args: str) -> str:
        completed = subprocess.run(
            [sys.executable, "-m", "incident_commander", *args],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "INCIDENT COMMANDER | SYNTHETIC FICTIONAL SCENARIO" in completed.stdout
        assert HONESTY in completed.stdout
        return completed.stdout

    run("fixtures", "--out", str(case))
    run("ingest", str(case))
    run("timeline")
    run("causes")
    run("rollback")
    run("report", "--format", "md")
    run("report", "--format", "html")
    audit_output = run("audit")
    rows = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 8
    assert [row["command"] for row in rows[:7]] == [
        "fixtures", "ingest", "timeline", "causes", "rollback", "report --format md", "report --format html"
    ]
    assert rows[0]["summary"]["file_count"] == 6
    assert rows[1]["summary"]["event_count"] == 12
    assert audit_output.count('"command":') == 7
    assert rows[7]["summary"]["entries_displayed"] == 7
    assert (case / "incident-report.md").is_file()
    assert (case / "incident-report.html").is_file()


def test_cli_help_and_argument_errors_are_audited(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    for argv, expected_code in [(["--help"], 0), (["ingest"], 2)]:
        completed = subprocess.run(
            [sys.executable, "-m", "incident_commander", *argv],
            cwd=tmp_path,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == expected_code
        assert "INCIDENT COMMANDER | SYNTHETIC FICTIONAL SCENARIO" in completed.stdout
        assert HONESTY in completed.stdout
    rows = [json.loads(line) for line in (tmp_path / "ic-audit.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["command"] for row in rows] == ["help", "ingest"]
    assert [row["summary"]["status"] for row in rows] == ["help", "argument_error"]


def test_reports_include_full_honesty_boundary(tmp_path: Path) -> None:
    from incident_commander.core import write_report

    case = make_case(tmp_path / "case")
    markdown = write_report(case, "md").read_text(encoding="utf-8")
    html = write_report(case, "html").read_text(encoding="utf-8")
    assert HONESTY in markdown
    assert HONESTY in html
    assert "Merged timeline" in markdown and "Ranked heuristic causes" in markdown and "Rollback options" in markdown

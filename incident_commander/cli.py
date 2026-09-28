"""Argparse command line interface. Every valid command is recorded in the local audit log."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import (
    HEADER,
    HONESTY,
    generate_fixtures,
    ingest,
    rollback_options,
    score_causes,
    timeline_text,
    write_ingest,
    write_json,
    write_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incident-commander",
        description=f"Deterministic incident analysis for fictional data. {HONESTY}",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fixtures = commands.add_parser("fixtures", help="generate the synthetic fictional scenario")
    fixtures.add_argument("--out", type=Path, required=True, help="output directory")

    ingest_parser = commands.add_parser("ingest", help="parse the four source types into normalized events")
    ingest_parser.add_argument("directory", type=Path)

    for name, help_text in (
        ("timeline", "print and export the merged incident timeline"),
        ("causes", "rank likely causes using documented evidence heuristics"),
        ("rollback", "show rollback targets, diffs, and risk notes"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--dir", dest="directory", type=Path, help="incident directory; defaults to the last ingested directory")

    report = commands.add_parser("report", help="write the complete report")
    report.add_argument("--format", choices=("md", "html"), required=True)
    report.add_argument("--dir", dest="directory", type=Path, help="incident directory; defaults to the last ingested directory")

    commands.add_parser("audit", help="show the local audit log")
    return parser


def _active_case(directory: Path | None, cwd: Path) -> Path:
    if directory is not None:
        return directory.resolve()
    state_path = cwd / "ic-state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return Path(state["case_dir"]).resolve()
    default = cwd / "fixtures" / "synthetic-incident"
    if default.is_dir():
        return default.resolve()
    raise FileNotFoundError("No incident selected. Run 'incident-commander ingest <dir>' first or pass --dir.")


def _print_events(events: list[dict[str, Any]], case_dir: Path) -> str:
    write_json(case_dir / "timeline.json", events)
    body = timeline_text(events)
    print(body or "No events found.")
    return body


def _print_causes(causes: list[dict[str, Any]], case_dir: Path) -> str:
    write_json(case_dir / "causes.json", causes)
    lines = []
    for index, item in enumerate(causes, 1):
        evidence = ", ".join(item["evidence"]) if item["evidence"] else "none"
        lines.append(f"{index}. {item['cause']} | score={item['score']} | evidence: {evidence}")
    body = "\n".join(lines)
    print(body)
    return body


def _print_rollbacks(options: list[dict[str, Any]], case_dir: Path) -> str:
    write_json(case_dir / "rollback-options.json", options)
    lines = []
    for item in options:
        lines.append(
            f"{item['deployed_version']} -> {item['rollback_target']} | diff: {item['diff_summary']} | "
            f"risk: {item['risk_notes']} | evidence: {', '.join(item['evidence'])}"
        )
    body = "\n".join(lines)
    print(body or "No deploys found.")
    return body


def _audit_rows(audit_path: Path) -> list[dict[str, Any]]:
    if not audit_path.exists():
        return []
    rows = []
    for line_no, line in enumerate(audit_path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid audit JSON at {audit_path.name}:{line_no}") from exc
    return rows


def _execute(args: argparse.Namespace, cwd: Path) -> tuple[str, dict[str, Any], str | None]:
    command = args.command
    if command == "fixtures":
        out_dir = args.out.resolve()
        files = generate_fixtures(out_dir)
        print(f"Generated {len(files)} deterministic fictional files in {out_dir}")
        return "fixtures", {"files": files, "file_count": len(files)}, str(out_dir)
    if command == "ingest":
        case_dir = args.directory.resolve()
        events = write_ingest(case_dir, cwd)
        counts = dict(sorted(Counter(event["source"] for event in events).items()))
        print(f"Ingested {len(events)} events from {case_dir}; counts: {json.dumps(counts, sort_keys=True)}")
        print(f"Normalized events: {case_dir / 'normalized-events.json'}")
        return "ingest", {"event_count": len(events), "counts": counts, "files": ["normalized-events.json"]}, str(case_dir)
    if command == "audit":
        rows = _audit_rows(cwd / "ic-audit.jsonl")
        body = json.dumps(rows, ensure_ascii=False, indent=2, sort_keys=True)
        print(body if rows else "No prior commands recorded.")
        input_dir = None
        state_path = cwd / "ic-state.json"
        if state_path.exists():
            input_dir = json.loads(state_path.read_text(encoding="utf-8")).get("case_dir")
        return "audit", {"entries_displayed": len(rows)}, input_dir

    case_dir = _active_case(getattr(args, "directory", None), cwd)
    if command == "timeline":
        events = ingest(case_dir)
        body = _print_events(events, case_dir)
        return "timeline", {"event_count": len(events), "files": ["timeline.json"]}, str(case_dir)
    if command == "causes":
        causes = score_causes(case_dir)
        body = _print_causes(causes, case_dir)
        return "causes", {"candidate_count": len(causes), "ranked_first": causes[0]["id"] if causes else None, "files": ["causes.json"]}, str(case_dir)
    if command == "rollback":
        options = rollback_options(case_dir)
        body = _print_rollbacks(options, case_dir)
        return "rollback", {"option_count": len(options), "files": ["rollback-options.json"]}, str(case_dir)
    if command == "report":
        path = write_report(case_dir, args.format)
        print(f"Wrote {path}")
        return f"report --format {args.format}", {"files": [path.name], "format": args.format}, str(case_dir)
    raise ValueError(f"Unsupported command: {command}")


def _append_audit(path: Path, command: str, input_dir: str | None, summary: dict[str, Any], error: str | None = None) -> None:
    record: dict[str, Any] = {
        "command": command,
        "input_dir": input_dir,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "summary": summary,
    }
    if error:
        record["error"] = error
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def main(argv: list[str] | None = None) -> int:
    invocation = list(sys.argv[1:] if argv is None else argv)
    cwd = Path.cwd().resolve()
    print(HEADER)
    print(HONESTY)
    parser = _parser()
    audit_path = cwd / "ic-audit.jsonl"
    try:
        args = parser.parse_args(invocation)
    except SystemExit as exc:
        choices = {"fixtures", "ingest", "timeline", "causes", "rollback", "report", "audit"}
        command = next((token for token in invocation if token in choices), None)
        if command is None:
            command = "help" if "-h" in invocation or "--help" in invocation else "argument_error"
        _append_audit(audit_path, command, None, {"status": "help" if exc.code == 0 else "argument_error", "exit_code": exc.code})
        return int(exc.code or 0)
    command_name = args.command
    audit_input: str | None = None
    try:
        command_name, summary, audit_input = _execute(args, cwd)
        _append_audit(audit_path, command_name, audit_input, summary)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        _append_audit(audit_path, command_name, audit_input or str(getattr(args, "directory", "") or "") or None, {"status": "error"}, str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

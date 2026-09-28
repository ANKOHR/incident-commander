"""Fixture creation, ingestion, scoring, timeline, rollback, and reports."""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIXTURE_SEED = 417
HONESTY = (
    "HONESTY BOUNDARY: All incident data is synthetic and fictional. Cause rankings "
    "are heuristic scoring over structured evidence, not an AI diagnosis of a real "
    "production outage, incident-response experience, or on-call expertise."
)
HEADER = "INCIDENT COMMANDER | SYNTHETIC FICTIONAL SCENARIO"
LOG_RE = re.compile(
    r"^(?P<timestamp>\S+) (?P<level>INFO|WARN|ERROR) "
    r"(?P<component>[A-Za-z0-9_.-]+) (?P<message>.*)$"
)
SOURCE_FILES = (
    ("logs/app.log", "log"),
    ("alerts/alerts.jsonl", "alert"),
    ("deploys/deploys.jsonl", "deploy"),
    ("commits/commits.jsonl", "commit"),
)


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def fixture_files() -> dict[str, bytes]:
    """Return all fixed scenario source files. Seed is documented; no runtime randomness is used."""
    logs = "\n".join(
        [
            "2026-04-14T09:40:10Z INFO synthetic_payments service_ready version=v2.4.0",
            "2026-04-14T10:05:00Z INFO synthetic_payments deploy_started version=v2.4.1 commit=d4e5f6a",
            "2026-04-14T10:05:30Z INFO synthetic_payments request_rate=1200 baseline=400 requests_per_minute",
            "2026-04-14T10:06:10Z WARN synthetic_payments p95_latency_ms=2100 threshold_ms=500",
            "2026-04-14T10:06:42Z ERROR synthetic_payments invalid config: strict_mode rejected legacy payload",
            "2026-04-14T10:07:11Z ERROR synthetic_payments payment requests failed code=PAYLOAD_SCHEMA_MISMATCH",
        ]
    ) + "\n"
    records = {
        "alerts/alerts.jsonl": [
            {
                "timestamp": "2026-04-14T10:06:20Z",
                "name": "PaymentErrorRateHigh",
                "state": "firing",
                "severity": "critical",
                "category": "application",
                "description": "Payment errors exceeded the fictional threshold after release.",
            },
            {
                "timestamp": "2026-04-14T10:30:00Z",
                "name": "PaymentErrorRateHigh",
                "state": "resolved",
                "severity": "info",
                "category": "application",
                "description": "Fictional payment error rate returned below threshold.",
            },
        ],
        "deploys/deploys.jsonl": [
            {
                "timestamp": "2026-04-14T09:40:00Z",
                "commit_sha": "a1b2c3d",
                "version": "v2.4.0",
                "previous_version": "v2.3.9",
                "change_summary": "Routine fictional payments release.",
                "diff_summary": "Payment service maintenance; no configuration changes.",
                "migration_applied_at": None,
                "risk_notes": "No post-deploy data migration is recorded in this fixture.",
            },
            {
                "timestamp": "2026-04-14T10:05:00Z",
                "commit_sha": "d4e5f6a",
                "version": "v2.4.1",
                "previous_version": "v2.4.0",
                "change_summary": "Enable strict payment payload configuration.",
                "diff_summary": "config/payments.yaml: strict_mode false -> true; legacy payload parser bypassed.",
                "migration_applied_at": "2026-04-14T10:12:00Z",
                "risk_notes": "A schema migration ran at 10:12 UTC; confirm backward compatibility before rollback.",
            },
        ],
        "commits/commits.jsonl": [
            {
                "timestamp": "2026-04-14T09:39:00Z",
                "commit_sha": "a1b2c3d",
                "author": "Fixture Author",
                "message": "Release v2.4.0 payments maintenance",
                "files_changed": ["src/payments.py"],
                "category": "maintenance",
                "breaking_change": False,
                "diff_summary": "Refactor health check without behavior changes.",
            },
            {
                "timestamp": "2026-04-14T10:04:00Z",
                "commit_sha": "d4e5f6a",
                "author": "Fixture Author",
                "message": "Enable strict payment payload configuration",
                "files_changed": ["config/payments.yaml"],
                "category": "config",
                "breaking_change": True,
                "diff_summary": "Set strict_mode from false to true; legacy payloads are rejected.",
            },
        ],
    }
    result = {"logs/app.log": logs.encode("utf-8")}
    for name, rows in records.items():
        labelled_rows = ({"scenario_label": "FICTIONAL SYNTHETIC DATA", **row} for row in rows)
        result[name] = ("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in labelled_rows)).encode("utf-8")
    result["SCENARIO.txt"] = (
        "FICTIONAL SYNTHETIC DATA ONLY\n"
        f"Documented fixture seed: {FIXTURE_SEED}\n"
        "Fixed values are used, with no runtime randomness or external data.\n"
        "Planted cause: v2.4.1 enabled strict_mode and rejected legacy payment payloads.\n"
    ).encode("utf-8")
    result["incident.json"] = json_bytes(
        {
            "fictional": True,
            "scenario_seed": FIXTURE_SEED,
            "incident_start": "2026-04-14T09:30:00Z",
            "incident_end": "2026-04-14T10:30:00Z",
            "description": "Synthetic payment errors after a breaking configuration deploy.",
        }
    )
    return result


def generate_fixtures(out_dir: Path) -> list[str]:
    out_dir = out_dir.resolve()
    files = fixture_files()
    for relative, data in files.items():
        target = out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return sorted(files)


def _event(timestamp: str, source: str, event_type: str, severity: str, path: str, line: int, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "source": source,
        "type": event_type,
        "severity": severity,
        "raw_reference": {"file": path, "line": line},
        "details": details,
    }


def _jsonl(path: Path, relative: str, source: str) -> list[dict[str, Any]]:
    events = []
    for line_no, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            row = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at {relative}:{line_no}: {exc}") from exc
        if not isinstance(row, dict) or "timestamp" not in row:
            raise ValueError(f"Expected an object with timestamp at {relative}:{line_no}")
        event_type = "alert_" + str(row.get("state", "unknown")) if source == "alert" else source
        severity = str(row.get("severity", "info" if source != "alert" else "unknown"))
        details = {key: value for key, value in row.items() if key != "timestamp"}
        events.append(_event(str(row["timestamp"]), source, event_type, severity, relative, line_no, details))
    return events


def _sort_key(event: dict[str, Any]) -> tuple[datetime, str, int]:
    stamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError(f"Timestamp must include timezone: {event['timestamp']}")
    ref = event["raw_reference"]
    return stamp.astimezone(timezone.utc), ref["file"], ref["line"]


def ingest(case_dir: Path) -> list[dict[str, Any]]:
    case_dir = case_dir.resolve()
    events: list[dict[str, Any]] = []
    for relative, source in SOURCE_FILES:
        path = case_dir / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing {relative} in {case_dir}")
        if source == "log":
            for line_no, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not text.strip():
                    continue
                match = LOG_RE.fullmatch(text)
                if not match:
                    raise ValueError(f"Invalid log line at {relative}:{line_no}")
                data = match.groupdict()
                level = data.pop("level")
                message = data.pop("message")
                component = data.pop("component")
                event_type = "log_error" if level == "ERROR" else "latency_spike" if "latency" in message else "log_line"
                details = {"component": component, "level": level, "message": message}
                events.append(_event(data["timestamp"], "log", event_type, level.lower(), relative, line_no, details))
        else:
            events.extend(_jsonl(path, relative, source))
    return sorted(events, key=_sort_key)


def reference(event: dict[str, Any]) -> str:
    raw = event["raw_reference"]
    return f"{raw['file']}:{raw['line']}"


def write_ingest(case_dir: Path, cwd: Path) -> list[dict[str, Any]]:
    case_dir = case_dir.resolve()
    events = ingest(case_dir)
    write_json(case_dir / "normalized-events.json", events)
    write_json(cwd.resolve() / "ic-state.json", {"case_dir": str(case_dir)})
    return events


def _load_sources(case_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    events = ingest(case_dir)
    commits = [event for event in events if event["source"] == "commit"]
    deploys = [event for event in events if event["source"] == "deploy"]
    alerts = [event for event in events if event["source"] == "alert"]
    return events, commits, deploys


def score_causes(case_dir: Path) -> list[dict[str, Any]]:
    events, commits, deploys = _load_sources(case_dir)
    logs = [event for event in events if event["source"] == "log"]
    alerts = [event for event in events if event["source"] == "alert"]
    commit_by_sha = {event["details"].get("commit_sha"): event for event in commits}
    first_error = next((event for event in logs if event["type"] == "log_error"), None)
    firing = [event for event in alerts if event["details"].get("state") == "firing"]

    candidates: dict[str, dict[str, Any]] = {
        "config_change": {"cause": "Breaking configuration change", "score": 0, "evidence": []},
        "recent_deploy": {"cause": "Recent deployment", "score": 0, "evidence": []},
        "traffic_spike": {"cause": "Traffic spike", "score": 0, "evidence": []},
        "dependency_upgrade": {"cause": "Dependency upgrade", "score": 0, "evidence": []},
        "infra_event": {"cause": "Infrastructure event", "score": 0, "evidence": []},
    }

    def add(key: str, points: int, *support: dict[str, Any]) -> None:
        candidates[key]["score"] += points
        for event in support:
            cite = reference(event)
            if cite not in candidates[key]["evidence"]:
                candidates[key]["evidence"].append(cite)

    for deploy in deploys:
        linked = commit_by_sha.get(deploy["details"].get("commit_sha"))
        if linked and linked["details"].get("category") == "config" and linked["details"].get("breaking_change"):
            relevant_logs = [
                event for event in logs
                if event["type"] == "log_error"
                and "config" in event["details"]["message"].lower()
                and _sort_key(event)[0] > _sort_key(deploy)[0]
            ]
            related_alerts = [event for event in firing if _sort_key(event)[0] > _sort_key(deploy)[0]]
            if relevant_logs:
                support = [linked, deploy, relevant_logs[0]]
                add("config_change", 4, linked)
                add("config_change", 3, relevant_logs[0])
                if related_alerts:
                    add("config_change", 3, related_alerts[0])
                for event in support:
                    cite = reference(event)
                    if cite not in candidates["config_change"]["evidence"]:
                        candidates["config_change"]["evidence"].append(cite)
        if first_error:
            gap = (_sort_key(first_error)[0] - _sort_key(deploy)[0]).total_seconds()
            if 0 <= gap <= 15 * 60:
                add("recent_deploy", 2, deploy, first_error)
                if linked and linked["details"].get("breaking_change"):
                    add("recent_deploy", 3, linked)
                related_alerts = [event for event in firing if _sort_key(event)[0] > _sort_key(deploy)[0]]
                if related_alerts:
                    add("recent_deploy", 2, related_alerts[0])

    for event in logs:
        msg = event["details"]["message"].lower()
        if "request_rate=" in msg and "baseline=" in msg:
            match = re.search(r"request_rate=(\d+) baseline=(\d+)", msg)
            if match and int(match.group(1)) >= 2 * int(match.group(2)):
                add("traffic_spike", 5, event)
                break
    for commit in commits:
        files = [str(name).lower() for name in commit["details"].get("files_changed", [])]
        if any("requirements" in name or "lock" in name or "package" in name for name in files):
            add("dependency_upgrade", 4, commit)
            if first_error:
                add("dependency_upgrade", 2, first_error)
    for alert in alerts:
        if alert["details"].get("category") == "infrastructure" and alert["details"].get("state") == "firing":
            add("infra_event", 5, alert)

    order = {"config_change": 0, "recent_deploy": 1, "traffic_spike": 2, "dependency_upgrade": 3, "infra_event": 4}
    ranked = []
    for key in sorted(candidates, key=lambda item: (-candidates[item]["score"], order[item])):
        row = candidates[key]
        ranked.append({"id": key, "cause": row["cause"], "score": row["score"], "evidence": sorted(row["evidence"])})
    return ranked


def rollback_options(case_dir: Path) -> list[dict[str, Any]]:
    events = ingest(case_dir)
    commits = {e["details"].get("commit_sha"): e for e in events if e["source"] == "commit"}
    options = []
    for event in events:
        if event["source"] != "deploy":
            continue
        details = event["details"]
        commit = commits.get(details.get("commit_sha"))
        migration_at = details.get("migration_applied_at")
        risk = details.get("risk_notes") or "No additional rollback risk is recorded in this fixture."
        if migration_at:
            risk = f"{risk} Migration timestamp: {migration_at}."
        options.append(
            {
                "deployed_version": details.get("version"),
                "rollback_target": details.get("previous_version"),
                "commit_sha": details.get("commit_sha"),
                "diff_summary": details.get("diff_summary") or (commit or {}).get("details", {}).get("diff_summary", "Diff summary unavailable."),
                "risk_notes": risk,
                "evidence": [reference(event)] + ([reference(commit)] if commit else []),
            }
        )
    return options


def timeline_text(events: list[dict[str, Any]]) -> str:
    lines = []
    for event in events:
        message = event["details"].get("message") or event["details"].get("name") or event["details"].get("version") or event["details"].get("message", event["type"])
        if event["source"] == "deploy":
            message = f"{event['details'].get('version')} deployed ({event['details'].get('change_summary')})"
        elif event["source"] == "commit":
            message = f"{event['details'].get('commit_sha')} {event['details'].get('message')}"
        elif event["source"] == "alert":
            message = f"{event['details'].get('name')} {event['details'].get('state')}: {event['details'].get('description')}"
        lines.append(f"{event['timestamp']}  {event['source']}/{event['type']} [{event['severity']}]  {message}  ({reference(event)})")
    return "\n".join(lines)


def _markdown(case_dir: Path) -> str:
    events = ingest(case_dir)
    causes = score_causes(case_dir)
    rollbacks = rollback_options(case_dir)
    output = [f"# Incident Commander Report\n\n> {HONESTY}\n", "## Merged timeline\n"]
    output.extend(f"- {line}" for line in timeline_text(events).splitlines())
    output.extend(["\n## Ranked heuristic causes\n"])
    for idx, cause in enumerate(causes, 1):
        cites = ", ".join(cause["evidence"]) if cause["evidence"] else "No supporting source lines"
        output.append(f"{idx}. **{cause['cause']}** (score {cause['score']})\n   Evidence: {cites}")
    output.append("\n## Rollback options\n")
    for option in rollbacks:
        output.append(
            f"- **{option['deployed_version']} to {option['rollback_target']}**: {option['diff_summary']} "
            f"Risk: {option['risk_notes']} Evidence: {', '.join(option['evidence'])}"
        )
    return "\n".join(output).rstrip() + "\n"


def _html_report(markdown: str) -> str:
    lines = markdown.splitlines()
    body = []
    in_list = False
    for line in lines:
        if line.startswith("# ") or line.startswith("## "):
            if in_list:
                body.append("</ul>")
                in_list = False
            level = 1 if line.startswith("# ") else 2
            body.append(f"<h{level}>{html.escape(line[level + 1:])}</h{level}>")
        elif line.startswith("> "):
            if in_list:
                body.append("</ul>")
                in_list = False
            body.append(f"<p class=\"honesty\">{html.escape(line[2:])}</p>")
        elif line.startswith("- ") or re.match(r"\d+\. ", line):
            if not in_list:
                body.append("<ul>")
                in_list = True
            content = re.sub(r"^\d+\. |^- ", "", line)
            content = html.escape(content).replace("**", "")
            body.append(f"<li>{content}</li>")
        elif not line.strip():
            if in_list:
                body.append("</ul>")
                in_list = False
        else:
            body.append(f"<p>{html.escape(line).replace('**', '')}</p>")
    if in_list:
        body.append("</ul>")
    return "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>Incident Commander Report</title>" \
        "<style>body{font:16px system-ui;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#18212f}" \
        ".honesty{background:#fff3cd;border:1px solid #d9a400;padding:1rem;font-weight:600}li{margin:.6rem 0}</style>" \
        "</head><body>\n" + "\n".join(body) + "\n</body></html>\n"


def write_report(case_dir: Path, format_name: str) -> Path:
    markdown = _markdown(case_dir)
    extension = "md" if format_name == "md" else "html"
    path = case_dir / f"incident-report.{extension}"
    content = markdown if format_name == "md" else _html_report(markdown)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path

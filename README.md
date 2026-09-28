# Incident Commander

Incident Commander is a deterministic Python CLI for turning incident logs, alerts, deploys, and commits into one cited timeline, heuristic cause ranking, rollback options, and a report. It is the incident-response half of a LiveOps Dashboard: the dashboard shows system pulse, while this tool narrates a fictional incident from structured evidence.

## Quickstart

Python 3.10 or newer is required. Runtime code uses only the Python standard library. No external data, downloads, machine learning frameworks, or GPU packages are used.

```powershell
python -m incident_commander fixtures --out fixtures/synthetic-incident
python -m incident_commander ingest fixtures/synthetic-incident
python -m incident_commander timeline
python -m incident_commander causes
python -m incident_commander rollback
python -m incident_commander report --format md
python -m incident_commander report --format html
python -m incident_commander audit
```

Install the package to use the `incident-commander` console command:

```powershell
python -m pip install -e .
incident-commander fixtures --out fixtures/synthetic-incident
incident-commander ingest fixtures/synthetic-incident
```

Timeline, causes, rollback, and report use the most recently ingested directory. Pass `--dir <directory>` to any of those commands to select another incident explicitly. Ingestion writes `normalized-events.json` and remembers the directory in `ic-state.json` in the current working directory. The analysis commands write `timeline.json`, `causes.json`, `rollback-options.json`, and `incident-report.md` or `incident-report.html` beside the source files. Each CLI invocation, including help and argument errors, appends one JSON record to `ic-audit.jsonl` in the current working directory.

The fixture generator uses documented seed `417` as scenario metadata. All fixture values are fixed constants; it does not consume randomness. Repeated runs produce byte-identical source files and normalized JSON for the same inputs. The generated scenario has one planted root cause: release `v2.4.1` enabled strict payment configuration and rejected legacy payloads.

Run the test suite with:

```powershell
python -m pytest
```

## Architecture

```text
                 +----------------------+
                 | fixtures (fictional) |
                 +----------+-----------+
                            |
       +--------------------+--------------------+
       |                    |                    |
     logs                 alerts               deploys + commits
       +--------------------+--------------------+
                            |
                    +-------v-------+
                    | source parsers |
                    +-------+-------+
                            |
                 normalized-events.json
                            |
        +-------------------+--------------------+
        |                   |                    |
     timeline          cause scoring        rollback review
        |                   |                    |
        +-------------------+--------------------+
                            |
                   Markdown or HTML report
                            |
                 ic-audit.jsonl (CLI runs)
```

The parser preserves each event's source file and one-based line number. Events are sorted by UTC timestamp, then source path and line number. Scoring uses only parsed fields and fixed rules. It has no model, network call, probabilistic step, or learned weights.

## Scoring heuristic catalogue

Candidates are returned in descending score. Equal scores use this stable order: configuration change, recent deployment, traffic spike, dependency upgrade, infrastructure event. All supporting source locations are listed as `path:line`; an unsupported candidate has score zero and an empty evidence list.

| Candidate | Evidence rule | Points | What it measures |
| --- | --- | ---: | --- |
| Breaking configuration change | A linked commit is categorized as config and marked breaking. | +4 | Whether a deploy includes an explicitly breaking config change. |
| Breaking configuration change | An error after that deploy contains `config`. | +3 | Whether the failure log mentions configuration after the change. |
| Breaking configuration change | A firing alert follows the deploy when the matching config error exists. | +3 | Whether monitoring detected the same post-deploy incident. |
| Recent deployment | A deploy occurred within 15 minutes before the first log error. | +2 | Temporal proximity between a release and the first observed error. |
| Recent deployment | Its linked commit is marked breaking. | +3 | Whether the nearby release has an explicit breaking change. |
| Recent deployment | A firing alert follows the deploy. | +2 | Whether an alert also follows the release. |
| Traffic spike | A log has `request_rate` at least twice its `baseline`. | +5 | Whether observed request volume materially exceeds its stated baseline. |
| Dependency upgrade | A commit changes a file with `requirements`, `lock`, or `package` in its path. | +4 | Whether dependency metadata changed. |
| Dependency upgrade | A first log error exists alongside that dependency change. | +2 | Whether a dependency change coincides with an observed error. |
| Infrastructure event | An infrastructure-category alert is firing. | +5 | Whether monitoring reports an active infrastructure issue. |

Evidence citations include the records that triggered each rule. The configuration rule also cites the linked deploy so the report shows the release context. These weights and match conditions are intentionally simple and inspectable. They do not establish causality.

## HONESTY BOUNDARY

All incident data is synthetic and fictional. The cause ranking is heuristic scoring over structured evidence, NOT an AI diagnosis of a real production outage, NOT incident-response experience, NOT on-call expertise. CLI output, generated reports, and fixture files identify the scenario as synthetic and fictional. The planted cause is included to demonstrate how evidence is collected and ranked; it is not a claim about a real system.

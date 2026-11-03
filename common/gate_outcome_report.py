"""Report existing gate outcome evidence without executing or grading tests.

Canonical test identity excludes stage and invocation. Repeated executions stay
as lists; subtest parameter text is a secondary discriminator, not a unique ID.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
from typing import Any


def summary_to_report(summary: dict[str, Any], *, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Project a summary's actual rows, retaining incomplete and legacy evidence."""
    if not isinstance(summary, dict) or not isinstance(summary.get("stages"), list):
        raise ValueError("gate summary requires a stages array")
    report = dict(schema_version=1, role="gate_outcome_report",
                  metadata=deepcopy({key: value for key, value in summary.items() if key != "stages"}),
                  supplied_metadata=deepcopy(metadata or {}), stages=[], executions=[])
    for stage_index, stage in enumerate(summary["stages"]):
        if not isinstance(stage, dict):
            raise ValueError("stage must be an object")
        rows = stage.get("test_outcomes") or []
        receipts = stage.get("test_outcome_invocations") or []
        if not isinstance(rows, list) or not isinstance(receipts, list):
            raise ValueError("outcomes and invocation receipts must be arrays")
        selected = stage.get("selected")
        state = ("not_selected" if selected is False else "blocked" if stage.get("status") == "BLOCKED"
                 else "observed" if rows or receipts else "not_executed" if stage.get("started_at") is None
                 and stage.get("status") in {"PENDING", "NOT_STARTED"} else "unknown")
        stage_report = deepcopy(stage)
        stage_report.update(stage_index=stage_index, execution_evidence=state,
                            outcome_record_count=len(rows), legacy_duration_only=bool(stage.get("test_durations")) and not rows)
        report["stages"].append(stage_report)
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError("outcome must be an object")
            record = deepcopy(row)
            # Context is additional: never overwrite the runner's own stage/id.
            record.update(summary_stage_name=stage.get("name"), summary_stage_index=stage_index,
                          stage_record_index=row_index, execution_sequence=len(report["executions"]))
            record.setdefault("outcome", "unknown")
            path, method = record.get("source_path"), record.get("class_method")
            expected = f"{path}::{method}" if path and method else None
            record["canonical_identity_valid"] = bool(expected and expected == record.get("test_key"))
            report["executions"].append(record)
    return report


def _groups(report: dict[str, Any]) -> tuple[dict[tuple, list], list]:
    groups, unknown = defaultdict(list), []
    for row in report["executions"]:
        if not row.get("canonical_identity_valid"):
            unknown.append(deepcopy(row))
            continue
        key = (row["test_key"], row.get("entity_kind"),
               row.get("legacy_test_id") if row.get("entity_kind") == "subtest" else None)
        groups[key].append(row)
    return groups, unknown


def _counter(rows: list, fields: tuple[str, ...]) -> list[dict]:
    counts = Counter(tuple(json.dumps(row.get(field), sort_keys=True) for field in fields) for row in rows)
    return [dict(values={field: json.loads(value) for field, value in zip(fields, values)}, count=count)
            for values, count in sorted(counts.items())]


def compare_reports(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Compare canonical multisets; never pair random invocation IDs across runs.

    Different multiplicities and ambiguous repeated attempts are exposed, not
    deduplicated. Unknown source identities are retained separately and unpaired.
    """
    a, unknown_a = _groups(left)
    b, unknown_b = _groups(right)
    comparisons = []
    for key in sorted(a.keys() | b.keys(), key=repr):
        x, y = a.get(key, []), b.get(key, [])
        differences = []
        if not x or not y:
            differences.append("only_left" if x else "only_right")
        if len(x) != len(y):
            differences.append("multiplicity")
        for fields, label in [(("outcome",), "outcome"),
                              (("outcome", "source_sha", "source_file_sha256"), "source_identity"),
                              (("outcome", "reason"), "reason")]:
            if x and y and _counter(x, fields) != _counter(y, fields):
                differences.append(label)
        comparisons.append(dict(test_key=key[0], entity_kind=key[1], subtest_discriminator=key[2],
                                differences=differences, left=deepcopy(x), right=deepcopy(y)))
    def stage_inventory(report):
        return [dict(name=row.get("name"), selected=row.get("selected"), status=row.get("status"),
                     execution_evidence=row.get("execution_evidence"),
                     reason_code=row.get("reason_code"), outcome_record_count=row.get("outcome_record_count"))
                for row in report["stages"]]
    stages_left, stages_right = stage_inventory(left), stage_inventory(right)
    stage_comparisons = []
    for name in sorted({row["name"] for row in stages_left + stages_right}, key=repr):
        x = [row for row in stages_left if row["name"] == name]
        y = [row for row in stages_right if row["name"] == name]
        if x != y:
            stage_comparisons.append(dict(name=name, left=x, right=y))
    return dict(schema_version=1, role="gate_outcome_comparison", comparisons=comparisons,
                left_metadata=deepcopy(left["metadata"]), right_metadata=deepcopy(right["metadata"]),
                left_supplied_metadata=deepcopy(left.get("supplied_metadata", {})),
                right_supplied_metadata=deepcopy(right.get("supplied_metadata", {})),
                left_stages=stages_left, right_stages=stages_right, stage_comparisons=stage_comparisons,
                unidentified_left=unknown_a, unidentified_right=unknown_b,
                matching_policy="test_key + entity_kind; subtest legacy params may collide; multiplicities retained")


def main(argv: list[str] | None = None) -> int:
    """Write an explicit report or comparison; differences are data, not a gate."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report")
    report.add_argument("--summary", required=True, type=Path)
    report.add_argument("--metadata", type=Path)
    compare = commands.add_parser("compare")
    compare.add_argument("--left", required=True, type=Path)
    compare.add_argument("--right", required=True, type=Path)
    for command in (report, compare):
        command.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))
    result = (summary_to_report(read(args.summary), metadata=read(args.metadata) if args.metadata else None)
              if args.command == "report" else compare_reports(read(args.left), read(args.right)))
    # An explicit output is a new evidence identity; do not overwrite old runs.
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Human-readable, machine-checkable artifact identifiers.

Folder timestamps use Asia/Shanghai local time for Explorer sorting.  Machine
manifests remain responsible for ISO-8601 timestamps with offsets and UTC.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime


MAX_ID_LENGTH = 96
ACTIVITIES = frozenset({"sim", "test", "analysis", "build", "benchmark", "gate", "migration"})
SCOPES = frozenset({"comsol", "simion", "cross", "cad", "python", "repo"})
ARCHIVE_REASONS = frozenset({"superseded", "legacy", "milestone", "failed-evidence", "migration-snapshot"})
TOKEN = r"[a-z0-9]+(?:-[a-z0-9]+)*"
PROJECT_ID = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
STAMP = r"\d{8}_\d{6}"
RUN_PATTERN = re.compile(
    rf"^(?P<stamp>{STAMP})__(?P<activity>{TOKEN})__(?P<scope>{TOKEN})__"
    rf"(?P<subject>{TOKEN})(?:__(?P<detail>{TOKEN}))?(?:__r(?P<retry>\d{{2}}))?$"
)
ARCHIVE_PATTERN = re.compile(
    rf"^(?P<stamp>{STAMP})__(?P<reason>{TOKEN})__(?P<scope>{TOKEN})__"
    rf"(?P<subject>{TOKEN})(?:__(?P<detail>{TOKEN}))?$"
)
TASK_PATTERN = re.compile(
    rf"^(?P<stamp>{STAMP})__(?P<scope>{TOKEN})__(?P<subject>{TOKEN})$"
)


def _validate_stamp(value: str) -> None:
    datetime.strptime(value, "%Y%m%d_%H%M%S")


def _common(identifier: str) -> None:
    if len(identifier) > MAX_ID_LENGTH:
        raise ValueError(f"identifier exceeds {MAX_ID_LENGTH} characters")
    if identifier != identifier.lower() or not identifier.isascii():
        raise ValueError("identifier must be lowercase ASCII")


def validate_run_id(identifier: str) -> dict[str, str | None]:
    _common(identifier)
    match = RUN_PATTERN.fullmatch(identifier)
    if not match:
        raise ValueError("run_id must be TIMESTAMP__ACTIVITY__SCOPE__SUBJECT[__DETAIL][__rNN]")
    values = match.groupdict()
    _validate_stamp(values["stamp"] or "")
    if values["activity"] not in ACTIVITIES:
        raise ValueError(f"unsupported activity: {values['activity']}")
    if values["scope"] not in SCOPES:
        raise ValueError(f"unsupported scope: {values['scope']}")
    if values["retry"] == "00":
        raise ValueError("retry numbering starts at r01")
    return values


def validate_archive_id(identifier: str) -> dict[str, str | None]:
    _common(identifier)
    match = ARCHIVE_PATTERN.fullmatch(identifier)
    if not match:
        raise ValueError("archive_id must be TIMESTAMP__REASON__SCOPE__SUBJECT[__DETAIL]")
    values = match.groupdict()
    _validate_stamp(values["stamp"] or "")
    if values["reason"] not in ARCHIVE_REASONS:
        raise ValueError(f"unsupported archive reason: {values['reason']}")
    if values["scope"] not in SCOPES:
        raise ValueError(f"unsupported scope: {values['scope']}")
    return values


def validate_formal_asset_name(filename: str, project_id: str) -> dict[str, str]:
    """Validate a primary formal binary that must remain clear when detached."""
    if not PROJECT_ID.fullmatch(project_id):
        raise ValueError("project_id must be stable snake_case")
    match = re.fullmatch(
        rf"(?P<project>{re.escape(project_id)})__(?P<role>{TOKEN})\.(?P<extension>[A-Za-z0-9]+)",
        filename,
    )
    if not match:
        raise ValueError("formal primary binary must be <project_id>__<role>.<ext>")
    return match.groupdict()


def validate_task_id(identifier: str) -> dict[str, str | None]:
    _common(identifier)
    match = TASK_PATTERN.fullmatch(identifier)
    if not match:
        raise ValueError("task_id must be TIMESTAMP__SCOPE__SUBJECT")
    values = match.groupdict()
    _validate_stamp(values["stamp"] or "")
    if values["scope"] not in SCOPES:
        raise ValueError(f"unsupported scope: {values['scope']}")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("run", "archive", "task"))
    parser.add_argument("identifier")
    args = parser.parse_args()
    validator = {"run": validate_run_id, "archive": validate_archive_id, "task": validate_task_id}[args.kind]
    validator(args.identifier)
    print(f"ARTIFACT_ID=PASS KIND={args.kind} ID={args.identifier}")


if __name__ == "__main__":
    main()

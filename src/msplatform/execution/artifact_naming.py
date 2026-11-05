"""The original run identifier contract, independent of repository lookup."""
from __future__ import annotations
import re
from datetime import datetime


MAX_ID_LENGTH = 96

ACTIVITIES = frozenset({"sim", "test", "analysis", "build", "benchmark", "gate", "migration"})

SCOPES = frozenset({"comsol", "simion", "cross", "cad", "python", "repo"})

TOKEN = r"[a-z0-9]+(?:-[a-z0-9]+)*"

STAMP = r"\d{8}_\d{6}"

RUN_PATTERN = re.compile(
    rf"^(?P<stamp>{STAMP})__(?P<activity>{TOKEN})__(?P<scope>{TOKEN})__"
    rf"(?P<subject>{TOKEN})(?:__(?P<detail>{TOKEN}))?(?:__r(?P<retry>\d{{2}}))?$"
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

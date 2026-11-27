"""Explicit instrument-clock identities and finite time arithmetic in microseconds."""
from __future__ import annotations

from dataclasses import dataclass
import math
import re

from jsonschema import Draft202012Validator


def _finite(value: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("clock time must be a finite number")
    return float(value)


@dataclass(frozen=True)
class ClockIdentity:
    """An externally verified epoch and authority SHA; no file is read here."""

    clock_epoch_id: str
    authority_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.clock_epoch_id, str) or not self.clock_epoch_id.strip():
            raise ValueError("clock epoch identity is missing")
        if not isinstance(self.authority_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", self.authority_sha256):
            raise ValueError("clock authority SHA-256 is missing or invalid")


def require_same_clock(source: ClockIdentity, target: ClockIdentity) -> None:
    """Reject matching labels with different authorities as well as different epochs."""
    if (source.clock_epoch_id != target.clock_epoch_id
            or source.authority_sha256.upper() != target.authority_sha256.upper()):
        raise ValueError("handoff clock epoch or authority differs")


def validate_clock_authority_structure(contract: dict, schema: dict) -> None:
    """Validate an explicitly supplied clock document against its supplied schema."""
    Draft202012Validator(schema).validate(contract)


def bind_clock_authority_identity(contract: dict, authority_sha256: str) -> dict:
    """Bind validated epoch metadata to the caller's measured authority bytes."""
    if authority_sha256 != contract['authority']['sha256']:
        raise ValueError('clock authority SHA-256 differs from frozen bytes')
    return dict(schema_version=1, role='canonical_clock_authority_validation', status='PASS',
                clock_epoch_id=contract['clock_epoch_id'], authority_sha256=authority_sha256)


def instrument_time_us(native_time_us: float, *, instrument_origin_us: float, native_origin_us: float) -> float:
    """Map explicit native and instrument anchors once; query order is unrestricted."""
    return _finite(_finite(instrument_origin_us) + (_finite(native_time_us) - _finite(native_origin_us)))


def age_us(instrument_time_us: float, *, birth_time_us: float) -> float:
    """Compute age from the original birth, never the receiver arrival time."""
    age = _finite(_finite(instrument_time_us) - _finite(birth_time_us))
    if age < 0:
        raise ValueError("instrument time precedes particle birth")
    return age


def seconds_to_microseconds(time_s: float) -> float:
    """Use the existing source-boundary seconds-to-us multiplication once."""
    return _finite(_finite(time_s) * 1e6)

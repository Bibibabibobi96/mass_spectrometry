"""Small shared primitives for MR-TOF SIMION run-manifest writers.

This module deliberately owns only byte-level artifact binding.  Each manifest
writer keeps ownership of its scientific scope and status: a one-PA Candidate
run, the retired two-instance review assembly, and the active three-component
geometry review are not interchangeable evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Type

from common.contracts.file_identity import file_sha256


def sha256_file(path: Path) -> str:
    """Return the legacy lowercase digest using the repository byte primitive."""
    return file_sha256(path).lower()


def record_artifact(
    path: Path,
    *,
    missing_error: Type[Exception] = FileNotFoundError,
) -> dict[str, Any]:
    """Return the path-independent identity record for one required artifact."""
    if not path.is_file():
        if missing_error is FileNotFoundError:
            raise FileNotFoundError(path)
        raise missing_error(f"required SIMION artifact is missing: {path}")
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def record_pa_family(run_directory: Path, stem: str, basis_ids: Iterable[int]) -> dict[str, Any]:
    """Record one PA0 and its explicit basis namespace under ``run_directory``."""
    pa0 = run_directory / f"{stem}.pa0"
    return {
        "pa0": record_artifact(pa0),
        "basis_arrays": [
            record_artifact(run_directory / f"{stem}.pa{electrode_id}")
            for electrode_id in basis_ids
        ],
    }


def validate_no_flight_structure_report(path: Path) -> str:
    """Read and fail closed unless a structure report proves a no-flight PASS."""
    report = path.read_text(encoding="utf-8")
    if "STATUS=PASS" not in report or "PARTICLE_FLY_EXECUTED=false" not in report:
        raise ValueError("IOB structure report is not a successful no-flight verification")
    return report


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write a deterministic UTF-8/LF manifest, creating its output directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

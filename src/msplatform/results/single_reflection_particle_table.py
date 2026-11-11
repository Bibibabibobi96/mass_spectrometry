"""Particle table import and normalization for single-reflection results."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

PARTICLE_ID_ALIASES = ("particleid", "ion", "ionnumber", "ionno", "particlenumber")


def _normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def find_column(
    frame: pd.DataFrame, aliases: tuple[str, ...], required: bool = False
) -> str | None:
    """Select the first matching normalized column alias, or require a match."""
    normalized = {_normalized_name(column): str(column) for column in frame.columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    if required:
        raise ValueError(
            f"Required column not found; aliases={aliases}; columns={list(frame.columns)}"
        )
    return None


def _parse_hit(values: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False)
    normalized = values.astype(str).str.strip().str.lower()
    truthy = {"1", "true", "yes", "y", "hit", "splat"}
    falsy = {"0", "false", "no", "n", "miss", "nan", "none", ""}
    unknown = ~normalized.isin(truthy | falsy)
    if bool(unknown.any()):
        bad = sorted(normalized[unknown].unique().tolist())
        raise ValueError(f"Unrecognized hit values: {bad}")
    return normalized.isin(truthy)


def validated_particle_ids(values: pd.Series, label: str = "Input") -> pd.Series:
    """Parse original integer encodings exactly, before any hit/event filtering."""
    ids = []
    for value in values:
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{label} particle IDs must be positive finite integers") from exc
        if (isinstance(value, (bool, np.bool_)) or not number.is_finite()
                or number <= 0 or number > np.iinfo(np.int64).max
                or number != number.to_integral_value()):
            raise ValueError(f"{label} particle IDs must be positive finite integers")
        ids.append(int(number))
    result = pd.Series(ids, index=values.index, dtype="int64")
    if result.duplicated().any():
        duplicates = result[result.duplicated()].tolist()
        raise ValueError(f"Duplicate particle_id values in {label}: {duplicates[:10]}")
    return result


def read_source_table(
    path: Path, particle_id_column: str | None = None,
) -> tuple[pd.DataFrame, str]:
    """Read CSV, Excel or detector TRACE while preserving particle ID encodings."""
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        header = pd.read_excel(path, engine="openpyxl", nrows=0)
        selected_id = particle_id_column or find_column(header, PARTICLE_ID_ALIASES)
        # Text IDs stay text; numeric Excel cells retain the values actually stored.
        dtype = {selected_id: object} if selected_id is not None else None
        return pd.read_excel(path, engine="openpyxl", dtype=dtype), "Excel human import"
    if path.suffix.lower() == ".csv":
        header = pd.read_csv(path, nrows=0)
        selected_id = particle_id_column or find_column(header, PARTICLE_ID_ALIASES)
        # Preserve only the ID column lexically; scientific numeric columns keep
        # their established pandas parsing and floating-point reduction inputs.
        dtype = {selected_id: "string"} if selected_id is not None else None
        return pd.read_csv(path, dtype=dtype), "CSV machine source"
    if path.suffix.lower() in {".log", ".txt"}:
        pattern = re.compile(
            r"^TRACE:\s*detector_crossing\s+ion=(\d+)\s+"
            r"t=([-+0-9.eE]+)\s+x=([-+0-9.eE]+)\s+"
            r"y=([-+0-9.eE]+)\s+z=([-+0-9.eE]+)\s+"
            r"r=([-+0-9.eE]+)\s+zmax=([-+0-9.eE]+)"
        )
        records: list[dict[str, float | int | str]] = []
        with path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                match = pattern.match(line.strip())
                if match is None:
                    continue
                records.append(
                    {
                        "Ion": int(match.group(1)),
                        "TofUs": float(match.group(2)),
                        "DetectorXmm": float(match.group(3)),
                        "DetectorYmm": float(match.group(4)),
                        "DetectorZmm": float(match.group(5)),
                        "RadiusMm": float(match.group(6)),
                        "ZMaxMm": float(match.group(7)),
                        "Event": "detector_crossing",
                    }
                )
        if not records:
            raise ValueError(f"No SIMION detector_crossing TRACE records found: {path}")
        return pd.DataFrame.from_records(records), "SIMION detector_crossing TRACE"
    raise ValueError(f"Unsupported input extension: {path.suffix}")


def normalize_particle_table(
    source: pd.DataFrame,
    source_format: str,
    detector_center_x_mm: float,
    detector_center_y_mm: float,
    column_overrides: dict[str, str] | None = None,
    declared_event: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Normalize one already-read source, keeping exact IDs aligned to its rows."""
    if source.empty:
        raise ValueError("Input table is empty")

    overrides = column_overrides or {}

    def source_column(
        canonical: str, aliases: tuple[str, ...], required: bool = False
    ) -> str | None:
        if canonical in overrides:
            selected = overrides[canonical]
            if selected not in source.columns:
                raise ValueError(
                    f"Configured {canonical} column {selected!r} is absent; "
                    f"columns={list(source.columns)}"
                )
            return selected
        return find_column(source, aliases, required)

    ion_column = source_column(
        "particle_id",
        PARTICLE_ID_ALIASES,
    )
    tof_column = source_column(
        "tof_us", ("tofus", "timeofflightus", "tof", "timeofflight"), True
    )
    hit_column = source_column("hit", ("hit", "detected", "arrived"))

    particle_id_generated = ion_column is None
    particle_id = (
        np.arange(1, len(source) + 1, dtype=np.int64)
        if particle_id_generated
        else validated_particle_ids(source[ion_column])
    )
    normalized = pd.DataFrame(
        {
            "particle_id": particle_id,
            "tof_us": pd.to_numeric(source[tof_column], errors="coerce"),
        }
    )
    if hit_column is not None:
        normalized["hit"] = _parse_hit(source[hit_column])
    else:
        normalized["hit"] = True

    local_x = source_column(
        "detector_local_x_mm",
        ("detectorlocalxmm", "localxmm", "impactlocalxmm"),
    )
    local_y = source_column(
        "detector_local_y_mm",
        ("detectorlocalymm", "localymm", "impactlocalymm"),
    )
    global_x = source_column("detector_x_mm", ("detectorxmm", "xmm", "x"))
    global_y = source_column("detector_y_mm", ("detectorymm", "ymm", "y"))
    if local_x is not None and local_y is not None:
        normalized["detector_x_mm"] = pd.to_numeric(source[local_x], errors="coerce")
        normalized["detector_y_mm"] = pd.to_numeric(source[local_y], errors="coerce")
    elif global_x is not None and global_y is not None:
        normalized["detector_x_mm"] = (
            pd.to_numeric(source[global_x], errors="coerce") - detector_center_x_mm
        )
        normalized["detector_y_mm"] = (
            pd.to_numeric(source[global_y], errors="coerce") - detector_center_y_mm
        )

    optional_columns = {
        "detector_z_mm": ("detectorzmm", "zmm", "z"),
        "logged_radius_mm": ("radiusmm", "rmm", "r"),
        "pa_instance": ("painstance", "painstanceno", "instance", "instanceid"),
        "initial_x_mm": ("x0mm", "initialxmm"),
        "initial_y_mm": ("y0mm", "initialymm"),
        "initial_z_mm": ("z0mm", "initialzmm"),
        "initial_energy_eV": ("energyev", "initialenergyev"),
    }
    for canonical, aliases in optional_columns.items():
        selected_column = source_column(canonical, aliases)
        if selected_column is not None:
            normalized[canonical] = pd.to_numeric(
                source[selected_column], errors="coerce"
            )
    event_column = source_column("event", ("event", "eventname", "eventtype"))
    if event_column is not None:
        normalized["event"] = (
            source[event_column].astype("string").fillna("").str.strip().astype(str)
        )
        event_provenance = "source_column"
    elif declared_event is not None and declared_event.strip():
        normalized["event"] = declared_event.strip()
        event_provenance = "operator_declared_from_data_recording_event_selection"
    else:
        event_provenance = "absent"
    if declared_event is not None and event_column is not None:
        declared = declared_event.strip().lower()
        recorded = normalized["event"].astype(str).str.strip().str.lower()
        if bool((recorded != declared).any()):
            raise ValueError("Declared event conflicts with values in the event column")

    detected = normalized.loc[normalized["hit"]].copy()
    if len(detected) < 3:
        raise ValueError("Fewer than three detected particles")
    if bool(detected["tof_us"].isna().any()) or bool(
        (~np.isfinite(detected["tof_us"])).any()
    ):
        raise ValueError("Detected particles contain missing or non-finite tof_us")
    if bool((detected["tof_us"] <= 0).any()):
        raise ValueError("Detected particles contain non-positive tof_us")
    for coordinate in ("detector_x_mm", "detector_y_mm"):
        if coordinate in detected and bool(detected[coordinate].isna().any()):
            raise ValueError(f"{coordinate} contains missing values")
    for numeric in ("detector_z_mm", "logged_radius_mm", "pa_instance"):
        if numeric in detected and bool(
            detected[numeric].isna().any() | (~np.isfinite(detected[numeric])).any()
        ):
            raise ValueError(f"{numeric} contains missing or non-finite values")

    metadata = {
        "source_format": source_format,
        "source_rows": int(len(source)),
        "detected_rows": int(len(detected)),
        "missed_rows": int(len(source) - len(detected)),
        "hit_fraction": float(len(detected) / len(source)),
        "hit_column_present": hit_column is not None,
        "hit_assumed_from_detector_export": hit_column is None,
        "particle_id_generated": particle_id_generated,
        "event_column_present": event_column is not None,
        "event_provenance": event_provenance,
        "pa_instance_column_present": "pa_instance" in normalized,
        "detector_z_column_present": "detector_z_mm" in normalized,
        "column_overrides": overrides,
        "source_columns": [str(column) for column in source.columns],
    }
    return detected.reset_index(drop=True), metadata

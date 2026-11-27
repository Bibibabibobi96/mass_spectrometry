"""Read frozen version-1 release receipts without invoking source producers."""
from __future__ import annotations

import csv
from functools import wraps
import hashlib
import json
import math
from pathlib import Path

_COLUMNS = ("particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm",
            "vx_m_s", "vy_m_s", "vz_m_s", "mass_amu", "charge_state")
_EVENT_COLUMNS = ("particle_id", "event", "reason", "t_us", "x_mm", "y_mm", "z_mm",
                  "vx_mm_us", "vy_mm_us", "vz_mm_us")
_ROLES = {"repository_ion_release", "continuous_axial_volume_ion_beam_source"}


def _digest(value):
    return hashlib.sha256(value).hexdigest().upper()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _read_legacy(path: Path, receipt: dict) -> dict:
    """Verify original records and state identity without running a sampler or owner."""
    spec = receipt.get("release_spec")
    if not isinstance(spec, dict) or receipt.get("status") != "materialized":
        raise ValueError("historical release receipt lacks its frozen release specification")
    if spec.get("schema_version") != 1 or spec.get("role") != receipt["role"]:
        raise ValueError("historical release identity differs")
    if receipt.get("release_spec_sha256") != _digest(_canonical(spec)):
        raise ValueError("historical release specification identity changed")
    source = receipt.get("source_spec")
    if source is not None:
        if not isinstance(source, dict) or not isinstance(source.get("path"), str):
            raise ValueError("historical release source binding is incomplete")
        try:
            payload = Path(source["path"]).read_bytes()
        except OSError as error:
            raise ValueError("historical release source specification unavailable") from error
        if len(payload) != source["bytes"] or _digest(payload) != source["sha256"].upper():
            raise ValueError("historical release source specification identity changed")
    table = receipt.get("state_table") or receipt.get("particle_source")
    if not isinstance(table, dict) or not isinstance(table.get("path"), str):
        raise ValueError("historical release table identity missing")
    table_path = Path(table["path"])
    if not table_path.is_absolute():
        table_path = path.parent / table_path
    try:
        payload = table_path.read_bytes()
    except OSError as error:
        raise ValueError("historical release table unavailable") from error
    if _digest(payload) != str(table.get("sha256", "")).upper() or ("bytes" in table and len(payload) != table["bytes"]):
        raise ValueError("historical release table identity changed")
    with table_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != _COLUMNS:
            raise ValueError("historical release table columns changed")
        states = []
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError("historical release table row is malformed")
            try:
                state = {key: (int(row[key]) if key in {"particle_id", "charge_state"}
                               else float(row[key])) for key in _COLUMNS}
            except (ValueError, TypeError) as error:
                raise ValueError("historical release table row has invalid values") from error
            if (state["particle_id"] <= 0 or state["charge_state"] == 0
                    or state["mass_amu"] <= 0 or any(not math.isfinite(value) for value in state.values())):
                raise ValueError("historical release table row has invalid physical values")
            states.append(state)
    ids = [state["particle_id"] for state in states]
    if len(ids) != len(set(ids)) or len(ids) != receipt.get("particle_count"):
        raise ValueError("historical release mother identities differ")
    identity = {"ordered_particle_ids_sha256": _digest(_canonical(ids)),
                "canonical_states_sha256": _digest(_canonical(states))}
    if identity != receipt.get("state_identity"):
        raise ValueError("historical release state identity changed")
    return receipt


def read_legacy_event_release_states(path: Path, spec: dict) -> list[dict]:
    """Restore schema-1 standalone sources from frozen events without producing new states."""
    if (not isinstance(spec, dict) or type(spec.get("schema_version")) is not int
            or spec["schema_version"] != 1 or spec.get("role") != "repository_ion_release"):
        raise ValueError("historical event source requires schema 1 repository_ion_release")
    count, mother_count = spec.get("particle_count"), spec.get("mother_particle_count")
    if (type(count) is not int or type(mother_count) is not int
            or count <= 0 or mother_count != count):
        raise ValueError("historical event source does not declare one complete mother cohort")
    birth = spec.get("common_time_of_birth_s")
    species = spec.get("species")
    if (isinstance(birth, bool) or not isinstance(birth, (int, float)) or not math.isfinite(birth)
            or not isinstance(species, dict)):
        raise ValueError("historical event source birth or species is invalid")
    mass, charge = species.get("mass_amu"), species.get("charge_state")
    if (isinstance(mass, bool) or not isinstance(mass, (int, float)) or not math.isfinite(mass) or mass <= 0
            or type(charge) is not int or charge == 0):
        raise ValueError("historical event source mass or charge is invalid")
    states = []
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != _EVENT_COLUMNS:
                raise ValueError("historical event source columns changed")
            for row in reader:
                if row["event"] != "source":
                    continue
                if None in row or any(value is None for value in row.values()):
                    raise ValueError("historical event source row is malformed")
                try:
                    particle_id = int(row["particle_id"])
                    values = {key: float(row[key]) for key in _EVENT_COLUMNS[3:]}
                except (ValueError, TypeError) as error:
                    raise ValueError("historical event source row has invalid values") from error
                if (particle_id <= 0 or any(not math.isfinite(value) for value in values.values())
                        or values["t_us"] != birth * 1e6):
                    raise ValueError("historical event source identity or units are invalid")
                states.append(dict(particle_id=particle_id, birth_time_s=float(birth),
                    x_mm=values["x_mm"], y_mm=values["y_mm"], z_mm=values["z_mm"],
                    vx_m_s=values["vx_mm_us"] * 1000, vy_m_s=values["vy_mm_us"] * 1000,
                    vz_m_s=values["vz_mm_us"] * 1000, mass_amu=float(mass), charge_state=charge))
    except OSError as error:
        raise ValueError("historical event source is unavailable") from error
    if [state["particle_id"] for state in states] != list(range(1, count + 1)):
        raise AssertionError("particle IDs do not match the input table")
    return states


def receipt_reader(function):
    """Select only the exact frozen historical receipt format for read-only validation."""
    @wraps(function)
    def read(path):
        path = Path(path)
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("release receipt is unreadable") from error
        if isinstance(receipt, dict) and receipt.get("schema_version") == 1 and receipt.get("role") in _ROLES:
            return _read_legacy(path, receipt)
        return function(path)
    return read

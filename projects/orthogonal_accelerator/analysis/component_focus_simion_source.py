"""Project-owned projection of common release states into one focus IOB."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.ion_release.release import validate_materialized_release
from common.simion.particle_source import render_source_states, render_standard_beams


_PROJECTION_FIELDS = {
    "source_frame", "workbench_mapping", "local_pa_span_mm", "iob_origin_rule",
    "local_exit_z_mm", "focus_plane_padding_mm", "positive_z_enclosure_padding_mm", "semantics",
}


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be finite") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _load_provider_source_interval(path: Path, local_exit_z_mm: float) -> tuple[float, float]:
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
        domain = plan["numerical_domain"]
        layout = plan["layout"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("provider focus plan is unreadable") from error
    if plan.get("role") != "orthogonal_accelerator_component_focus_pa_plan":
        raise ValueError("provider focus plan identity is invalid")
    planned_exit = _finite(domain.get("local_exit_z_mm"), "provider plan local exit")
    if not math.isclose(planned_exit, local_exit_z_mm, rel_tol=0.0, abs_tol=1.0e-9):
        raise ValueError("provider plan local exit differs from resolved projection")
    # Derive the interval from the owned electrode planes.  Older PA plans
    # serialized their source centre in the exit-adjacent region; accepting that
    # metadata would reintroduce the coordinate error while the PA fields remain
    # physically identical and safely reusable.
    gap_1 = _finite(layout.get("gap_1_mm"), "provider first-gap length")
    gap_2 = _finite(layout.get("gap_2_mm"), "provider second-gap length")
    minimum = gap_2
    maximum = gap_2 + gap_1
    if not minimum < maximum:
        raise ValueError("provider source interval is invalid")
    return minimum, maximum


def _load_rows(receipt: Mapping[str, Any], particle_count: int) -> list[dict[str, str]]:
    table = Path(str(receipt["state_table"]["path"]))
    with table.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != particle_count:
        raise ValueError("release table count differs from campaign")
    for expected, row in enumerate(rows, 1):
        if int(row["particle_id"]) != expected:
            raise ValueError("release IDs must be contiguous")
    return rows


def materialize(
    receipt_path: Path,
    campaign_path: Path,
    provider_plan_path: Path,
    fly2_path: Path,
    source_states_path: Path,
    resolved_projection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one run-local FLY2/source-state pair after physical source validation."""
    receipt = validate_materialized_release(receipt_path)
    campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
    spec = campaign["release_spec"]
    if receipt["release_spec"] != spec:
        raise ValueError("common release differs from component campaign")
    mapping = resolved_projection if resolved_projection is not None else campaign["simion_projection"]
    if (
        mapping.get("source_frame") != spec["frame_id"]
        or mapping.get("workbench_mapping") != "identity_xyz_with_local_exit_z_translation_v1"
        or mapping.get("iob_origin_rule") != "negative_half_transverse_span__local_z_zero_v1"
        or set(mapping) != _PROJECTION_FIELDS
        or not isinstance(mapping.get("local_pa_span_mm"), list)
        or len(mapping["local_pa_span_mm"]) != 3
    ):
        raise ValueError("component SIMION projection contract is unsupported")
    spans = tuple(_finite(value, "component SIMION PA span") for value in mapping["local_pa_span_mm"])
    if min(spans) <= 0.0:
        raise ValueError("component SIMION PA span is invalid")
    exit_z = _finite(mapping["local_exit_z_mm"], "resolved local exit")
    source_minimum, source_maximum = _load_provider_source_interval(provider_plan_path, exit_z)
    rows = _load_rows(receipt, int(spec["particle_count"]))
    beams: list[dict[str, Any]] = []
    source_states: list[dict[str, Any]] = []
    for expected, row in enumerate(rows, 1):
        source_z = _finite(row["z_mm"], "release source z")
        if not source_minimum < source_z < source_maximum:
            raise ValueError("release source is outside the provider first acceleration gap")
        vx, vy, vz = (_finite(row[key], key) for key in ("vx_m_s", "vy_m_s", "vz_m_s"))
        energy = _finite(spec["sampling"]["kinetic_energy"]["center_ev"], "release energy")
        time_of_birth = _finite(row["birth_time_s"], "release birth time") * 1.0e6
        x, y = _finite(row["x_mm"], "release x"), _finite(row["y_mm"], "release y")
        z = source_z + exit_z
        beams.append({"tob": time_of_birth, "mass": _finite(row["mass_amu"], "release mass"),
                      "charge": int(row["charge_state"]), "x": x, "y": y, "z": z,
                      "direction": (vx, vy, vz), "ke": energy, "cwf": 1, "color": 3})
        source_states.append({"particle_id": expected, "t": time_of_birth, "x": x, "y": y, "z": z,
                              "vx": vx * 1.0e-3, "vy": vy * 1.0e-3, "vz": vz * 1.0e-3, "ke": energy})
    fly2_path.parent.mkdir(parents=True, exist_ok=True)
    fly2_path.write_text(render_standard_beams(beams), encoding="ascii", newline="\n")
    source_states_path.parent.mkdir(parents=True, exist_ok=True)
    source_states_path.write_text(render_source_states(source_states), encoding="ascii", newline="\n")
    return {
        "schema_version": 1,
        "role": "orthogonal_accelerator_component_focus_simion_projection",
        "status": "materialized",
        "mapping": mapping,
        "provider_plan_sha256": file_sha256(provider_plan_path),
        "provider_source_exit_interval_mm": [source_minimum, source_maximum],
        "particle_count": len(beams),
        "release_receipt_sha256": file_sha256(receipt_path),
        "release_state_table_sha256": receipt["state_table"]["sha256"],
        "fly2_sha256": file_sha256(fly2_path),
        "source_states_sha256": file_sha256(source_states_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-receipt", required=True, type=Path)
    parser.add_argument("--campaign", required=True, type=Path)
    parser.add_argument("--provider-plan", required=True, type=Path)
    parser.add_argument("--resolved-projection", type=Path)
    parser.add_argument("--fly2", required=True, type=Path)
    parser.add_argument("--source-states", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        projection = (json.loads(arguments.resolved_projection.read_text(encoding="utf-8"))
                      if arguments.resolved_projection else None)
        result = materialize(arguments.release_receipt, arguments.campaign, arguments.provider_plan,
                             arguments.fly2, arguments.source_states, projection)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ACCELERATOR_COMPONENT_FOCUS_SOURCE=FAIL ERROR={error}")
        return 1
    arguments.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"ACCELERATOR_COMPONENT_FOCUS_SOURCE=PASS PARTICLES={result['particle_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

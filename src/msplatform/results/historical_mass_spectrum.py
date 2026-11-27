"""Decode sealed v1 OA-TOF mass-spectrum records without executing a producer.

Original solver-local IDs, declared mother populations, signed charge states
and selected geometry remain explicit. Calibration and plots belong to
``analysis.mass_spectrum``; reading history does not grant scientific qualification.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from msplatform.results import single_reflection_particle_table as particle_table
from msplatform.contracts.particle_identity import parse_charge_state


OUTPUT_NAMES = ("mass_spectrum_particles.csv", "mass_spectrum_summary.csv",
    "mass_peak_shape_comparison.csv", "mass_spectrum_metrics.json",
    "mass_spectrum_comparison.png", "mass_detector_landing_comparison.png")



def _historical_comsol_completion(path: Path, *, run_id: str) -> dict[str, Any]:
    """Decode the exact v1 completion record without launching its former owner."""
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("role") != "comsol_launcher_completion"
            or value.get("run_id") != run_id
            or not isinstance(value.get("operations"), list)
            or not value["operations"] or not isinstance(value.get("host_release"), dict)):
        raise ValueError("COMSOL completion receipt identity differs")
    release = value["host_release"]
    if (type(release.get("inherited")) is not bool
            or release.get("error") is not None
            or (release.get("inherited") is False and (
                not isinstance(release.get("result"), dict)
                or release["result"].get("status") != "released"
                or release["result"].get("token") != release.get("token")))):
        raise ValueError("COMSOL writer or host release remains unknown")
    for operation in value["operations"]:
        observation = operation.get("observation")
        if (not isinstance(observation, dict) or observation.get("exit_confirmed") is not True
                or any(type(observation.get(name)) is not int for name in (
                    "process_id", "process_started_at_utc_ticks"))
                or observation["process_id"] <= 0
                or observation["process_started_at_utc_ticks"] <= 0):
            raise ValueError("COMSOL writer completion is unknown")
    return value


def read_historical_mass_selection(guarded: Any, manifest_record: dict[str, Any]) -> dict[str, Any]:
    """Decode exactly the consumed v1 records while their caller-held guards live.

    The caller supplies the public execution guard, keeps it alive through every
    read and transfers exact records to any worker that continues consuming them.
    The historical source is never used as a producer or lifecycle owner.
    """
    source, config = guarded.root, guarded.config
    if config.get("role") not in (None, "oa_tof_mass_spectrum_run_config"):
        raise ValueError("Source is not an oa-TOF mass-spectrum parent")
    inputs = {name: guarded.input(name) for name in ("mode_config", "resolved_geometry")}
    if any(not Path(record["path"]).is_relative_to(source / "inputs") for record in inputs.values()):
        raise ValueError("Parent input binding differs")
    mode = json.loads(Path(inputs["mode_config"]["path"]).read_text(encoding="utf-8-sig"))
    species = mode.get("species")
    if (mode.get("schema_version") != 1 or mode.get("mode") != "mass_spectrum_candidate"
            or mode.get("role") != "oa_tof_candidate_mass_spectrum_mode"
            or not isinstance(species, list) or len(species) < 3
            or any(not isinstance(item, dict) for item in species)):
        raise ValueError("Parent mass-spectrum species are missing")
    ids = [item.get("species_id") for item in species]
    if (any(not isinstance(value, str) or not value or Path(value).name != value
            or "/" in value or "\\" in value or value in (".", "..") for value in ids)
            or len(ids) != len(set(ids))):
        raise ValueError("Parent species identifiers are invalid or duplicated")
    counts = [item.get("particle_count") for item in species]
    if any(type(count) is not int or count < 1 for count in counts):
        raise ValueError("Parent emitted counts are invalid")
    exports = {"simion_csv": guarded.output("results/simion_particles.csv"),
               "simion_summary": guarded.output("results/simion_summary.json")}
    if json.loads(Path(exports["simion_summary"]["path"]).read_text(encoding="utf-8-sig")).get("Hit") != sum(counts):
        raise ValueError("Parent SIMION full-mother detection requirement is not satisfied")
    for name, count in zip(ids, counts, strict=True):
        exports[f"comsol_{name}"] = guarded.output(f"comsol/{name}.csv")
        report = guarded.output(f"logs/{name}.report.txt")
        completion = guarded.output(f"logs/{name}.comsol_completion.json")
        receipt = _historical_comsol_completion(Path(completion["path"]), run_id=config["run_id"])
        expected = f"DETECTED={count}/{count}"
        if (not all(int(row["observation"]["returncode"]) == 0 for row in receipt["operations"])
                or expected not in Path(report["path"]).read_text(encoding="utf-8-sig").splitlines()):
            raise ValueError(f"COMSOL species lacks {expected}")
        exports[f"report_{name}"] = report
        exports[f"completion_{name}"] = completion
    return dict(manifest_record=manifest_record, run_id=config["run_id"],
        source_directory=str(source), inputs=inputs, exports=exports,
        execution=config.get("execution", {}),
        particle_source_provenance=config.get("particle_source_provenance", []))


def load_mode(path: Path) -> dict[str, Any]:
    """Read and validate a candidate mass-spectrum mode and its species."""
    mode = json.loads(path.read_text(encoding="utf-8-sig"))
    if mode.get("role") != "oa_tof_candidate_mass_spectrum_mode":
        raise ValueError("Not an oa-TOF candidate mass-spectrum mode")
    species = mode.get("species", [])
    if len(species) < 3:
        raise ValueError("A calibration spectrum requires at least three species")
    ids = [str(item["species_id"]) for item in species]
    if len(ids) != len(set(ids)):
        raise ValueError("species_id values must be unique")
    for item in species:
        mass = float(item["mass_amu"])
        charge = parse_charge_state(item["charge_state"])
        mz = float(item["mz"])
        if not np.isfinite(mass) or mass <= 0 or not np.isfinite(mz) or mz <= 0:
            raise ValueError(f"Invalid species definition: {item}")
        if not np.isclose(mass / abs(charge), mz, rtol=0, atol=1e-12):
            raise ValueError(f"m/z is inconsistent for {item['species_id']}")
        item["charge_state"] = charge
        count = item["particle_count"]
        if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
            raise ValueError("particle_count must be a positive integer")
    return mode



def _normalized_simion_rows(path: Path, detector_x: float, detector_y: float) -> pd.DataFrame:
    # Keep integer fields lexical until validation; float inference can round them.
    raw = pd.read_csv(path, dtype={"Ion": "string", "ChargeState": "string"})
    required = {
        "Ion", "MassAmu", "ChargeState", "TofUs", "XMm", "YMm", "Hit"
    }
    missing = required.difference(raw.columns)
    if missing:
        raise ValueError(f"SIMION mixed-species CSV lacks columns: {sorted(missing)}")
    hit = raw["Hit"].astype(str).str.lower().isin({"true", "1", "yes"})
    result = pd.DataFrame(
        {
            "particle_id": particle_table.validated_particle_ids(raw["Ion"], "SIMION"),
            "mass_amu": pd.to_numeric(raw["MassAmu"], errors="raise"),
            "charge_state": raw["ChargeState"].map(parse_charge_state),
            "tof_us": pd.to_numeric(raw["TofUs"], errors="coerce"),
            "detector_x_mm": (
                pd.to_numeric(raw["XMm"], errors="coerce")
                - detector_x
            ),
            "detector_y_mm": (
                pd.to_numeric(raw["YMm"], errors="coerce")
                - detector_y
            ),
            "hit": hit,
        }
    )
    for source, target in (
        ("X0Mm", "initial_x_mm"),
        ("Y0Mm", "initial_y_mm"),
        ("Z0Mm", "initial_z_mm"),
        ("EnergyEv", "initial_energy_eV"),
    ):
        if source in raw:
            result[target] = pd.to_numeric(raw[source], errors="coerce")
    return result


def _normalized_comsol_rows(path: Path, emitted: int, detector_x: float, detector_y: float) -> pd.DataFrame:
    source, source_format = particle_table.read_source_table(path)
    id_column = particle_table.find_column(source, particle_table.PARTICLE_ID_ALIASES, True)
    ids = particle_table.validated_particle_ids(source[id_column], "COMSOL")
    if len(ids) > emitted:
        raise ValueError("COMSOL has more particle rows than emitted particles")
    if (ids > emitted).any():
        raise ValueError("COMSOL particle ID exceeds its species mother population")
    result, _ = particle_table.normalize_particle_table(source, source_format, detector_x, detector_y)
    return result

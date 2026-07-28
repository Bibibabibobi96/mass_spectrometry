"""Validate and resolve one consumed source from a governed paired bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from common.contracts.particle_state import canonical_sources, ion11_sources
from projects.rf_quadrupole_ion_optics.analysis.paired_particle_source_bundle import (
    load_declared_bundle_specification,
    validate_bundle,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _validate_representation_equivalence(
    ion11_path: Path, canonical10_path: Path
) -> None:
    ion11 = ion11_sources(ion11_path)
    canonical10 = canonical_sources(canonical10_path)
    if set(ion11) != set(canonical10):
        raise ValueError("ION11 and canonical particle IDs differ")
    fields = (
        "time_us",
        "elapsed_time_us",
        "axial_z_mm",
        "transverse_x_mm",
        "transverse_y_mm",
        "velocity_axial_m_s",
        "velocity_x_m_s",
        "velocity_y_m_s",
        "kinetic_energy_eV",
    )
    for particle_id in sorted(ion11):
        for field in fields:
            tolerance = 1e-6 if field.startswith("velocity_") else 1e-9
            if abs(ion11[particle_id][field] - canonical10[particle_id][field]) > tolerance:
                raise ValueError(
                    "ION11 and canonical source states differ: "
                    f"particle={particle_id} field={field}"
                )


def resolve_binding(
    metadata_path: Path,
    source_family_path: Path,
    distribution_path: Path,
    resolved_design_path: Path,
    operating_point_id: str,
    particle_count: int,
    consumed_representation: str,
    expected_consumed_path: Path,
) -> dict[str, Any]:
    bundle_specification = load_declared_bundle_specification(
        metadata_path,
        source_family_path,
    )
    metadata = validate_bundle(
        metadata_path,
        source_family_path,
        distribution_path,
        resolved_design_path,
        **bundle_specification,
    )
    if consumed_representation not in {"ion11", "canonical10"}:
        raise ValueError("consumed representation must be ion11 or canonical10")
    entries: dict[str, dict[str, Any]] = {}
    for entry in metadata["artifacts"]:
        if (
            entry["operating_point_id"] == operating_point_id
            and int(entry["particle_count"]) == particle_count
        ):
            entries[entry["representation"]] = entry
    if set(entries) != {"ion11", "canonical10"}:
        raise ValueError("paired source bundle lacks the requested representation pair")
    root = metadata_path.resolve().parent
    paths = {
        representation: (root / entry["relative_path"]).resolve()
        for representation, entry in entries.items()
    }
    consumed_path = paths[consumed_representation]
    if consumed_path != expected_consumed_path.resolve():
        raise ValueError("consumed particle table differs from its bundle artifact")
    for representation, path in paths.items():
        entry = entries[representation]
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"{representation} source SHA-256 differs from bundle metadata")
    _validate_representation_equivalence(paths["ion11"], paths["canonical10"])
    return {
        "schema_version": 1,
        "role": "rf_quadrupole_paired_particle_source_binding",
        "bundle_metadata_path": str(metadata_path.resolve()),
        "bundle_metadata_sha256": sha256(metadata_path),
        "source_sample_family_sha256": metadata["sample_family_sha256"],
        "source_family_sha256": metadata["inputs"]["source_family_sha256"],
        "distribution_sha256": metadata["inputs"]["distribution_sha256"],
        "latent_sha256": metadata["latent_sha256"],
        "coordinate_mapping_version": metadata["coordinate_mapping_version"],
        "representation_equivalence": "PASS",
        "operating_point_id": operating_point_id,
        "particle_count": particle_count,
        "representation": consumed_representation,
        "consumed_path": str(consumed_path),
        "consumed_sha256": entries[consumed_representation]["sha256"],
        "ion11_path": str(paths["ion11"]),
        "ion11_sha256": entries["ion11"]["sha256"],
        "canonical10_path": str(paths["canonical10"]),
        "canonical10_sha256": entries["canonical10"]["sha256"],
        "n1000_parent": entries[consumed_representation]["n1000_parent"],
        "ion11_n1000_parent": entries["ion11"]["n1000_parent"],
        "canonical10_n1000_parent": entries["canonical10"]["n1000_parent"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-metadata", required=True, type=Path)
    parser.add_argument("--source-family", required=True, type=Path)
    parser.add_argument("--distribution", required=True, type=Path)
    parser.add_argument("--resolved-design", required=True, type=Path)
    parser.add_argument("--operating-point", required=True)
    parser.add_argument("--particle-count", required=True, type=int)
    parser.add_argument(
        "--consumed-representation",
        required=True,
        choices=("ion11", "canonical10"),
    )
    parser.add_argument("--expected-consumed", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = resolve_binding(
        args.bundle_metadata,
        args.source_family,
        args.distribution,
        args.resolved_design,
        args.operating_point,
        args.particle_count,
        args.consumed_representation,
        args.expected_consumed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "RFQUAD_PAIRED_SOURCE_BINDING=PASS "
        f"POINT={result['operating_point_id']} N={result['particle_count']} "
        f"REPRESENTATION={result['representation']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

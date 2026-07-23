"""Convert an eight-column historical particle source into governed canonical form."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from common.multipole.particle_source_preflight import COLUMNS, validate_source


LEGACY_COLUMNS = COLUMNS[:-2]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def convert(
    legacy_source: Path,
    resolved: dict[str, Any],
    species_metadata: dict[str, Any],
    output: Path,
    *,
    species_metadata_sha256: str | None = None,
) -> dict[str, Any]:
    """Append governed species fields, preflight the result, and return lineage."""
    if resolved.get("role") != "multipole_resolved_design_do_not_edit":
        raise ValueError("legacy conversion requires a governed resolved design")
    if "mass_amu" not in species_metadata or "charge_state" not in species_metadata:
        raise ValueError("species metadata must declare mass_amu and charge_state")
    mass = float(species_metadata["mass_amu"])
    charge = int(species_metadata["charge_state"])
    if charge != int(resolved["particle_source"]["charge_state"]):
        raise ValueError("species metadata charge differs from the resolved design")
    with legacy_source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != LEGACY_COLUMNS:
            raise ValueError(f"legacy particle source columns differ: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise ValueError("legacy particle source is empty")

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        **{column: row[column] for column in LEGACY_COLUMNS},
                        "mass_amu": format(mass, ".17g"),
                        "charge_state": str(charge),
                    }
                )
        preflight = validate_source(temporary, resolved)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()

    return {
        "schema_version": 1,
        "role": "multipole_canonical_particle_source_lineage",
        "legacy_source_sha256": sha256(legacy_source),
        "canonical_source_sha256": sha256(output),
        "parent_resolved_design_sha256": resolved["resolved_sha256"],
        "species_metadata_sha256": species_metadata_sha256
        or hashlib.sha256(
            json.dumps(species_metadata, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest().upper(),
        "preserved_columns": LEGACY_COLUMNS,
        "appended_columns": ["mass_amu", "charge_state"],
        "mass_amu": mass,
        "charge_state": charge,
        "canonical_preflight": preflight,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-source", required=True, type=Path)
    parser.add_argument("--resolved-design", required=True, type=Path)
    parser.add_argument("--species-metadata", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--lineage-output", required=True, type=Path)
    args = parser.parse_args()
    resolved = json.loads(args.resolved_design.read_text(encoding="utf-8-sig"))
    species = json.loads(args.species_metadata.read_text(encoding="utf-8-sig"))
    lineage = convert(
        args.legacy_source,
        resolved,
        species,
        args.output,
        species_metadata_sha256=sha256(args.species_metadata),
    )
    args.lineage_output.parent.mkdir(parents=True, exist_ok=True)
    args.lineage_output.write_text(
        json.dumps(lineage, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "MULTIPOLE_LEGACY_SOURCE_CONVERSION=PASS "
        f"PARTICLES={lineage['canonical_preflight']['particle_count']} "
        f"SHA256={lineage['canonical_source_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

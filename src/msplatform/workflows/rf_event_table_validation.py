"""RF event-table protocol, distinct from neutral transfer-state snapshots.

Preserves the deployed source/terminal, single-event, phase and plane checks.
Source formats are loaded only by CLI, never by a core column-order consumer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from msplatform.components.rf_multipole.event_table import read_canonical_rf_source_expectations, validate_rf_event_table

def main() -> None:
    from msplatform.backends.simion.rf_ion11_source import read_ion11_source_states

    parser = argparse.ArgumentParser(description=__doc__, epilog="ION11 columns include mass_amu and signed integer charge_state; energy is kinetic eV, not energy per charge. This reader preserves the deployed source protocol and adds no charge-policy validation.")
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--particles", required=True, type=Path)
    parser.add_argument("--source-format", choices=("ion11", "canonical"), required=True, help="11-column SIMION ION CSV or canonical RF source CSV")
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--axial-offset-mm", type=float, default=0.0)
    parser.add_argument("--mass-amu", type=float)
    parser.add_argument("--frequency-hz", type=float, required=True, help="RF frequency in Hz")
    parser.add_argument("--phase-rad", type=float, default=0.0, help="RF phase offset in radians")
    parser.add_argument("--rod-exit-mm", type=float)
    parser.add_argument("--handoff-mm", type=float)
    parser.add_argument("--solver", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    columns = None
    enums = None
    rod_exit_mm = args.rod_exit_mm
    handoff_mm = args.handoff_mm
    if args.contract:
        contract = json.loads(args.contract.read_text(encoding="utf-8-sig"))
        columns = contract["particle_state_columns"]
        enums = contract["enums"]
        rod_exit_mm = float(contract["planes"]["rod_exit"]["z_mm"])
        handoff_mm = float(contract["planes"]["handoff"]["z_mm"])
    sources = (
        read_ion11_source_states(args.particles, args.axial_offset_mm)
        if args.source_format == "ion11"
        else read_canonical_rf_source_expectations(args.particles, args.mass_amu)
    )
    report = validate_rf_event_table(
        args.state, sources, args.frequency_hz, args.phase_rad,
        rod_exit_mm, handoff_mm, columns, enums,
    )
    report["solver"] = args.solver
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()

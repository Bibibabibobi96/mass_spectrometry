"""Generate the monolithic three-dimensional MR-TOF Candidate GEM.

This generator never imports oa-TOF assets.  It keeps the project coordinate
frame directly in GEM local coordinates: x is transverse focusing, y is the
slow-drift direction, z is the fast mirror-reflection direction, and z=0 is
the centre/injection handoff plane.  CAD provides the mirror and prism local
envelopes; the Stripe contour and global transforms are theory-derived until
the broken archived ion-foil parts are recovered.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
    load_contract,
)


ELECTRODE_IDS = {
    "right_mirror": (1, 2, 3, 4, 5),
    "left_mirror": (6, 7, 8, 9, 10),
    "drift_stripe_set_1": (11, 12),
    "drift_stripe_set_2": (13, 14),
    "central_ground": 15,
    "prisms": (16, 17),
    "prism_ground_shields": (18, 19, 20, 21),
    "accelerator": (22, 23, 24),
    "detector": 25,
}


def build_full_candidate_gem(contract_path: Path) -> str:
    """Return a SIMION 2020 legacy-GEM source for the complete Candidate."""
    contract = load_contract(contract_path)
    if contract["status"] != "candidate_provisional_not_cad_audited":
        raise CandidateContractError("full geometry must retain the qualified Candidate status")
    if contract["accelerator"]["topology"] != "two_zone_orthogonal_pulsed":
        raise CandidateContractError("full geometry requires the MR-TOF two-zone accelerator")
    return """; Full MR-TOF 3D SIMION Candidate (not Formal).
; Project coordinates are native GEM coordinates: x focus, y drift, z reflection.
; CAD audit: mirror/prism envelopes and physical Stripe B-spline edge profiles
; are resolved from read-only SolidWorks evidence.  The raw Foil-1/Foil-3
; overlap is moved to a serial, non-overlapping dual-Stripe Candidate layout.
; IDs: 1..5 right mirror; 6..10 left mirror; 11..14 four physical Stripes;
; 15 central ground; 16..17 triangular prisms; 18..21 grounded shields;
; 22 repeller; 23 ideal grid-1; 24 ideal grid-2; 25 numerical detector.
# local mmgu_xy = _G.var and _G.var.mmgu_xy or 4.0
# local mmgu_z = _G.var and _G.var.mmgu_z or 0.4
# local focus_phase_z = 0.12918680341102168
# local x_span, y_span, z_span = 180, 680, 700
# local nx = math.floor(x_span/mmgu_xy + 0.5) + 1
# local ny = math.floor(y_span/mmgu_xy + 0.5) + 1
# local nz = math.floor(z_span/mmgu_z + 0.5) + 1
pa_define($(nx),$(ny),$(nz),planar,none,electrostatic,, $(mmgu_xy),$(mmgu_xy),$(mmgu_z),surface=none)
locate($(x_span/2),$(y_span/2),$(z_span/2)) {
  ; Non-accelerator hardware is phase-shifted so the PA-instance translation
  ; maps its physical central plane to project z=0. The raw accelerator grids
  ; remain at local rows -33.6 and 0 mm, preserving native-grid alignment.
  locate(0,0,$(focus_phase_z)) {
  ; Five CAD-envelope mirrors: local slow length 600 mm and transverse width 125 mm.
  e(1) { box3D(-62.5,-300,80,62.5,300,135) }
  e(2) { box3D(-62.5,-300,141,62.5,300,198) }
  e(3) { box3D(-62.5,-300,204,62.5,300,231) }
  e(4) { box3D(-62.5,-300,237,62.5,300,262) }
  e(5) { box3D(-62.5,-300,268,62.5,300,297) }
  e(6) { box3D(-62.5,-300,-135,62.5,300,-80) }
  e(7) { box3D(-62.5,-300,-198,62.5,300,-141) }
  e(8) { box3D(-62.5,-300,-231,62.5,300,-204) }
  e(9) { box3D(-62.5,-300,-262,62.5,300,-237) }
  e(10) { box3D(-62.5,-300,-297,62.5,300,-268) }
  ; CAD Foil-1/3 long B-spline edges are represented as project y-z profiles.
  ; Raw CAD zones overlap; Foil-1 is shifted outwards by 35 mm so the two
  ; independent voltage regions are serial with a positive axial gap.
  e(11) { extrude_yz(-12,12) { polyline(-390,121.3,-326,104.9,-263,90.8,-214,84.5,-181,83.7,-131,86.6,-90,92.6,-41,99.4,0,99.1,0,132,-390,132) } }
  e(12) { extrude_yz(-12,12) { polyline(-390,-121.3,-326,-104.9,-263,-90.8,-214,-84.5,-181,-83.7,-131,-86.6,-90,-92.6,-41,-99.4,0,-99.1,0,-132,-390,-132) } }
  e(13) { extrude_yz(-12,12) { polyline(-390,38.9,-326,26.8,-261,17.3,-212,14.7,-179,16.3,-130,23.0,-90,31.8,-41,42.0,0,44.6,0,59.5,-41,59.8,-90,53.0,-131,47.0,-181,44.0,-230,46.4,-279,54.2,-326,65.3,-390,81.7) } }
  e(14) { extrude_yz(-12,12) { polyline(-390,-38.9,-326,-26.8,-261,-17.3,-212,-14.7,-179,-16.3,-130,-23.0,-90,-31.8,-41,-42.0,0,-44.6,0,-59.5,-41,-59.8,-90,-53.0,-131,-47.0,-181,-44.0,-230,-46.4,-279,-54.2,-326,-65.3,-390,-81.7) } }
  ; Centred CAD Ion-Foil-2 envelope, reserved as the grounded prism corridor.
  e(15) { box3D(-12,-390,-12,12,2,12) }
  ; Two CAD-placed triangular prism groups, split into their measured x halves.
  e(16) { extrude_yz(-12,-2) { polyline(42.828,-90,67.828,-90,67.828,-40) } extrude_yz(2,12) { polyline(42.828,-90,42.828,-40,67.828,-40) } }
  e(17) { extrude_yz(-12,-2) { polyline(3.536,-20,23.536,-20,23.536,20) } extrude_yz(2,12) { polyline(3.536,-20,3.536,20,23.536,20) } }
  e(18) { box3D(-24,38,-96,-12,72,-34) }
  e(19) { box3D(12,38,-96,24,72,-34) }
  e(20) { box3D(-24,-2,-26,-12,28,26) }
  e(21) { box3D(12,-2,-26,24,28,26) }
  e(25) { box3D(-25,285,-5,25,285,5) }
  }
  ; Independent two-zone accelerator; z=0 focus is established by workbench placement.
  e(22) { fill { within { box3D(-30,-310,-41.6,30,-250,-39.6) } notin { box3D(-10,-305,-42.6,10,-255,-38.6) } } }
  e(23) { box3D(-30,-310,-33.6,30,-250,-33.6) }
  e(24) { box3D(-30,-310,0,30,-250,0) }
}
"""


def write_full_candidate_gem(contract_path: Path, output_path: Path) -> None:
    """Write line-feed GEM source suitable for SIMION's ``gem2pa`` command."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_full_candidate_gem(contract_path), encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_full_candidate_gem(args.contract, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

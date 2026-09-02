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
; CAD audit: mirror/prism envelopes are CAD evidence; Stripe curves/transforms are
; theory-derived pending recovery of unreadable archived ion-foil parts.
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
  ; Theory-derived, tapered face-to-face dual Stripe pairs. Each lies on a distinct z slab.
  e(11) { intersect { extrude_xy() { polyline(-62,-160,-38,-140,-34,0,-38,140,-62,160) } box3D(-90,-340,-4,90,340,-2) } }
  e(12) { intersect { extrude_xy() { polyline(62,-160,38,-140,34,0,38,140,62,160) } box3D(-90,-340,-4,90,340,-2) } }
  e(13) { intersect { extrude_xy() { polyline(-62,-160,-42,-140,-38,0,-42,140,-62,160) } box3D(-90,-340,2,90,340,4) } }
  e(14) { intersect { extrude_xy() { polyline(62,-160,42,-140,38,0,42,140,62,160) } box3D(-90,-340,2,90,340,4) } }
  e(15) { box3D(-9,-300,-1,9,300,1) }
  ; Triangular prism faces retain the audited 20--25 mm transverse envelope.
  e(16) { intersect { extrude_xy() { polyline(-55,-230,-30,-230,-42,-180) } box3D(-90,-340,-5,90,340,5) } }
  e(17) { intersect { extrude_xy() { polyline(55,230,30,230,42,180) } box3D(-90,-340,-5,90,340,5) } }
  e(18) { fill { within { box3D(-72,-245,-12,-20,-165,12) } notin { box3D(-65,-238,-8,-27,-172,8) } } }
  e(19) { fill { within { box3D(20,165,-12,72,245,12) } notin { box3D(27,172,-8,65,238,8) } } }
  e(20) { box3D(-72,-245,-12,-20,-240,12) }
  e(21) { box3D(20,240,-12,72,245,12) }
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

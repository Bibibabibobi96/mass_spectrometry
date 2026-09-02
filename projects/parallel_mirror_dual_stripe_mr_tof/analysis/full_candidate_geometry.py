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
# local x_span, y_span, z_span = 180, 680, 900
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
  ; Five CAD-envelope mirror stages with an aligned 90 mm Candidate beam slot.
  e(1) { fill { within { box3D(-62.5,-300,190,62.5,300,245) } notin { box3D(-45,-300,175,45,10,422) } } }
  e(2) { fill { within { box3D(-62.5,-300,251,62.5,300,308) } notin { box3D(-45,-300,175,45,10,422) } } }
  e(3) { fill { within { box3D(-62.5,-300,314,62.5,300,341) } notin { box3D(-45,-300,175,45,10,422) } } }
  e(4) { fill { within { box3D(-62.5,-300,347,62.5,300,372) } notin { box3D(-45,-300,175,45,10,422) } } }
  e(5) { fill { within { box3D(-62.5,-300,378,62.5,300,407) } notin { box3D(-45,-300,175,45,10,422) } } }
  e(6) { fill { within { box3D(-62.5,-300,-245,62.5,300,-190) } notin { box3D(-45,-300,-422,45,10,-175) } } }
  e(7) { fill { within { box3D(-62.5,-300,-308,62.5,300,-251) } notin { box3D(-45,-300,-422,45,10,-175) } } }
  e(8) { fill { within { box3D(-62.5,-300,-341,62.5,300,-314) } notin { box3D(-45,-300,-422,45,10,-175) } } }
  e(9) { fill { within { box3D(-62.5,-300,-372,62.5,300,-347) } notin { box3D(-45,-300,-422,45,10,-175) } } }
  e(10) { fill { within { box3D(-62.5,-300,-407,62.5,300,-378) } notin { box3D(-45,-300,-422,45,10,-175) } } }
  ; CAD Foil-1/3 long B-spline edges are represented as project y-z profiles.
  ; Raw CAD zones overlap; Foil-3 is shifted by 50 mm and Foil-1 by 90 mm so
  ; independent voltage regions are serial with a positive axial gap.
  ; Preserve a 16 mm centred x-channel: the four physical CAD contours are
  ; resolved as opposing rails rather than solid beam blocks.
  e(11) { fill { within { extrude_yz(-12,12) { polyline(-390,176.3,-326,159.9,-263,145.8,-214,139.5,-181,138.7,-131,141.6,-90,147.6,-41,154.4,0,154.1,0,187,-390,187) } } notin { box3D(-8,-400,-250,8,10,250) } } }
  e(12) { fill { within { extrude_yz(-12,12) { polyline(-390,-176.3,-326,-159.9,-263,-145.8,-214,-139.5,-181,-138.7,-131,-141.6,-90,-147.6,-41,-154.4,0,-154.1,0,-187,-390,-187) } } notin { box3D(-8,-400,-250,8,10,250) } } }
  e(13) { fill { within { extrude_yz(-12,12) { polyline(-390,88.9,-326,76.8,-261,67.3,-212,64.7,-179,66.3,-130,73.0,-90,81.8,-41,92.0,0,94.6,0,109.5,-41,109.8,-90,103.0,-131,97.0,-181,94.0,-230,96.4,-279,104.2,-326,115.3,-390,131.7) } } notin { box3D(-8,-400,-250,8,10,250) } } }
  e(14) { fill { within { extrude_yz(-12,12) { polyline(-390,-88.9,-326,-76.8,-261,-67.3,-212,-64.7,-179,-66.3,-130,-73.0,-90,-81.8,-41,-92.0,0,-94.6,0,-109.5,-41,-109.8,-90,-103.0,-131,-97.0,-181,-94.0,-230,-96.4,-279,-104.2,-326,-115.3,-390,-131.7) } } notin { box3D(-8,-400,-250,8,10,250) } } }
  ; Centred CAD Ion-Foil-2 envelope, grounded except for the explicitly
  ; aligned injection aperture linking the two-zone accelerator to z=0.
  e(15) { fill { within { box3D(-12,-390,-12,12,2,12) } notin { box3D(-8,-310,-20,8,-250,20) } } }
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
  ; A full repeller plane establishes the first uniform extraction field. The
  ; source lies downstream in gap 1; only the two downstream grids are ideal.
  e(22) { box3D(-30,-310,-41.6,30,-250,-39.6) }
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

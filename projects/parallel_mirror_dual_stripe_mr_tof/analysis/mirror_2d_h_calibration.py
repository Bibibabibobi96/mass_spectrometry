#!/usr/bin/env python3
"""Calibrate an effective Berdnikov H from CAD cross-section FDM evidence.

This is a deliberately small, solver-independent two-dimensional Laplace
screen.  It retains the CAD 30-mm active slot, 4-mm inner-shield slot, five
axial bands and the closed outer E cover.  It is not a replacement for 3-D
BEM/FEM or a PA field, but it makes the analytic H input traceable rather than
guessing it from one mechanical dimension.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_l0 import step_response
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_geometry_parameters import derive_mirror_boundaries
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import load_contract


def calibrate(contract: dict, spacing_mm: float = 1.0) -> dict:
    mirror = contract["mirror"]
    x_half = float(mirror["outer_width_x_mm"]) / 2.0
    active_slot = float(mirror["beam_slot_width_mm"]) / 2.0
    shield_slot = float(mirror["grounded_inner_shield"]["slot_width_x_mm"]) / 2.0
    boundaries = derive_mirror_boundaries(mirror)
    edges = [float(value) for value in boundaries["active_start_z_mm"]]
    thicknesses = [float(value) for value in mirror["electrode_thicknesses_mm"]]
    end_z = float(boundaries["physical_E_active_end_z_mm"]) + float(mirror["outer_e_closure"]["thickness_z_mm"])
    x = np.arange(-x_half - 15.0, x_half + 15.0 + spacing_mm / 2.0, spacing_mm)
    z = np.arange(0.0, end_z + 30.0 + spacing_mm / 2.0, spacing_mm)
    nx, nz = len(x), len(z)
    fixed = np.zeros((nz, nx), dtype=bool)
    values = np.zeros((nz, nx), dtype=float)
    # The finite computational-domain boundary is grounded; that is not an
    # electrode assignment.  The physical closed outer cover belongs to E.
    fixed[[0, -1], :] = True
    fixed[:, [0, -1]] = True

    def conductor(z0: float, z1: float, half_slot: float, value: float) -> None:
        zi = (z >= z0 - 1e-9) & (z <= z1 + 1e-9)
        xi = (np.abs(x) >= half_slot - 1e-9) & (np.abs(x) <= x_half + 1e-9)
        fixed[np.ix_(zi, xi)] = True
        values[np.ix_(zi, xi)] = value

    inner = float(mirror["inner_face_z_mm"])
    inner_thickness = float(mirror["grounded_inner_shield"]["thickness_z_mm"])
    conductor(inner, inner + inner_thickness, shield_slot, 0.0)
    # Unit B step, with all other conductors grounded.  This is the single
    # basis field whose axis response is fitted to an ideal unit step.
    for index, (z0, thickness) in enumerate(zip(edges, thicknesses)):
        conductor(z0, z0 + thickness, active_slot, 1.0 if index == 1 else 0.0)
    conductor(float(boundaries["physical_E_active_end_z_mm"]), end_z, 0.0, 0.0)

    unknown = -np.ones((nz, nx), dtype=int)
    unknown[~fixed] = np.arange(np.count_nonzero(~fixed))
    count = int(np.count_nonzero(~fixed))
    matrix = lil_matrix((count, count), dtype=float)
    rhs = np.zeros(count)
    for iz, ix in zip(*np.where(~fixed)):
        row = unknown[iz, ix]
        matrix[row, row] = -4.0
        for jz, jx in ((iz - 1, ix), (iz + 1, ix), (iz, ix - 1), (iz, ix + 1)):
            if fixed[jz, jx]:
                rhs[row] -= values[jz, jx]
            else:
                matrix[row, unknown[jz, jx]] = 1.0
    values[~fixed] = spsolve(matrix.tocsr(), rhs)
    axis = values[:, int(np.argmin(np.abs(x)))]
    # Fit around the B entrance, excluding the metal band itself and distant
    # end effects.  Amplitude and offset absorb finite-box effects; H is the
    # physically relevant shape parameter.
    mask = (z >= edges[1] - 45.0) & (z <= edges[1] + 45.0)
    sample_z = z[mask]
    sample_phi = axis[mask]

    def residual(parameters: np.ndarray) -> np.ndarray:
        offset, amplitude, h = parameters
        return offset + amplitude * np.array([step_response((value - edges[1]) / h) for value in sample_z]) - sample_phi

    solution = least_squares(residual, (0.0, 1.0, 15.0), bounds=((-1.0, 0.0, 1.0), (1.0, 2.0, 100.0)))
    return {
        "status": "fdm_2d_effective_h_candidate_not_bem_or_3d_validated",
        "grid_spacing_mm": spacing_mm,
        "domain_x_mm": [float(x[0]), float(x[-1])],
        "domain_z_mm": [float(z[0]), float(z[-1])],
        "unit_basis": "B electrode = +1 V; all other CAD cross-section conductors and domain boundary = 0 V",
        "cad_geometry": {"active_slot_width_mm": active_slot * 2.0, "inner_shield_slot_width_mm": shield_slot * 2.0, "edges_mm": edges, "outer_e_cover_start_z_mm": float(boundaries["physical_E_active_end_z_mm"])},
        "fit": {"effective_h_mm": float(solution.x[2]), "offset": float(solution.x[0]), "amplitude": float(solution.x[1]), "rms": float(np.sqrt(np.mean(residual(solution.x) ** 2))), "success": bool(solution.success)},
        "limitations": ["2-D finite-difference screen", "finite exterior boundary", "unit-B fit only", "not a unit-field PA/BEM/FEM validation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--spacing-mm", type=float, default=1.0)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    result = calibrate(load_contract(arguments.contract), arguments.spacing_mm)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"MIRROR_2D_H_CALIBRATION: H={result['fit']['effective_h_mm']:.6g} mm output={arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

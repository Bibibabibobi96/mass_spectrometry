"""Frozen-contract fixtures for read-only native MR accelerator PA verification.

This is a long-lived test generator, not a production geometry authority. Run
with --contract <run-local.json> --output <run-local.csv>, or --self-test.
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    geometry_fingerprint, resolve_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError, derive_two_zone_placement, load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.split_candidate_geometry import (
    ACCELERATOR_LOCAL_ELECTRODE_IDS,
)


def build_samples(contract: dict) -> list[tuple]:
    """Sample resolved physical boundaries on the declared local PA lattice."""
    resolved = resolve_geometry(contract)
    acc = contract["accelerator"]
    mesh = contract["simion"]["component_mesh_mm_per_gu"]["accelerator"]
    span = contract["simion"]["accelerator_pa_span_mm"]
    placement = derive_two_zone_placement(contract)
    origin = (-span[0]/2, placement.focus_y_mm-span[1]/2,
              placement.exit_grid_z_mm-acc["pa_local_margin_z_mm"])
    shift = -origin[2]
    dimensions = tuple(round(span[i]/mesh[i])+1 for i in range(3))
    rows = [("dimensions", "pa_nodes", *dimensions, 0),
            ("mesh", "mm_per_gu", *mesh, 0),
            ("origin", "project_mm", *origin, 0),
            ("identity", geometry_fingerprint(resolved), 0, 0, 0, 0)]

    def node(mm: float, axis: int) -> int:
        value = mm/mesh[axis]
        index = round(value)
        # Only round representational noise; physical off-grid points fail.
        tolerance = 64*math.ulp(max(1.0, abs(value)))
        if abs(value-index) > tolerance:
            raise CandidateContractError(f"native sample off PA lattice: axis={axis} local_mm={mm}")
        if not 0 <= index < dimensions[axis]:
            raise CandidateContractError("native geometry sample outside PA")
        return index

    def sample(label: str, x: float, y: float, z: float, expected: int) -> None:
        indices = (node(x+span[0]/2, 0), node(y+span[1]/2, 1), node(z, 2))
        rows.append(("sample", label, *indices, expected))

    supports = resolved["accelerator_grid_support_frames"]
    rings = [{**ring, "grid_z_mm": None,
              "front_z_mm": ring["center_z_mm"]-ring["thickness_z_mm"]/2,
              "back_z_mm": ring["center_z_mm"]+ring["thickness_z_mm"]/2,
              "outer_half_x_mm": supports[0]["outer_half_x_mm"],
              "outer_half_y_mm": supports[0]["outer_half_y_mm"],
              "aperture_half_x_mm": supports[0]["aperture_half_x_mm"],
              "aperture_half_y_mm": supports[0]["aperture_half_y_mm"]}
             for ring in resolved["accelerator_stage_2_rings"]]
    for item in [*supports, *rings]:
        eid = ACCELERATOR_LOCAL_ELECTRODE_IDS[item["id"]]
        front, back = item["front_z_mm"]+shift, item["back_z_mm"]+shift
        low, high = math.floor(front/mesh[2])-1, math.ceil(back/mesh[2])+1
        grid = None if item["grid_z_mm"] is None else node(item["grid_z_mm"]+shift, 2)
        ax, ay = item["aperture_half_x_mm"], item["aperture_half_y_mm"]
        # Pick a named existing node strictly inside frame material. This is
        # not a replacement for the exact aperture-boundary checks below.
        fx = math.floor((ax+item["outer_half_x_mm"])/2/mesh[0])*mesh[0]
        fy = math.floor((ay+item["outer_half_y_mm"])/2/mesh[1])*mesh[1]
        if not (ax < fx < item["outer_half_x_mm"] and ay < fy < item["outer_half_y_mm"]):
            raise CandidateContractError("mesh cannot resolve accelerator frame material")
        material_layers = 0
        for iz in range(low, high+1):
            z = iz*mesh[2]
            eps = 64*math.ulp(max(1.0, abs(z), abs(front), abs(back)))
            material = front-eps <= z <= back+eps
            material_layers += material
            for x, y, label in ((fx, 0, "frame_x"), (0, fy, "frame_y")):
                sample(f"id{eid}_{label}_{iz}", x, y, z, eid if material else 0)
            for x, y, label in ((0, 0, "axis"), (ax-mesh[0], 0, "bore_x"),
                                (0, ay-mesh[1], "bore_y")):
                sample(f"id{eid}_{label}_{iz}", x, y, z, eid if iz == grid else 0)
            if material:
                for x, y, label in ((ax, 0, "positive_x_wall"), (-ax, 0, "negative_x_wall"),
                                    (0, ay, "positive_y_wall"), (0, -ay, "negative_y_wall")):
                    sample(f"id{eid}_{label}_{iz}", x, y, z, eid)
        if material_layers < 2:
            raise CandidateContractError("mesh cannot represent nonzero accelerator ring thickness")
    exit_frame = supports[1]
    exit_id = ACCELERATOR_LOCAL_ELECTRODE_IDS[exit_frame["id"]]
    ground_id = ACCELERATOR_LOCAL_ELECTRODE_IDS[15]
    contact_z = node(exit_frame["grid_z_mm"]+shift, 2)+1
    z = contact_z*mesh[2]
    if z >= exit_frame["back_z_mm"]+shift:
        raise CandidateContractError("mesh cannot resolve exit frame to enclosure contact")
    for axis, outer in enumerate((exit_frame["outer_half_x_mm"], exit_frame["outer_half_y_mm"])):
        for sign in (-1, 1):
            for delta, expected in ((-mesh[axis], exit_id), (0, exit_id), (mesh[axis], ground_id)):
                xy = [0.0, 0.0]
                xy[axis] = sign*(outer+delta)
                sample(f"exit_contact_{axis}_{sign}_{delta}", *xy, z, expected)
    return rows


class AcceleratorGeometrySamplesTest(unittest.TestCase):
    def test_default_samples_cover_frames_rings_bores_and_contact(self) -> None:
        contract = load_contract(Path(__file__).resolve().parents[2]/"config/simion_candidate_two_zone.json")
        rows = build_samples(contract)
        self.assertEqual(rows[1][2:5], (0.25, 0.25, 0.1))
        samples = [row for row in rows if row[0] == "sample"]
        for eid in range(3, 10):
            axis = [row for row in samples if row[1].startswith(f"id{eid}_axis_")]
            self.assertEqual(sum(row[-1] != 0 for row in axis), int(eid in (3, 4)))
            frame = [row for row in samples if row[1].startswith(f"id{eid}_frame_x_")]
            self.assertEqual(sum(row[-1] == eid for row in frame), 11)
        self.assertEqual(sum(row[1].startswith("exit_contact_") for row in samples), 12)

    def test_changed_thickness_is_derived_and_off_lattice_aperture_fails(self) -> None:
        contract = load_contract(Path(__file__).resolve().parents[2]/"config/simion_candidate_two_zone.json")
        contract["accelerator"]["stage_2_rings"]["thickness_z_mm"] = 1.6
        rows = build_samples(contract)
        for eid in range(3, 10):
            self.assertEqual(sum(row[0] == "sample" and row[1].startswith(f"id{eid}_frame_x_")
                                 and row[-1] == eid for row in rows), 17)
        contract["accelerator"]["aperture_width_x_mm"] = 25.1
        with self.assertRaisesRegex(CandidateContractError, "off PA lattice"):
            build_samples(contract)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromTestCase(AcceleratorGeometrySamplesTest))
        return 0 if result.wasSuccessful() else 1
    if not args.contract or not args.output:
        parser.error("--contract and --output are required")
    rows = build_samples(load_contract(args.contract))
    with args.output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("kind", "label", "x", "y", "z", "expected_id"))
        writer.writerows(rows)
    print(f"NATIVE_GEOMETRY_SAMPLES={len(rows)-4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

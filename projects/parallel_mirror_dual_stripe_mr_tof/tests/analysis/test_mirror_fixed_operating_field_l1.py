from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_fixed_operating_field_l1 import (
    CSV_COLUMNS,
    REGION_ORDER,
    analyze_operating_field_l1,
    load_operating_field_csv,
    write_sampler_spec,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.mirror_real_field_l1_screen import (
    RealFieldL1Error,
)


PROJECT = Path(__file__).resolve().parents[2]


def _write_slice(path: Path, *, duplicate: bool = False) -> None:
    columns = sorted(CSV_COLUMNS)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for iz, region in enumerate(REGION_ORDER):
            mesh = 0.25 if "mirror" in region and "bridge" not in region else 0.5
            for x_mm in (-0.25, 0.0, 0.25):
                row = {
                    "region_id": region,
                    "source_mesh_x_mm": mesh,
                    "source_mesh_y_mm": mesh,
                    "source_mesh_z_mm": mesh,
                    "x_mm": x_mm,
                    "z_mm": float(iz),
                    "is_electrode": int(x_mm == 0.25 and iz == 0),
                    "potential_v": iz + x_mm,
                    "ex_v_per_mm": 1.0,
                    "ey_v_per_mm": 0.0,
                    "ez_v_per_mm": -1.0,
                }
                writer.writerow(row)
                if duplicate and iz == 0 and x_mm == -0.25:
                    writer.writerow(row)


class MirrorFixedOperatingFieldL1Tests(unittest.TestCase):
    def test_spec_writer_preserves_five_local_origins_and_meshes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regions = []
            for index, region in enumerate(REGION_ORDER):
                suffix = ".pa0" if index in {0, 4} else ".pa"
                pa = root / f"{region}{suffix}"
                pa.write_bytes(b"fixture")
                mesh = 0.25 if index in {0, 4} else 0.5
                regions.append({
                    "region_id": region,
                    "standalone_pa_path": str(pa),
                    "region_origin_project_mm": [-1.0, 2.0, float(index)],
                    "mesh_mm_per_gu": [mesh, mesh, mesh],
                    "z_range_mm": [float(index), float(index)],
                })
            plan = {
                "schema_version": 1,
                "role": "mrtof_fixed_operating_field_slice",
                "project_frame": "project_xyz",
                "slice_y_mm": 280.0,
                "sample_step_mm": 0.25,
                "x_range_mm": [-0.25, 0.25],
                "regions": regions,
            }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            output = root / "spec.lua"
            write_sampler_spec(plan_path=plan_path, output_path=output)
            text = output.read_text(encoding="utf-8")
        self.assertEqual(text.count("standalone_pa_path="), 5)
        self.assertEqual(text.count("mesh_mm_per_gu="), 5)
        self.assertLess(text.index(REGION_ORDER[0]), text.index(REGION_ORDER[-1]))
        self.assertIn("slice_y_mm=280", text)

    def test_loader_stitches_mixed_mesh_regions_with_one_mask(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slice.csv"
            _write_slice(path)
            loaded = load_operating_field_csv(path, probe_y_mm=280.0)
        self.assertEqual(loaded.basis.electrode_mask.shape, (3, 5))
        self.assertTrue(loaded.basis.electrode_mask[2, 0])
        self.assertEqual(loaded.mesh_by_region_mm_per_gu[REGION_ORDER[0]], (0.25, 0.25, 0.25))
        self.assertEqual(loaded.mesh_by_region_mm_per_gu[REGION_ORDER[2]], (0.5, 0.5, 0.5))
        potential, field = loaded.combined_field().sample(0.0, 2.0, reject_electrode=True)
        self.assertEqual(potential, 2.0)
        self.assertEqual(field.tolist(), [1.0, 0.0, -1.0])

    def test_loader_rejects_duplicate_geometry_sample(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slice.csv"
            _write_slice(path, duplicate=True)
            with self.assertRaisesRegex(RealFieldL1Error, "duplicate"):
                load_operating_field_csv(path, probe_y_mm=280.0)

    def test_analysis_reuses_l1_probe_and_reports_convergence_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "slice.csv"
            _write_slice(path)
            loaded = load_operating_field_csv(path, probe_y_mm=280.0)

        def fake_probe(_field, **kwargs):
            scale = kwargs["position_probe_mm"]
            return {
                "stable": True,
                "gamma_degrees": 90.0 + scale,
                "Tbar_xx_us_per_mm2": 2.0 + scale,
                "stability_margin": 0.5,
                "launch_direction_z": kwargs["launch_direction"],
            }

        with patch(
            "projects.parallel_mirror_dual_stripe_mr_tof.analysis."
            "mirror_fixed_operating_field_l1.l1_probe_at_energy",
            side_effect=fake_probe,
        ) as probe:
            result = analyze_operating_field_l1(
                loaded,
                energy_points_v=(3900.0, 4000.0, 4100.0),
                probe_scale_factors=(0.5, 1.0, 2.0),
                position_probe_mm=0.004,
                angle_probe_rad=4e-5,
                trace_controls={},
                target_gamma_degrees=90.0,
                maximum_gamma_target_residual_degrees=0.01,
                maximum_adjacent_gamma_change_degrees=0.001,
                maximum_adjacent_relative_tbar_change=0.01,
                tbar_relative_change_absolute_floor_us_per_mm2=1e-9,
                minimum_stability_margin=0.1,
            )
        self.assertEqual(probe.call_count, 10)
        self.assertEqual(result["probe_parallelism"]["actual_workers"], 1)
        self.assertEqual(result["probe_parallelism"]["job_count"], 10)
        self.assertEqual(result["status"], "screen_fail_diagnostic_only")
        self.assertIn("gamma_probe_not_converged:direction=-1", result["hard_gate_failures"])
        self.assertIn("directions", result)
        self.assertIn("Tbar_xx_us_per_mm2", result["directions"]["1"]["4000"]["scales"][-1])

    def test_lua_sampler_is_read_only_and_declares_origin_mesh_stitching(self) -> None:
        source = (PROJECT / "simion" / "sample_fixed_operating_field_slice.lua").read_text(
            encoding="utf-8"
        )
        self.assertIn("region_origin_project_mm", source)
        self.assertIn("mesh_mm_per_gu", source)
        self.assertIn("conservative_electrode_mask", source)
        self.assertIn("simion.pas:open", source)
        self.assertNotIn(":save", source)
        self.assertNotIn("fast_adjust", source.lower())
        self.assertNotIn("refine", source.lower().replace("never saves, adjusts, or refines", ""))


if __name__ == "__main__":
    unittest.main()

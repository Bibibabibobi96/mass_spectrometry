from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from projects.single_reflection_oa_tof_mass_analyzer.analysis import sync_geometry_contract

from projects.single_reflection_oa_tof_mass_analyzer.analysis.sync_geometry_contract import (
    PROJECT_ROOT,
    frozen_fly2_seed,
    load_contract,
    render_authority_document,
    render_fly2,
    render_optimization_envelope,
    render_resolved_lua,
)
from common.contracts.machine_contracts import sha256
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import (
    BASELINE_PATH,
    MODE_PATH,
    NUMERICS_PATH,
    derive_simion_geometry,
    resolve_contract,
    resolve_contract_documents,
    serialized,
)


class SyncGeometryContractTests(unittest.TestCase):
    def test_document_resolution_preserves_path_serialization_and_inputs(self) -> None:
        documents = [json.loads(path.read_text(encoding="utf-8"))
                     for path in (BASELINE_PATH, MODE_PATH, NUMERICS_PATH)]
        before = json.dumps(documents)
        original = resolve_contract()
        resolved = resolve_contract_documents(*documents, input_identity=original["inputs"])
        self.assertEqual(serialized(resolved), serialized(original))
        self.assertEqual(json.dumps(documents), before)
        self.assertIsNot(resolved["inputs"], original["inputs"])

    def test_document_resolution_rejects_the_same_invalid_numerics(self) -> None:
        baseline, mode, numerics = [json.loads(path.read_text(encoding="utf-8"))
                                   for path in (BASELINE_PATH, MODE_PATH, NUMERICS_PATH)]
        for value in (None, "unknown", ["free"]):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                numerics["comsol"]["solver_steps"] = value
                path = Path(directory) / "numerics.json"
                path.write_text(json.dumps(numerics), encoding="utf-8")
                with self.assertRaises(ValueError) as from_path:
                    resolve_contract(numerics_path=path)
                with self.assertRaises(ValueError) as from_documents:
                    resolve_contract_documents(baseline, mode, numerics, input_identity={})
                self.assertEqual(str(from_path.exception), str(from_documents.exception))

    def test_baseline_derived_geometry_matches_published_contract(self) -> None:
        self.assertEqual(resolve_contract()["derived"], load_contract()["derived"])

    def test_detector_half_cells_match_native_rounding_without_moving_geometry(self) -> None:
        resolved = resolve_contract()
        build = resolved["simion_geometry_build"]
        build["detector"]["margin_xy_mm"] = 1
        marker = resolved["simion_detector_marker"]
        marker.update(active_radius_mm=4.125, cell_xy_mm=.5, cell_z_mm=.25,
            absorber_thickness_mm=1.25, front_margin_z_mm=2.5, back_margin_z_mm=1.375)
        derived = derive_simion_geometry(
            geometry=resolved["geometry_mm"], coordinate=resolved["coordinate_convention"],
            build=build, marker=marker, source=resolved["particle_source"])
        detector = derived["simion_instances"][3]
        # Both spans are 20.5 cells: native Lua rounds up, not ties-to-even.
        self.assertEqual((detector["nx"], detector["ny"], detector["nz"]), (22, 22, 22))
        self.assertEqual(detector["x_mm"], resolved["coordinate_convention"]["detector_x"] - 5.125)
        self.assertEqual(detector["y_mm"], -5.125)
        self.assertEqual(detector["z_mm"], marker["active_plane_z_mm"] - 2.625)

    def test_final_geometry_controls_internal_placements_dimensions_and_samples(self) -> None:
        derived = derive_simion_geometry(
            geometry=dict(accelerator_bore_half=10, accelerator_ring_width=2,
                accelerator_insulation_gap=3, accelerator_shield_wall=1,
                accelerator_repeller_thickness=2, accelerator_rear_clearance=3,
                L_accel=100, accelerator_front_vacuum_margin=4,
                accelerator_repeller_z=8, accelerator_grid1_z=15, accelerator_grid2_z=100,
                shield_outer_z_min=-10, L_flight=300, flight_tube_r=20,
                flight_tube_wall=2, L_reflectron=40, ring_thickness=2,
                shield_axial_gap=3, shield_endcap_thickness=1, L_stage1=10, L_stage2=30),
            coordinate=dict(reflectron_axis=[7, -9], accelerator_axis_x=50, detector_x=-60),
            build=dict(accelerator=dict(cell_xy_mm=2, cell_z_mm=.5),
                flight_tube=dict(cell_axial_mm=1, cell_radial_mm=2),
                reflectron=dict(cell_axial_mm=1, cell_radial_mm=2),
                detector=dict(margin_xy_mm=1)),
            marker=dict(active_radius_mm=4, active_plane_z_mm=5,
                back_margin_z_mm=.25, absorber_thickness_mm=.25,
                front_margin_z_mm=.5, cell_xy_mm=.5, cell_z_mm=.25),
            source=dict(center_z_mm=12),
        )
        instances = derived["simion_instances"]
        self.assertEqual([(r["x_mm"], r["y_mm"], r["z_mm"], r["az_deg"])
            for r in instances], [(7, -9, -10, -90.), (7, -9, 300, -90.),
                (34, -16, 2, 0.), (-65, -5, 4.5, 0.)])
        self.assertEqual([(r["nx"], r["ny"], r["nz"]) for r in instances],
            [(311, 12, 1), (47, 12, 1), (17, 17, 221), (21, 21, 5)])
        self.assertEqual(derived["field_sample_points_mm"], dict(
            source_center=[50, 0., 12], accelerator_mid=[50, 0., 57.5],
            accelerator_exit=[50, 0., 99.5], drift_mid=[7, -9, 152.5],
            reflectron_stage1=[7, -9, 305], reflectron_stage2=[7, -9, 325]))

    def test_resolved_runtime_preserves_the_author_time_step_policy(self) -> None:
        numerics = json.loads(NUMERICS_PATH.read_text(encoding="utf-8"))
        numerics["comsol"]["solver_steps"] = "strict"
        numerics["comsol"]["times_to_store"] = "tlist"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "numerics.json"
            path.write_text(json.dumps(numerics), encoding="utf-8")
            actual = resolve_contract(numerics_path=path)["comsol_runtime"]
        self.assertEqual(actual["solver_steps"], "strict")
        self.assertEqual(actual["times_to_store"], "tlist")

    def test_invalid_or_missing_time_step_policy_is_rejected_before_resolution(self) -> None:
        for field, value in (
            ("solver_steps", None), ("solver_steps", "unknown"),
            ("solver_steps", "manual"), ("solver_steps", ["free"]),
            ("times_to_store", None), ("times_to_store", "unknown"),
            ("times_to_store", "tsteps"), ("times_to_store", "tstepsclosest"),
        ):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                numerics = json.loads(NUMERICS_PATH.read_text(encoding="utf-8"))
                if value is None:
                    del numerics["comsol"][field]
                else:
                    numerics["comsol"][field] = value
                path = Path(directory) / "numerics.json"
                path.write_text(json.dumps(numerics), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, field):
                    resolve_contract(numerics_path=path)

    def test_grid_policy_names_the_official_zero_width_one_row_model(self) -> None:
        contract = load_contract()
        expected = (
            "zero-grid-unit-thick one-row full-aperture 100%-transmission "
            "ideal electrode sheet"
        )
        self.assertEqual(contract["grid_policy"]["baseline"], expected)
        self.assertIn(f'baseline="{expected}"', render_resolved_lua(contract))

    def test_fly2_seed_remains_a_run_instance_binding(self) -> None:
        contract = load_contract()
        self.assertNotIn("seed", contract["particle_source"])

        rendered = render_fly2(contract, particle_source_seed=20260729)

        self.assertIn("seed(20260729)", rendered)
        self.assertNotIn("seed", contract["particle_source"])

    def test_fly2_rendering_rejects_an_implicit_or_noninteger_seed(self) -> None:
        contract = load_contract()
        for invalid in (None, "20260729", True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "explicit integer"):
                    render_fly2(contract, particle_source_seed=invalid)

    def test_freshness_reads_one_existing_frozen_seed_without_deriving_it_from_physics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fly2 = Path(directory) / "source.fly2"
            fly2.write_text("seed(20260713)\n", encoding="utf-8")
            self.assertEqual(frozen_fly2_seed(fly2), 20260713)

            fly2.write_text("seed(1)\nseed(2)\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                frozen_fly2_seed(fly2)

    def test_campaign_authorities_are_compiled_by_the_same_sync_chain(self) -> None:
        campaign = PROJECT_ROOT / "config" / "experiment_campaign.json"
        envelope_source = render_optimization_envelope()
        rendered = json.loads(render_authority_document(campaign, envelope_source))
        self.assertEqual(
            rendered["authorities"]["baseline"]["sha256"],
            sha256(PROJECT_ROOT / "config" / "baseline.json"),
        )
        self.assertEqual(
            rendered["authorities"]["solver_numerics"]["sha256"],
            sha256(PROJECT_ROOT / "config" / "formal_solver_numerics.json"),
        )
        self.assertEqual(
            rendered["authorities"]["optimization_envelope"]["sha256"],
            sha256(PROJECT_ROOT / "config" / "optimization_envelope.json"),
        )
        self.assertEqual(
            rendered["authorities"]["candidate_runtime"]["sha256"],
            sha256(PROJECT_ROOT / "config" / "candidate_runtime.json"),
        )

    def test_runtime_authority_drift_is_detected_and_only_its_binding_is_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            campaign = root / "config" / "experiment_campaign.json"
            runtime = root / "config" / "candidate_runtime.json"
            campaign.write_bytes((PROJECT_ROOT / "config" / campaign.name).read_bytes())
            runtime.write_bytes((PROJECT_ROOT / "config" / runtime.name).read_bytes())
            envelope = render_optimization_envelope()
            with patch.object(sync_geometry_contract, "PROJECT_ROOT", root):
                sync_geometry_contract.update(campaign, render_authority_document(campaign, envelope), True)
                before = campaign.read_bytes()
                runtime.write_bytes(runtime.read_bytes() + b"\n")
                rendered = render_authority_document(campaign, envelope)
                with self.assertRaisesRegex(SystemExit, "STALE=config[/\\\\]experiment_campaign.json"):
                    sync_geometry_contract.update(campaign, rendered, False)
                self.assertEqual(campaign.read_bytes(), before)
                sync_geometry_contract.update(campaign, rendered, True)
                expected = json.loads(before)
                expected["authorities"]["candidate_runtime"]["sha256"] = sha256(runtime)
                self.assertEqual(json.loads(campaign.read_text()), expected)
                self.assertFalse(sync_geometry_contract.update(campaign, rendered, False))


if __name__ == "__main__":
    unittest.main()

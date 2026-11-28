from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.io.file_identity import file_sha256
from msplatform.backends.simion.pa_family_cache import canonical_pa_family_cache_key
from msplatform.backends.simion import standalone_pa_response_set
from msplatform.backends.simion.oa_focus_plan import derive
from msplatform.backends.simion.oa_focus_identity import expected_files, identity
from msplatform.components.orthogonal_accelerator.two_zone_geometry import load_geometry_profile


class ComponentFocusPAPlanTests(unittest.TestCase):
    def test_focus_is_inside_domain_and_closed_end_is_padded(self) -> None:
        root = Path(__file__).resolve().parents[4] / "src/msplatform/components/orthogonal_accelerator"
        campaign = root / "config/two_zone_component_focus_campaign.json"
        plan = derive(campaign, geometry_profile=load_geometry_profile(json.loads(campaign.read_text(encoding="utf-8"))["geometry_profile_id"]), mesh_mm_per_gu=[0.25, 0.25, 0.1])
        domain = plan["numerical_domain"]
        layout = plan["layout"]
        self.assertAlmostEqual(domain["focus_plane_local_z_mm"], domain["focus_plane_padding_mm"])
        self.assertGreater(domain["focus_plane_local_z_mm"], 0.0)
        self.assertGreaterEqual(domain["span_mm"][2], layout["local_exit_z_mm"] + layout["static_axial_length_mm"] + domain["positive_z_enclosure_padding_mm"])
        self.assertIn("Solid repeller; no coaxial return aperture", plan["gem"])
        self.assertEqual(plan["cache_policy"], "one_native_fast_adjust_family__manifest_bound_standalone_runtime_responses")
        self.assertEqual(plan["electrode_count"], 19)
        self.assertEqual(plan["geometry_profile_id"], "closed_two_zone_compact_mr_axial_r3_gap1_4mm")
        self.assertEqual(plan["layout"]["gap_1_mm"], 4.0)
        self.assertEqual(plan["layout"]["gap_2_mm"], 30.0)
        self.assertEqual(plan["layout"]["aperture_height_y_mm"], 26.0)
        self.assertEqual(plan["layout"]["static_minimum_y_extent_mm"], 34.0)
        self.assertEqual(domain["span_mm"], [44.5, 34.5, 50.0])
        self.assertEqual(domain["stored_span_mm"], [22.25, 34.5, 50.0])
        self.assertEqual(domain["mirror_axes"], ["x"])
        self.assertEqual(domain["iob_origin_mm"], [0.0, -17.25, 0.0])
        self.assertIn("pa_define($(nx),$(ny),$(nz),planar,x,electrostatic", plan["gem"])
        self.assertIn("locate(0,$(y_span/2),0)", plan["gem"])
        self.assertIn("local nx = math.floor(stored_x_span/mmgu_x + 0.5) + 1", plan["gem"])
        self.assertEqual(plan["layout"]["static_axial_length_mm"], 38.0)
        self.assertEqual(plan["theory_seed"]["source_center_exit_mm"], 32.0)
        self.assertAlmostEqual(plan["theory_seed"]["nominal_energy_per_charge_v"], 4371.2351565, places=7)
        self.assertAlmostEqual(plan["theory_seed"]["first_order_focus_drift_mm"], 0.0, places=7)

    def test_identity_includes_dynamic_standalone_response_bank(self) -> None:
        root = Path(__file__).resolve().parents[4] / "src/msplatform/components/orthogonal_accelerator"
        campaign = root / "config/two_zone_component_focus_campaign.json"
        plan = derive(campaign, geometry_profile=load_geometry_profile(json.loads(campaign.read_text(encoding="utf-8"))["geometry_profile_id"]), mesh_mm_per_gu=[0.25, 0.25, 0.1])
        builder = root.parents[3] / "src/msplatform/backends/simion/resources/build_component_focus_pa.lua"
        executable = Path(__file__)
        value = identity(plan, builder, executable)
        contract = Path(standalone_pa_response_set.__file__).resolve()
        self.assertEqual(value["builder_identity"]["response_set_contract_sha256"], file_sha256(contract))

        def changed_contract(path):
            return "A" * 64 if Path(path) == contract else file_sha256(path)

        with patch("msplatform.backends.simion.oa_focus_identity.file_sha256", side_effect=changed_contract):
            changed = identity(plan, builder, executable)
        self.assertNotEqual(value["builder_identity"]["response_set_contract_sha256"], changed["builder_identity"]["response_set_contract_sha256"])
        self.assertNotEqual(canonical_pa_family_cache_key(value), canonical_pa_family_cache_key(changed))
        self.assertEqual(expected_files(plan), tuple(sorted((
            "orthogonal_accelerator_focus.pa#",
            *(f"orthogonal_accelerator_focus.pa{index}" for index in range(20)),
            *(f"orthogonal_accelerator_focus.response{index}.pa" for index in range(1, 20)),
            "orthogonal_accelerator_focus.standalone_responses.json",
        ))))
        self.assertEqual(value["refine_policy"]["response_bank"], "new_pa_object_standalone_responses_1_through_electrode_count")
        self.assertEqual(value["basis_namespace"]["native_solution_ids"], list(range(20)))
        self.assertEqual(value["basis_namespace"]["electrode_ids"], list(range(1, 20)))
        self.assertEqual(value["basis_namespace"]["runtime"], "manifest_bound_standalone_responses__private_native_fast_adjust_family")
        self.assertEqual(value["grid_phase"]["stored_span_mm"], [22.25, 34.5, 50.0])
        self.assertEqual(value["grid_phase"]["pa_span_mm"], [44.5, 34.5, 50.0])
        self.assertEqual(value["grid_phase"]["mirror_axes"], ["x"])

    def test_builder_preserves_adjustable_electrode_flags_and_uses_official_solution_pattern(self) -> None:
        root = Path(__file__).resolve().parents[4] / "src/msplatform/components/orthogonal_accelerator"
        builder = (root.parents[3] / "src/msplatform/backends/simion/resources/build_component_focus_pa.lua").read_text(encoding="utf-8")
        self.assertNotIn(":potential(", builder)
        self.assertIn("family:refine{solutions={0}}", builder)
        self.assertIn("family:load(output)", builder)
        self.assertIn("for solution=1,electrode_count do", builder)
        self.assertIn("family:refine{solutions=solutions}", builder)
        self.assertIn("for solution=0,electrode_count do", builder)

    def test_store_controller_owns_native_verification_and_runtime_claims(self) -> None:
        root = Path(__file__).resolve().parents[4]
        controller = (root / "src/msplatform/backends/simion/oa_focus_controller_store.py").read_text(encoding="utf-8")
        workflow = (root / "src/msplatform/workflows/oa_focus_controller.py").read_text(encoding="utf-8")
        self.assertIn("session.run_process", controller)
        self.assertIn("put_asset_claimed", controller)
        self.assertIn("claim_token", controller)
        self.assertIn("focus_manifest.json", controller)
        self.assertIn("materialize_focus_runtime", workflow)
        self.assertIn("runtime_checkpoint_path", workflow)
        self.assertNotIn("Enter-ArtifactWorkflowCapacitySession", workflow)
        self.assertNotIn("New-RunPackage", workflow)


class ExplicitFocusMeshTests(unittest.TestCase):
    def test_explicit_mesh_rejects_missing_invalid_and_changes_actual_grid(self):
        root = Path(__file__).resolve().parents[4] / "src/msplatform/components/orthogonal_accelerator"
        campaign = root / "config/two_zone_component_focus_campaign.json"
        profile = load_geometry_profile(json.loads(campaign.read_text(encoding="utf-8"))["geometry_profile_id"])
        with self.assertRaises(TypeError):
            derive(campaign, geometry_profile=profile)
        for mesh in (None, [], [1, 1], [1, 1, 1, 1], [True, .25, .1], [0, .25, .1], [-1, .25, .1], [float("nan"), .25, .1], [float("inf"), .25, .1]):
            with self.subTest(mesh=mesh), self.assertRaises(ValueError):
                derive(campaign, geometry_profile=profile, mesh_mm_per_gu=mesh)
        plan = derive(campaign, geometry_profile=profile, mesh_mm_per_gu=[.2, .5, .2])
        self.assertEqual(plan["numerical_domain"]["mesh_mm_per_gu"], [.2, .5, .2])
        self.assertEqual(plan["requirements"]["local_pa"]["mesh_mm_per_gu"], [.2, .5, .2])
        self.assertIn("contract_mmgu_x, contract_mmgu_y, contract_mmgu_z = 0.2, 0.5, 0.2", plan["gem"])
        self.assertEqual(plan["numerical_domain"]["mirror_axes"], ["x"])
        self.assertEqual(plan["electrode_count"], 19)


if __name__ == "__main__":
    unittest.main()

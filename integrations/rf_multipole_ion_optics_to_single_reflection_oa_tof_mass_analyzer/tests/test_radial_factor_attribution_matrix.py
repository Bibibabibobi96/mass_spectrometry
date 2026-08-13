import json
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.analysis.radial_factor_matrix import (
    validate_radial_factor_matrix,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "radial_factor_attribution_matrix.json"


class RadialFactorAttributionMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(CONFIG.read_text(encoding="utf-8"))
        cls.profiles = {row["id"]: row for row in cls.doc["design_profiles"]}

    def test_contract_is_versioned_non_executable_and_reuses_existing_cli(self):
        validate_radial_factor_matrix(self.doc)
        self.assertEqual(self.doc["schema_version"], 1)
        self.assertEqual(self.doc["status"], "planning_only_until_adapter_support")
        self.assertFalse(self.doc["execution_authorized"])
        self.assertEqual(
            self.doc["existing_execution_entry"],
            "projects/single_reflection_oa_tof_mass_analyzer/workflows/radial_compaction/run_campaign.py",
        )

    def test_source_clock_cohort_voltage_frontend_and_factor_mesh_are_frozen(self):
        frozen = self.doc["frozen_context"]
        self.assertEqual(frozen["resolution_time_basis"], "detector_time_minus_pulse_effective_time")
        self.assertEqual(frozen["population_basis"], "all_pulse_eligible_particles")
        self.assertTrue(frozen["same_ordered_particle_ids_required"])
        for key in ("source_run_id", "source_manifest_sha256", "source_state_sha256",
                    "particle_source_sha256", "frontend_grid_profile_id",
                    "accelerator_field_profile_id", "voltage_policy"):
            self.assertTrue(frozen[key])
        self.assertEqual({p["reflectron_axial_cell_mm"] for p in self.profiles.values()}, {0.1})

    def test_shield_only_changes_only_shield_radius(self):
        rows = [self.profiles[i] for i in self.doc["contrasts"]["shield_only"]]
        self.assertEqual([r["shield_inner_r_mm"] for r in rows], [100, 180, 350])
        keys = set(rows[0]) - {"id", "shield_inner_r_mm"}
        self.assertTrue(all({k: r[k] for k in keys} == {k: rows[0][k] for k in keys} for r in rows))

    def test_bundle_and_topology_contrasts_are_exact(self):
        a, b = [self.profiles[i] for i in self.doc["contrasts"]["radial_electrode_bundle"]]
        changed = {k for k in a if k != "id" and a[k] != b[k]}
        self.assertEqual(changed, {"bore_r_mm", "ring_outer_r_mm"})
        self.assertEqual([(a["bore_r_mm"], a["ring_outer_r_mm"]),
                          (b["bore_r_mm"], b["ring_outer_r_mm"])], [(35, 70), (250, 300)])
        rows = [self.profiles[i] for i in self.doc["contrasts"]["r100_topology_sequence"]]
        self.assertEqual([(r["stage1_rings"], r["stage2_rings"], r["ring_thickness_mm"])
                          for r in rows], [(10, 5, 5), (8, 15, 5), (8, 15, 2)])
        self.assertEqual({(r["bore_r_mm"], r["ring_outer_r_mm"], r["shield_inner_r_mm"])
                          for r in rows}, {(35, 70, 100)})

    def test_large_anchor_grid_convergence_and_promotion_are_locked(self):
        anchor = self.profiles[self.doc["contrasts"]["large_anchor"]]
        self.assertEqual((anchor["bore_r_mm"], anchor["ring_outer_r_mm"],
                          anchor["shield_inner_r_mm"]), (250, 300, 350))
        self.assertEqual(self.doc["grid_convergence"]["reflectron_axial_cell_mm"], [0.2, 0.1, 0.05])
        promotion = self.doc["promotion"]
        self.assertEqual((promotion["screening_count"], promotion["qualification_count"]), (100, 1000))
        self.assertFalse(promotion["n100_is_ranking_authority"])
        self.assertTrue(promotion["promotion_requires_all_contrast_arms_complete"])


if __name__ == "__main__":
    unittest.main()

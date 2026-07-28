from __future__ import annotations

import json
import hashlib
import unittest
from pathlib import Path
from typing import Any

from common.multipole.runtime_profile import resolve_runtime_profile
from common.multipole.design_profile import resolve_design_profile
from common.contracts.particle_count_policy import validate_prefix_particle_sources


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
    "exit_aperture_plate_acceleration",
)
N100_TIER_SUFFIXES = (
    "",
    "_n100_spatial_refined",
    "_n100_temporal_refined",
)
COMPATIBILITY_RUNTIME_IDS = {
    "baseline_finite_3d",
    "exit_aperture_plate_acceleration_reference",
}


def load(relative: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


class ThreeModeRuntimeAndQualificationTests(unittest.TestCase):
    def test_family_runtime_profiles_resolve_without_free_numerics(self) -> None:
        registry = load("config/runtime_profiles.json")
        expected_ids = {
            f"{mode_id}{suffix}"
            for mode_id in MODE_IDS
            for suffix in N100_TIER_SUFFIXES
        }
        expected_ids |= {f"{mode_id}_n1000" for mode_id in MODE_IDS}
        expected_ids |= COMPATIBILITY_RUNTIME_IDS
        self.assertEqual(set(registry["profiles"]), expected_ids)
        source_identities = set()
        for runtime_id in sorted(expected_ids):
            resolved = resolve_runtime_profile(
                REPO_ROOT,
                "rf_octupole_ion_optics",
                runtime_id,
            )
            source_identities.add(
                (
                    resolved["particle_source"]["path"],
                    resolved["particle_source"]["sha256"],
                )
            )
        self.assertEqual(
            source_identities,
            {
                (
                    str(
                        REPO_ROOT
                        / "common/multipole/sources/"
                        "rf_multipole_family_mother_sample_v1_100.csv"
                    ),
                    "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
                ),
                (
                    str(
                        REPO_ROOT
                        / "common/multipole/sources/"
                        "rf_multipole_family_mother_sample_v1_1000.csv"
                    ),
                    "CE68A6B47DC5726D9C45CBE28E4397A2321D782FAED265067824891AAF4D0FBF",
                ),
            },
        )

    def test_three_tiers_isolate_spatial_then_time_refinement(self) -> None:
        comsol = load("config/comsol_solver_numerics.json")["profiles"]
        simion = load("config/simion_solver_numerics.json")["profiles"]
        self.assertEqual(
            (
                comsol["baseline_finite_3d"]["mesh"][
                    "working_region_maximum_element_size_mm"
                ],
                comsol["n100_spatial_refined"]["mesh"][
                    "working_region_maximum_element_size_mm"
                ],
                comsol["baseline_finite_3d"]["trajectory"]["rf_steps_per_period"],
                comsol["n100_temporal_refined"]["trajectory"][
                    "rf_steps_per_period"
                ],
            ),
            (0.5, 0.35, 80, 160),
        )
        self.assertEqual(
            (
                simion["baseline_finite_3d"]["cell_mm"],
                simion["n100_spatial_refined"]["cell_mm"],
                simion["baseline_finite_3d"]["trajectory"]["rf_steps_per_period"],
                simion["n100_temporal_refined"]["trajectory"][
                    "rf_steps_per_period"
                ],
            ),
            (0.4, 0.3, 40, 80),
        )
        self.assertEqual(
            comsol["n100_spatial_refined"]["mesh"],
            comsol["n100_temporal_refined"]["mesh"],
        )
        self.assertEqual(
            simion["n100_spatial_refined"]["cell_mm"],
            simion["n100_temporal_refined"]["cell_mm"],
        )

    def test_family_n100_is_the_exact_registered_n1000_prefix(self) -> None:
        profiles = load("config/particle_source_profiles.json")["profiles"]
        n100 = profiles["family_mother_sample_v1_n100"]
        n1000 = profiles["family_mother_sample_v1_n1000"]
        self.assertEqual(
            n100["sha256"],
            "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
        )
        self.assertEqual(
            n1000["sha256"],
            "CE68A6B47DC5726D9C45CBE28E4397A2321D782FAED265067824891AAF4D0FBF",
        )
        validate_prefix_particle_sources(
            REPO_ROOT / n100["path"],
            REPO_ROOT / n1000["path"],
            expected_n100_sha256=n100["sha256"],
            expected_n1000_sha256=n1000["sha256"],
        )

    def test_preregistration_fails_inconclusive_without_supported_thresholds(self) -> None:
        plan = load("config/qualification/n100_convergence_preregistration.json")
        acceptance = load(
            "config/qualification/dispersion_acceptance.json"
        )
        effect = load(
            "config/qualification/dispersion_effect_resolution.json"
        )
        budget = load("config/qualification/engineering_budget.json")
        for document in (plan, acceptance, effect, budget):
            self.assertTrue(document["preregistered_before_run"])
            self.assertEqual(document["project_id"], "rf_octupole_ion_optics")
        self.assertEqual(
            plan["decision_policy"]["without_supported_acceptance_budget"],
            "INCONCLUSIVE",
        )
        self.assertEqual(
            acceptance["acceptance_criteria"]["status"],
            "not_established",
        )
        self.assertEqual(
            effect["effect_resolution"]["status"],
            "not_established",
        )
        self.assertEqual(
            budget["budget_exhaustion_result"],
            "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED",
        )
        self.assertTrue(budget["pilot_authorization"]["authorized"])
        self.assertEqual(
            budget["pilot_authorization"]["scope"]["runtime_profile_id"],
            "segmented_rod_axial_acceleration_n100_spatial_refined",
        )
        result = load(
            "config/qualification/n100_no_acceleration_qualification.json"
        )
        self.assertEqual(result["functional_transport"]["status"], "PASS")
        self.assertEqual(
            result["continuous_diagnostics"]["status"],
            "INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET",
        )

    def test_geometry_and_voltage_contracts_match_typed_resolved_modes(self) -> None:
        invariant_path = (
            PROJECT_ROOT
            / "config/qualification/three_mode_geometry_invariant.json"
        )
        invariant = json.loads(invariant_path.read_text(encoding="utf-8"))
        invariant_sha256 = hashlib.sha256(invariant_path.read_bytes()).hexdigest().upper()
        mechanical = invariant["mechanical_baseline"]
        expected_voltages = {
            "no_acceleration_full_length": [0.0, 0.0, 0.0, 0.0],
            "segmented_rod_axial_acceleration": [0.0, -1.0, -2.0, -3.0],
            "exit_aperture_plate_acceleration": [0.0, 0.0, 0.0, 0.0],
        }
        for mode_id, expected in expected_voltages.items():
            resolved = resolve_design_profile(
                REPO_ROOT,
                "rf_octupole_ion_optics",
                mode_id,
            )["resolved_design"]
            voltage = load(f"config/qualification/voltage_{mode_id}.json")
            self.assertEqual(
                voltage["geometry_invariant_sha256"],
                invariant_sha256,
            )
            self.assertEqual(voltage["rod_segment_common_mode_V"], expected)
            self.assertEqual(
                [
                    item["common_mode_V"]
                    for item in resolved["segmentation"]["axial_acceleration"][
                        "derived"
                    ]["segments"]
                ],
                expected,
            )
            self.assertEqual(
                resolved["interfaces_mm"]["entrance"]["release_plane_z_mm"],
                mechanical["release_plane_z_mm"],
            )
            self.assertEqual(
                resolved["interfaces_mm"]["exit"]["handoff_plane_z_mm"],
                mechanical["handoff_plane_z_mm"],
            )
            self.assertEqual(
                resolved["interfaces_mm"]["exit"]["census_plane_z_mm"],
                mechanical["near_interface_census_plane_z_mm"],
            )

    def test_dispersion_preregistration_references_are_fresh(self) -> None:
        preregistration = load(
            "config/qualification/three_mode_dispersion_preregistration.json"
        )
        self.assertEqual(
            preregistration["formal_binding_status"],
            "pending_real_solver_outputs",
        )
        references = [
            preregistration["geometry"],
            preregistration["source_family"]["n100"],
            preregistration["source_family"]["n1000"],
            *[
                item["voltage_contract"]
                for item in preregistration["modes"]
            ],
            *preregistration["qualification_bindings"].values(),
        ]
        for reference in references:
            path = REPO_ROOT / reference["path"]
            self.assertEqual(
                hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                reference["sha256"],
            )
        self.assertEqual(
            preregistration["formal_binding_generation"][
                "missing_real_handoff_decision"
            ],
            "FAIL_CLOSED_NO_FORMAL_BINDING",
        )

    def test_compatibility_aliases_resolve_the_same_typed_modes(self) -> None:
        aliases = {
            "baseline_finite_3d": "segmented_rod_axial_acceleration",
            "exit_aperture_plate_acceleration_reference":
                "exit_aperture_plate_acceleration",
        }
        for alias, canonical in aliases.items():
            alias_design = resolve_design_profile(
                REPO_ROOT,
                "rf_octupole_ion_optics",
                alias,
            )["resolved_design"]
            canonical_design = resolve_design_profile(
                REPO_ROOT,
                "rf_octupole_ion_optics",
                canonical,
            )["resolved_design"]
            for key in (
                "geometry_mm",
                "interfaces_mm",
                "drive",
                "static_electrodes_V",
                "segmentation",
            ):
                self.assertEqual(alias_design[key], canonical_design[key])

    def test_wrappers_expose_only_registered_runtime_profiles(self) -> None:
        runtime_ids = set(load("config/runtime_profiles.json")["profiles"])
        for name in (
            "analysis/run_finite_3d_transport.ps1",
            "analysis/run_simion_finite_3d_transport.ps1",
        ):
            source = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            for runtime_id in runtime_ids:
                self.assertIn(f"'{runtime_id}'", source)
            self.assertIn("RuntimeProfileId", source)
            self.assertNotIn("MeshAutoLevel =", source.split("$arguments = @{")[0])
            self.assertNotIn("CellMm =", source.split("$arguments = @{")[0])


if __name__ == "__main__":
    unittest.main()

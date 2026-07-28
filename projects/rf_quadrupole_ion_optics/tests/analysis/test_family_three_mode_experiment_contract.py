from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import validate_schema
from common.contracts.particle_count_policy import validate_prefix_particle_sources
from common.multipole.design_profile import resolve_design_profile
from common.multipole.particle_source_preflight import validate_source


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]
CONFIG = PROJECT_ROOT / "config"
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
    "exit_aperture_plate_acceleration",
)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class FamilyThreeModeExperimentContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolved = {
            mode_id: resolve_design_profile(
                REPO_ROOT, "rf_quadrupole_ion_optics", mode_id
            )["resolved_design"]
            for mode_id in MODE_IDS
        }

    def test_three_profiles_share_one_typed_mechanical_authority(self) -> None:
        profiles = load(CONFIG / "design_profiles.json")
        modes = load(CONFIG / "operating_modes.json")
        validate_schema(profiles, "design_profiles.schema.json")
        validate_schema(modes, "multipole_operating_modes.schema.json")
        selected = {
            item["design_profile_id"]: item
            for item in profiles["profiles"]
            if item["design_profile_id"] in MODE_IDS
        }
        self.assertEqual(set(selected), set(MODE_IDS))
        for field in ("design_request", "design_variables", "optimization_envelope"):
            self.assertEqual({item[field] for item in selected.values()}, {
                {
                    "design_request": "config/requests/baseline.json",
                    "design_variables": "config/design_variables.json",
                    "optimization_envelope": "config/optimization_envelope.json",
                }[field]
            })
            self.assertEqual(
                len({item["sha256"][field] for item in selected.values()}), 1
            )
        self.assertEqual(
            [item["mode_id"] for item in modes["modes"]],
            list(MODE_IDS),
        )

    def test_geometry_source_and_rf_are_strictly_identical(self) -> None:
        reference = self.resolved[MODE_IDS[0]]
        for resolved in self.resolved.values():
            self.assertEqual(resolved["geometry_mm"], reference["geometry_mm"])
            self.assertEqual(resolved["interfaces_mm"], reference["interfaces_mm"])
            self.assertEqual(resolved["drive"], reference["drive"])
            self.assertEqual(resolved["particle_source"], reference["particle_source"])
            physical_segments = [
                {key: value for key, value in electrode.items() if key != "common_mode_V"}
                for electrode in resolved["segmentation"]["segmented_rod_array"][
                    "electrodes"
                ]
            ]
            reference_segments = [
                {key: value for key, value in electrode.items() if key != "common_mode_V"}
                for electrode in reference["segmentation"]["segmented_rod_array"][
                    "electrodes"
                ]
            ]
            self.assertEqual(physical_segments, reference_segments)
        geometry = reference["geometry_mm"]
        self.assertEqual(
            (
                geometry["inscribed_radius_r0"],
                geometry["rod_radius_ratio"],
                geometry["rod_z_min"],
                geometry["rod_z_max"],
            ),
            (4.0, 0.5, 0.0, 79.6),
        )
        self.assertEqual(
            (
                reference["interfaces_mm"]["entrance"]["release_plane_z_mm"],
                reference["interfaces_mm"]["entrance"][
                    "aperture_plate_upstream_face_z_mm"
                ],
                reference["interfaces_mm"]["entrance"][
                    "aperture_plate_downstream_face_z_mm"
                ],
                reference["interfaces_mm"]["exit"]["aperture_plate_upstream_face_z_mm"],
                reference["interfaces_mm"]["exit"]["aperture_plate_downstream_face_z_mm"],
                reference["interfaces_mm"]["exit"]["handoff_plane_z_mm"],
                reference["interfaces_mm"]["exit"]["census_plane_z_mm"],
            ),
            (-1.5, -1.0, -0.5, 80.1, 80.6, 80.6, 81.1),
        )

    def test_only_typed_electrical_assignments_differ(self) -> None:
        expected_segments = {
            MODE_IDS[0]: [0.0, 0.0, 0.0, 0.0],
            MODE_IDS[1]: [0.0, -1.0, -2.0, -3.0],
            MODE_IDS[2]: [0.0, 0.0, 0.0, 0.0],
        }
        expected_exit = {
            MODE_IDS[0]: 0.0,
            MODE_IDS[1]: -3.0,
            MODE_IDS[2]: -3.0,
        }
        expected_topology = {
            MODE_IDS[0]: "none",
            MODE_IDS[1]: "segmented_rod_axial_acceleration",
            MODE_IDS[2]: "exit_aperture_plate_potential_step",
        }
        for mode_id, resolved in self.resolved.items():
            segments = resolved["segmentation"]["axial_acceleration"]["derived"][
                "segments"
            ]
            for item in segments:
                self.assertAlmostEqual(
                    item["z_max_mm"] - item["z_min_mm"], 19.6
                )
            self.assertEqual(
                [item["common_mode_V"] for item in segments],
                expected_segments[mode_id],
            )
            self.assertEqual(resolved["axial_drive"]["topology"], expected_topology[mode_id])
            self.assertEqual(
                resolved["static_electrodes_V"][
                    "exit_outer_endcap_aperture_plate_connector_V"
                ],
                expected_exit[mode_id],
            )

    def test_family_n100_is_shared_n1000_prefix_and_preflights(self) -> None:
        source_profiles = load(CONFIG / "particle_source_profiles.json")["profiles"]
        n100 = REPO_ROOT / source_profiles["family_mother_sample_v1_n100"]["path"]
        n1000 = REPO_ROOT / source_profiles["family_mother_sample_v1_n1000"]["path"]
        validate_prefix_particle_sources(
            n100,
            n1000,
            expected_n100_sha256=source_profiles["family_mother_sample_v1_n100"][
                "sha256"
            ],
            expected_n1000_sha256=source_profiles["family_mother_sample_v1_n1000"][
                "sha256"
            ],
        )
        for resolved in self.resolved.values():
            metadata = validate_source(n100, resolved)
            self.assertEqual(metadata["particle_count"], 100)
            self.assertEqual(metadata["source_plane_z_mm"], -1.5)
        self.assertEqual(
            source_profiles["official_fixed_100"]["path"],
            "projects/rf_quadrupole_ion_optics/config/particles/"
            "official_fixed_100_canonical.csv",
        )

    def test_n100_numerical_matrix_is_preregistered_exactly(self) -> None:
        comsol = load(CONFIG / "multipole_transport_comsol_solver_numerics.json")[
            "profiles"
        ]
        simion = load(CONFIG / "multipole_transport_simion_solver_numerics.json")[
            "profiles"
        ]
        self.assertEqual(
            [
                (
                    comsol[name]["mesh"]["working_region_maximum_element_size_mm"],
                    comsol[name]["trajectory"]["rf_steps_per_period"],
                )
                for name in (
                    "baseline_finite_3d",
                    "n100_spatial_refined",
                    "n100_temporal_refined",
                )
            ],
            [(0.5, 80), (0.35, 80), (0.35, 160)],
        )
        self.assertEqual(
            [
                (
                    simion[name]["cell_mm"],
                    simion[name]["trajectory"]["rf_steps_per_period"],
                )
                for name in (
                    "baseline_finite_3d",
                    "n100_spatial_refined",
                    "n100_temporal_refined",
                )
            ],
            [(0.4, 40), (0.3, 40), (0.3, 80)],
        )
        runtime = load(CONFIG / "runtime_profiles.json")["profiles"]
        self.assertEqual(len(runtime), 12)
        for mode_id in MODE_IDS:
            self.assertIn(mode_id, runtime)
            self.assertIn(f"{mode_id}_n100_spatial_refined", runtime)
            self.assertIn(f"{mode_id}_n100_temporal_refined", runtime)
            self.assertIn(f"{mode_id}_n1000", runtime)

    def test_acceptance_effect_resolution_and_budget_fail_inconclusive(self) -> None:
        family = CONFIG / "family_experiment"
        acceptance = load(family / "dispersion_acceptance.json")
        effect = load(family / "dispersion_effect_resolution.json")
        budget = load(family / "engineering_budget.json")
        self.assertEqual(
            acceptance["acceptance_criteria"]["missing_threshold_decision"],
            "INCONCLUSIVE",
        )
        self.assertIsNone(
            acceptance["acceptance_criteria"]["minimum_transmission_fraction"]
        )
        self.assertIsNone(effect["effect_resolution"]["minimum_resolvable_effect"])
        self.assertEqual(
            effect["effect_resolution"][
                "decision_when_interval_overlaps_unresolved_region"
            ],
            "INCONCLUSIVE",
        )
        self.assertFalse(budget["pilot_authorization"]["authorized"])
        self.assertFalse(budget["full_matrix_authorization"]["authorized"])
        self.assertEqual(
            budget["budget_exhaustion_result"],
            "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED",
        )

    def test_preregistration_freezes_qualification_inputs_without_fake_outputs(
        self,
    ) -> None:
        preregistration = load(
            CONFIG / "family_experiment" / "n100_convergence_preregistration.json"
        )
        self.assertTrue(preregistration["preregistered_before_run"])
        self.assertEqual(preregistration["modes"], list(MODE_IDS))
        particle_source = preregistration["particle_source"]
        self.assertEqual(
            particle_source["sha256"], sha256(REPO_ROOT / particle_source["path"])
        )
        self.assertEqual(
            particle_source["n1000_sha256"],
            sha256(REPO_ROOT / particle_source["n1000_path"]),
        )
        design_authority = preregistration["design_authority"]
        for path_key, sha_key in (
            ("design_profiles", "design_profiles_sha256"),
            ("operating_modes", "operating_modes_sha256"),
            ("geometry_invariant", "geometry_invariant_sha256"),
        ):
            self.assertEqual(
                design_authority[sha_key],
                sha256(REPO_ROOT / design_authority[path_key]),
            )
        for solver_plan in preregistration["solver_plans"].values():
            self.assertEqual(
                solver_plan["registry_sha256"],
                sha256(REPO_ROOT / solver_plan["registry"]),
            )
        for name, reference in preregistration["qualification_bindings"].items():
            path = REPO_ROOT / reference["path"]
            self.assertEqual(reference["sha256"], sha256(path), name)
        publication = preregistration["dispersion_binding_publication"]
        self.assertEqual(
            publication["status"], "INCONCLUSIVE_PENDING_SOLVER_HANDOFF_STATES"
        )
        for relative in publication["target_bindings"]:
            self.assertFalse(
                (REPO_ROOT / relative).exists(),
                "A formal dispersion binding must not be fabricated before solver output",
            )
        budget = load(CONFIG / "family_experiment" / "engineering_budget.json")
        self.assertFalse(budget["pilot_authorization"]["authorized"])
        self.assertFalse(budget["full_matrix_authorization"]["authorized"])

    def test_no_acceleration_qualification_closes_only_functional_transport(
        self,
    ) -> None:
        result = load(
            CONFIG
            / "family_experiment"
            / "n100_no_acceleration_qualification.json"
        )
        self.assertEqual(result["functional_transport"]["status"], "PASS")
        self.assertEqual(
            result["continuous_diagnostics"]["status"],
            "INCONCLUSIVE_NO_SOURCED_ERROR_BUDGET",
        )
        self.assertEqual(
            result["decision"],
            {
                "functional_collision_free_transport": "CLOSED",
                "continuous_numerical_equivalence": "INCONCLUSIVE",
                "further_brute_force_refinement": "NOT_AUTHORIZED",
                "next_scope": (
                    "Separate preregistration is required for another radial "
                    "order or acceleration mode."
                ),
            },
        )

    def test_segmented_acceleration_closes_functional_baseline_not_comsol_spatial(
        self,
    ) -> None:
        result = load(
            CONFIG
            / "family_experiment"
            / "n100_segmented_rod_axial_acceleration_qualification.json"
        )
        self.assertEqual(result["baseline_functional_transport"]["status"], "PASS")
        self.assertEqual(
            result["same_solver_spatial"]["simion"]["functional_status"],
            "PASS",
        )
        self.assertEqual(
            result["same_solver_spatial"]["comsol"]["status"],
            "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED",
        )
        self.assertEqual(
            result["decision"]["continuous_numerical_equivalence"],
            "INCONCLUSIVE",
        )
        self.assertEqual(
            result["method"]["sha256"],
            sha256(REPO_ROOT / result["method"]["path"]),
        )
        self.assertEqual(
            result["method"]["acceptance_sha256"],
            sha256(REPO_ROOT / result["method"]["acceptance_path"]),
        )
        self.assertEqual(
            result["particle_source"]["sha256"],
            sha256(REPO_ROOT / result["particle_source"]["path"]),
        )

    def test_public_runners_propagate_typed_mode_identity(self) -> None:
        comsol = (REPO_ROOT / "common" / "multipole" / "run_finite_3d_transport.ps1")
        simion = (
            REPO_ROOT
            / "common"
            / "multipole"
            / "run_simion_finite_3d_transport.ps1"
        )
        for path in (comsol, simion):
            source = path.read_text(encoding="utf-8-sig")
            self.assertIn("profile.paths.operating_mode_registry", source)
            self.assertIn("--operating-mode-registry", source)
            self.assertIn("--mode-id", source)
        for name in ("run_comsol.ps1", "run_simion.ps1"):
            wrapper = (
                PROJECT_ROOT / "workflows" / "no_collision_transport" / name
            ).read_text(encoding="utf-8-sig")
            self.assertIn("[string]$RuntimeProfileId", wrapper)
            self.assertNotIn("[string]$DesignProfileId", wrapper)
            self.assertNotIn("[string]$ParticleSourcePath", wrapper)

    def test_oatof_oracle_remains_rectangular_and_outside_family_scope(self) -> None:
        official = load(CONFIG / "resolved_design_official.json")
        port = load(CONFIG / "interfaces" / "provided" / "rf_multipole_exit.json")
        self.assertEqual(
            official["geometry_mm"]["enclosure"]["model"],
            "rectangular_reference_enclosure_v1",
        )
        self.assertEqual(
            port["profile_scope"],
            {
                "scope_id": "official_transport_oatof_oracle",
                "scope_kind": "integration_oracle",
                "family_experiment_port": False,
            },
        )
        self.assertNotEqual(
            port["mating_surface"]["center_mm"][2],
            self.resolved[MODE_IDS[0]]["interfaces_mm"]["exit"]["handoff_plane_z_mm"],
        )

    def test_legacy_four_arm_experiment_is_an_unexecutable_tombstone(self) -> None:
        tombstone = load(CONFIG / "axial_acceleration_four_arm_experiment.json")
        self.assertEqual(tombstone["role"], "superseded_experiment_tombstone")
        self.assertEqual(tombstone["status"], "SUPERSEDED_NOT_EXECUTABLE")
        self.assertFalse(tombstone["run_authorization"])
        self.assertEqual(
            tombstone["replacement_contract"],
            "projects/rf_quadrupole_ion_optics/config/family_experiment/"
            "n100_convergence_preregistration.json",
        )


if __name__ == "__main__":
    unittest.main()

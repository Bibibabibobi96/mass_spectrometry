from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from common.contracts.machine_contracts import validate_schema
from common.multipole.design_profile import resolve_design_profile
from common.multipole.runtime_profile import resolve_runtime_profile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parents[1]
MODE_IDS = (
    "no_acceleration_full_length",
    "segmented_rod_axial_acceleration",
    "exit_aperture_plate_acceleration",
)


def load(relative: str) -> dict[str, Any]:
    return json.loads((PROJECT_ROOT / relative).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


class FamilyExperimentProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resolved = {
            mode_id: resolve_design_profile(
                REPO_ROOT, "rf_hexapole_ion_optics", mode_id
            )["resolved_design"]
            for mode_id in MODE_IDS
        }

    def test_profiles_share_one_governed_base_catalog_and_envelope(self) -> None:
        registry = load("config/design_profiles.json")
        validate_schema(registry, "design_profiles.schema.json")
        current = [
            profile
            for profile in registry["profiles"]
            if profile["design_profile_id"] in MODE_IDS
        ]
        self.assertEqual({profile["mode_id"] for profile in current}, set(MODE_IDS))
        for key in ("design_request", "design_variables", "optimization_envelope"):
            self.assertEqual({profile[key] for profile in current}, {
                {
                    "design_request": "config/requests/mechanical_base.json",
                    "design_variables": "config/design_variables.json",
                    "optimization_envelope": "config/optimization_envelope.json",
                }[key]
            })
            self.assertEqual(len({profile["sha256"][key] for profile in current}), 1)
        aliases = {
            profile["design_profile_id"]: profile["mode_id"]
            for profile in registry["profiles"]
            if profile["design_profile_id"] not in MODE_IDS
        }
        self.assertEqual(
            aliases,
            {
                "baseline_finite_3d": "segmented_rod_axial_acceleration",
                "exit_aperture_plate_acceleration_reference": (
                    "exit_aperture_plate_acceleration"
                ),
            },
        )

    def test_three_modes_have_exactly_one_mechanical_geometry(self) -> None:
        baseline = self.resolved[MODE_IDS[0]]
        for resolved in self.resolved.values():
            self.assertEqual(resolved["geometry_mm"], baseline["geometry_mm"])
            self.assertEqual(resolved["interfaces_mm"], baseline["interfaces_mm"])
            physical_segments = [
                {
                    key: value
                    for key, value in electrode.items()
                    if key != "common_mode_V"
                }
                for electrode in resolved["segmentation"]["segmented_rod_array"][
                    "electrodes"
                ]
            ]
            baseline_segments = [
                {
                    key: value
                    for key, value in electrode.items()
                    if key != "common_mode_V"
                }
                for electrode in baseline["segmentation"]["segmented_rod_array"][
                    "electrodes"
                ]
            ]
            self.assertEqual(physical_segments, baseline_segments)
        self.assertEqual(
            (baseline["geometry_mm"]["rod_z_min"], baseline["geometry_mm"]["rod_z_max"]),
            (0.0, 79.6),
        )
        segments = baseline["segmentation"]["axial_acceleration"]["derived"]["segments"]
        self.assertEqual(len(segments), 4)
        for segment in segments:
            self.assertAlmostEqual(segment["z_max_mm"] - segment["z_min_mm"], 19.6)
        self.assertEqual(
            baseline["interfaces_mm"],
            {
                "entrance": {
                    "aperture_radius_mm": 3.6,
                    "aperture_plate_upstream_face_z_mm": -1.0,
                    "aperture_plate_downstream_face_z_mm": -0.5,
                    "connector_length_mm": 0.0,
                    "connector_upstream_face_z_mm": -1.0,
                    "connector_downstream_face_z_mm": -1.0,
                    "release_plane_z_mm": -1.5,
                    "connector_shape": "cylindrical_bore",
                },
                "exit": {
                    "aperture_radius_mm": 3.6,
                    "aperture_plate_upstream_face_z_mm": 80.1,
                    "aperture_plate_downstream_face_z_mm": 80.6,
                    "aperture_crossing_plane_z_mm": 80.6,
                    "connector_length_mm": 0.0,
                    "connector_upstream_face_z_mm": 80.6,
                    "connector_downstream_face_z_mm": 80.6,
                    "handoff_plane_z_mm": 80.6,
                    "census_plane_z_mm": 81.1,
                    "connector_shape": "cylindrical_bore",
                },
            },
        )

    def test_modes_differ_only_by_registered_electrical_assignments(self) -> None:
        expected = {
            "no_acceleration_full_length": ([0.0, 0.0, 0.0, 0.0], 0.0),
            "segmented_rod_axial_acceleration": ([0.0, -1.0, -2.0, -3.0], -3.0),
            "exit_aperture_plate_acceleration": ([0.0, 0.0, 0.0, 0.0], -3.0),
        }
        for mode_id, resolved in self.resolved.items():
            segment_voltages = [
                segment["common_mode_V"]
                for segment in resolved["segmentation"]["axial_acceleration"][
                    "derived"
                ]["segments"]
            ]
            exit_voltage = resolved["static_electrodes_V"][
                "exit_outer_endcap_aperture_plate_connector_V"
            ]
            self.assertEqual((segment_voltages, exit_voltage), expected[mode_id])

    def test_runtime_tiers_change_only_the_registered_numerical_axis(self) -> None:
        for mode_id in MODE_IDS:
            baseline = resolve_runtime_profile(
                REPO_ROOT, "rf_hexapole_ion_optics", mode_id
            )
            spatial = resolve_runtime_profile(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                f"{mode_id}_n100_spatial_refined",
            )
            temporal = resolve_runtime_profile(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                f"{mode_id}_n100_temporal_refined",
            )
            statistical = resolve_runtime_profile(
                REPO_ROOT, "rf_hexapole_ion_optics", f"{mode_id}_n1000"
            )
            self.assertEqual(
                {
                    baseline["design_profile_id"],
                    spatial["design_profile_id"],
                    temporal["design_profile_id"],
                    statistical["design_profile_id"],
                },
                {mode_id},
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                spatial["particle_source"]["sha256"],
            )
            self.assertEqual(
                baseline["particle_source"]["profile_id"],
                "family_mother_sample_v1_n100",
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
            )
            self.assertEqual(
                baseline["particle_source"]["sha256"],
                temporal["particle_source"]["sha256"],
            )
            self.assertEqual(
                temporal["solver_numerics"]["comsol"]["values"]["mesh"][
                    "working_region_maximum_element_size_mm"
                ],
                0.25,
            )
            self.assertEqual(
                temporal["solver_numerics"]["comsol"]["values"]["trajectory"][
                    "rf_steps_per_period"
                ],
                160,
            )
            self.assertEqual(
                temporal["solver_numerics"]["simion"]["values"]["cell_mm"],
                0.2,
            )
            self.assertEqual(
                temporal["solver_numerics"]["simion"]["values"]["trajectory"][
                    "rf_steps_per_period"
                ],
                80,
            )
            self.assertEqual(
                statistical["particle_source"]["sha256"],
                "CE68A6B47DC5726D9C45CBE28E4397A2321D782FAED265067824891AAF4D0FBF",
            )
            self.assertEqual(
                statistical["particle_source"]["profile_id"],
                "family_mother_sample_v1_n1000",
            )
        for alias in (
            "baseline_finite_3d",
            "exit_aperture_plate_acceleration_reference",
        ):
            resolved_alias = resolve_runtime_profile(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                alias,
            )
            self.assertEqual(
                resolved_alias["particle_source"]["profile_id"],
                "family_mother_sample_v1_n100",
            )

    def test_preregistration_refuses_unsourced_numerical_thresholds(self) -> None:
        convergence = load("config/qualification/n100_convergence_preregistration.json")
        for solver_id, spatial_key in (
            ("comsol", "working_region_maximum_element_size_mm"),
            ("simion", "cell_mm"),
        ):
            plan = convergence["solver_plans"][solver_id]
            self.assertEqual(
                plan["registry_sha256"],
                sha256(REPO_ROOT / plan["registry"]),
            )
            self.assertEqual(
                plan["tiers"]["temporal_refined"][spatial_key],
                plan["tiers"]["spatial_refined"][spatial_key],
            )
        self.assertFalse(convergence["decision_policy"]["qualification_pass_allowed"])
        self.assertEqual(
            convergence["decision_policy"]["continuous_result"], "INCONCLUSIVE"
        )
        for name, role, content in (
            (
                "dispersion_acceptance.json",
                "multipole_dispersion_acceptance_contract",
                "acceptance_criteria",
            ),
            (
                "dispersion_effect_resolution.json",
                "multipole_dispersion_effect_resolution_contract",
                "effect_resolution",
            ),
            (
                "engineering_budget.json",
                "multipole_engineering_budget_contract",
                "pilot_authorization",
            ),
        ):
            contract = load(f"config/qualification/{name}")
            self.assertEqual(contract["role"], role)
            self.assertTrue(contract["preregistered_before_run"])
            self.assertTrue(contract[content])
        engineering = load("config/qualification/engineering_budget.json")
        self.assertTrue(engineering["pilot_authorization"]["authorized"])
        self.assertEqual(
            engineering["pilot_authorization"]["scope"]["runtime_profile_id"],
            "no_acceleration_full_length",
        )
        self.assertFalse(engineering["full_matrix_authorization"]["authorized"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.runtime_profile import (
    resolve_runtime_profile,
    resolve_runtime_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "rf_quadrupole_ion_optics"
CAMPAIGN_ROOT = REPO_ROOT / "common" / "multipole" / "campaigns"
EXPERIMENT_ID = "quad_noacc_simion_h15_r015_z020_t160"
RUN_ID = "20260731_143000__sim__simion__quad-noacc-radial-h15-r015-z020-t160"


def campaign_fixture() -> dict:
    return {
        "schema_version": 1,
        "role": "multipole_transport_experiment_campaign",
        "family_id": "rf_multipole_ion_optics",
        "campaign_id": "quad_simion_radial_extension_v1",
        "preregistered_before_run": True,
        "experiments": [
            {
                "experiment_id": EXPERIMENT_ID,
                "project_id": PROJECT_ID,
                "authorized_run_id": RUN_ID,
                "solver": "simion",
                "stop_stage": "transport",
                "design_profile_id": "no_acceleration_full_length",
                "particle_source_profile_id": "family_mother_sample_v1_n100",
                "comsol_solver_numerics_profile_id": "baseline_finite_3d",
                "simion_solver_numerics": {
                    "kind": "inline",
                    "numerics_id": "simion_h15_r015_z020_t160",
                    "values": {
                        "cell_mm_xyz": {"x": 0.15, "y": 0.15, "z": 0.2},
                        "trajectory_quality": 10,
                        "trajectory": {
                            "rf_steps_per_period": 160,
                            "maximum_global_time_us": 80.0,
                        },
                    },
                },
                "retention_class": "compact",
                "resource_authorization": {
                    "authorized": True,
                    "limits": {
                        "wall_clock_seconds_by_solver": {
                            "comsol": 1800,
                            "simion": 2400,
                        },
                        "transient_run_directory_bytes": 8589934592,
                        "process_tree_working_set_bytes": 8589934592,
                        "minimum_system_available_memory_bytes": 8589934592,
                        "compact_final_retained_bytes": 26214400,
                        "maximum_pa_grid_points": 35000000,
                        "automatic_retry_count": 0,
                    },
                    "full_matrix_authorization": {
                        "authorized": False,
                        "reason": "Only this preregistered SIMION transport arm is authorized.",
                    },
                    "budget_exhaustion_result": (
                        "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED"
                    ),
                },
                "claim_limit": (
                    "N=100 SIMION numerical-sensitivity evidence only; "
                    "no convergence or solver-equivalence claim."
                ),
            }
        ],
        "claim_limit": "Campaign experiments remain unqualified numerical evidence.",
    }


@contextmanager
def written_campaign(document: dict) -> Iterator[Path]:
    campaign_root_existed = CAMPAIGN_ROOT.is_dir()
    CAMPAIGN_ROOT.mkdir(exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".transport_campaign_test_", dir=CAMPAIGN_ROOT
        ) as directory:
            path = Path(directory) / "campaign.json"
            path.write_text(
                json.dumps(document, indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            yield path
    finally:
        if not campaign_root_existed:
            try:
                CAMPAIGN_ROOT.rmdir()
            except OSError:
                pass


class TransportCampaignTests(unittest.TestCase):
    def test_checked_in_family_campaign_resolves_every_declared_row(self) -> None:
        path = (
            REPO_ROOT
            / "common"
            / "multipole"
            / "campaigns"
            / "20260731__noacc_vs_segmented_h15_n100.json"
        )
        campaign = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(campaign["experiments"]), 5)
        for experiment in campaign["experiments"]:
            resolved = resolve_runtime_selection(
                REPO_ROOT,
                experiment["project_id"],
                campaign_path=path,
                experiment_id=experiment["experiment_id"],
            )
            pilot = resolved["engineering_budget"]["inline_contract"][
                "pilot_authorization"
            ]
            scope = pilot["scope"]
            self.assertEqual(
                scope["authorized_run_id"], experiment["authorized_run_id"]
            )
            self.assertEqual(scope["allowed_solvers"], ["simion"])
            self.assertEqual(scope["particle_count"], 100)
            self.assertEqual(
                pilot["limits"]["maximum_pa_grid_points"], 35_000_000
            )

    def test_checked_in_endface_campaign_resolves_canonical_third_arm(self) -> None:
        path = (
            REPO_ROOT
            / "common"
            / "multipole"
            / "campaigns"
            / "20260731__endface_h15_n100.json"
        )
        campaign = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(campaign["experiments"]), 3)
        self.assertEqual(
            {item["project_id"] for item in campaign["experiments"]},
            {
                "rf_quadrupole_ion_optics",
                "rf_hexapole_ion_optics",
                "rf_octupole_ion_optics",
            },
        )
        for experiment in campaign["experiments"]:
            self.assertEqual(
                experiment["design_profile_id"],
                "exit_aperture_plate_acceleration",
            )
            resolved = resolve_runtime_selection(
                REPO_ROOT,
                experiment["project_id"],
                campaign_path=path,
                experiment_id=experiment["experiment_id"],
            )
            design = resolved["design_profile_resolution"]["resolved_design"]
            self.assertEqual(
                design["axial_drive"]["topology"],
                "exit_aperture_plate_potential_step",
            )
            self.assertEqual(
                resolved["solver_numerics"]["simion"]["values"]["cell_mm_xyz"],
                {"x": 0.15, "y": 0.15, "z": 0.2},
            )

    def test_family_campaign_launcher_is_a_serial_thin_selector(self) -> None:
        source = (
            REPO_ROOT
            / "common"
            / "multipole"
            / "run_simion_transport_campaign.ps1"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("parametersetname = 'one'", source)
        self.assertIn("parametersetname = 'all'", source)
        self.assertIn("parametersetname = 'status'", source)
        self.assertIn("invoke-multipoleprojectfinite3dtransport", source)
        self.assertNotIn("start-job", source)
        self.assertNotIn("foreach-object -parallel", source)
        self.assertNotIn("automaticretry", source)


    def test_campaign_resolves_existing_authorities_and_inline_simion_numerics(
        self,
    ) -> None:
        with written_campaign(campaign_fixture()) as path:
            resolved = resolve_runtime_selection(
                REPO_ROOT,
                PROJECT_ID,
                campaign_path=path,
                experiment_id=EXPERIMENT_ID,
            )
            self.assertEqual(resolved["runtime_profile_id"], EXPERIMENT_ID)
            self.assertEqual(
                resolved["design_profile_id"], "no_acceleration_full_length"
            )
            self.assertEqual(
                resolved["particle_source"]["profile_id"],
                "family_mother_sample_v1_n100",
            )
            self.assertEqual(
                resolved["solver_numerics"]["comsol"]["profile_id"],
                "baseline_finite_3d",
            )
            self.assertEqual(
                resolved["solver_numerics"]["simion"],
                {
                    "profile_id": "simion_h15_r015_z020_t160",
                    "values": {
                        "cell_mm_xyz": {"x": 0.15, "y": 0.15, "z": 0.2},
                        "trajectory_quality": 10,
                        "trajectory": {
                            "rf_steps_per_period": 160,
                            "maximum_global_time_us": 80.0,
                        },
                    },
                    "registry_sha256": resolved["campaign"]["sha256"],
                },
            )
            self.assertEqual(
                resolved["engineering_budget"]["inline_contract"][
                    "pilot_authorization"
                ]["scope"]["authorized_run_id"],
                RUN_ID,
            )

    def test_campaign_budget_normalizes_to_existing_resolved_budget_semantics(
        self,
    ) -> None:
        with written_campaign(campaign_fixture()) as path:
            runtime = resolve_runtime_selection(
                REPO_ROOT,
                PROJECT_ID,
                campaign_path=path,
                experiment_id=EXPERIMENT_ID,
            )
            result = validate_pilot_budget(
                repo_root=REPO_ROOT,
                budget_path=path,
                project_id=PROJECT_ID,
                solver="simion",
                runtime_profile_id=EXPERIMENT_ID,
                design_profile_id=runtime["design_profile_id"],
                particle_source_path=Path(runtime["particle_source"]["path"]),
                retention_class="compact",
                run_id=RUN_ID,
            )
            self.assertEqual(result["role"], "multipole_resolved_resource_budget")
            self.assertEqual(result["runtime_profile_id"], EXPERIMENT_ID)
            self.assertEqual(result["authorized_run_id"], RUN_ID)
            self.assertEqual(result["limits"]["wall_clock_seconds"], 2400)
            self.assertEqual(result["limits"]["maximum_pa_grid_points"], 35000000)
            with self.assertRaisesRegex(ValueError, "authorized_run_id"):
                validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=path,
                    project_id=PROJECT_ID,
                    solver="simion",
                    runtime_profile_id=EXPERIMENT_ID,
                    design_profile_id=runtime["design_profile_id"],
                    particle_source_path=Path(runtime["particle_source"]["path"]),
                    retention_class="compact",
                    run_id=RUN_ID + "__r02",
                )

    def test_legacy_runtime_selection_is_field_compatible(self) -> None:
        legacy = resolve_runtime_profile(
            REPO_ROOT, PROJECT_ID, "no_acceleration_full_length"
        )
        selected = resolve_runtime_selection(
            REPO_ROOT,
            PROJECT_ID,
            runtime_profile_id="no_acceleration_full_length",
        )
        self.assertEqual(selected, legacy)

    def test_campaign_rejects_duplicate_unknown_and_physical_override_fields(
        self,
    ) -> None:
        duplicate = campaign_fixture()
        duplicate["experiments"].append(copy.deepcopy(duplicate["experiments"][0]))
        with written_campaign(duplicate) as path:
            with self.assertRaisesRegex(ValueError, "must be unique"):
                resolve_runtime_selection(
                    REPO_ROOT,
                    PROJECT_ID,
                    campaign_path=path,
                    experiment_id=EXPERIMENT_ID,
                )

        physical_override = campaign_fixture()
        physical_override["experiments"][0]["rf_peak_v"] = 100.0
        with written_campaign(physical_override) as path:
            with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign"):
                resolve_runtime_selection(
                    REPO_ROOT,
                    PROJECT_ID,
                    campaign_path=path,
                    experiment_id=EXPERIMENT_ID,
                )

    def test_campaign_rejects_partial_numerics_and_unsupported_execution(self) -> None:
        partial = campaign_fixture()
        del partial["experiments"][0]["simion_solver_numerics"]["values"][
            "trajectory"
        ]
        with written_campaign(partial) as path:
            with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign"):
                resolve_runtime_selection(
                    REPO_ROOT,
                    PROJECT_ID,
                    campaign_path=path,
                    experiment_id=EXPERIMENT_ID,
                )

        unsupported = campaign_fixture()
        unsupported["experiments"][0]["solver"] = "comsol"
        with written_campaign(unsupported) as path:
            with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign"):
                resolve_runtime_selection(
                    REPO_ROOT,
                    PROJECT_ID,
                    campaign_path=path,
                    experiment_id=EXPERIMENT_ID,
                )

    def test_campaign_path_must_remain_inside_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            path.write_text(json.dumps(campaign_fixture()), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "escapes common/multipole/campaigns"
            ):
                resolve_runtime_selection(
                    REPO_ROOT,
                    PROJECT_ID,
                    campaign_path=path,
                    experiment_id=EXPERIMENT_ID,
                )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from common.multipole.resource_budget import validate_pilot_budget
from common.multipole.campaign_status import campaign_status
from common.multipole.runtime_profile import (
    resolve_runtime_profile,
    resolve_runtime_selection,
    semantic_diff_campaign_experiments,
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


def analysis_campaign_fixture() -> dict:
    source = json.loads(
        (
            CAMPAIGN_ROOT / "20260731__oatof_shield_terminal_h15_n100.json"
        ).read_text(encoding="utf-8-sig")
    )
    template = next(
        item
        for item in source["experiments"]
        if item["experiment_id"] == "hex_segmented_oatof_terminal_h15_n100"
    )
    rows = []
    for index, suffix in enumerate(("baseline", "drive")):
        row = copy.deepcopy(template)
        row["experiment_id"] = f"analysis_contract_{suffix}"
        row["authorized_run_id"] = (
            f"20260803_120{index:02d}__sim__simion__analysis-contract-{suffix}"
        )
        row["execution_profile_id"] = "simion_transport_campaign_engineering"
        row["case_set"] = "primary_only"
        row["design_variable_values"] = {
            "rf_amplitude": 139.81792 if index == 0 else 153.799712,
            "rf_frequency": 1_100_000.0 if index == 0 else 1_210_000.0,
        }
        rows.append(row)
    return {
        "schema_version": 4,
        "role": source["role"],
        "family_id": source["family_id"],
        "campaign_id": "analysis_contract_v4",
        "preregistered_before_run": True,
        "downstream_terminal_profile": source["downstream_terminal_profile"],
        "design_variable_authorization": {
            "allowed_variable_ids": ["rf_amplitude", "rf_frequency"],
            "variable_limits": [
                {
                    "variable_id": "rf_amplitude",
                    "unit": "V",
                    "minimum": 139.81792,
                    "maximum": 169.179683,
                },
                {
                    "variable_id": "rf_frequency",
                    "unit": "Hz",
                    "minimum": 1_100_000.0,
                    "maximum": 1_210_000.0,
                },
            ],
        },
        "particle_source_phase_policy": {
            "kind": "match_baseline_rf_phase",
            "baseline_frequency_Hz": 1_100_000.0,
            "frequency_variable_id": "rf_frequency",
            "n1000_reference_profile_id": "family_mother_sample_v1_n1000",
        },
        "experiments": rows,
        "analysis_requests": [
            {
                "capability_id": "multipole_exit_state_comparison_v1",
                "experiment_ids": [row["experiment_id"] for row in rows],
                "baseline_experiment_id": rows[0]["experiment_id"],
                "analysis_run_id": (
                    "20260803_120200__analysis__cross__campaign-diagnostic-test"
                ),
                "parameters": {},
            }
        ],
        "claim_limit": "Analysis contract test only; no physical claim.",
    }


@contextmanager
def written_campaign(document: dict) -> Iterator[Path]:
    campaign_root_existed = CAMPAIGN_ROOT.is_dir()
    CAMPAIGN_ROOT.mkdir(exist_ok=True)
    path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            prefix=".transport_campaign_test_",
            # The production path guard requires this fixture to remain under
            # the campaign root. A non-publication suffix keeps concurrent
            # repository-binding scans from treating the in-flight fixture as
            # an active campaign.
            suffix=".tmp",
            dir=CAMPAIGN_ROOT,
            delete=False,
            encoding="utf-8",
        ) as stream:
            json.dump(document, stream, indent=2, allow_nan=False)
            stream.write("\n")
            path = Path(stream.name)
        yield path
    finally:
        if path is not None:
            path.unlink(missing_ok=True)
        if not campaign_root_existed:
            try:
                CAMPAIGN_ROOT.rmdir()
            except OSError:
                pass


class TransportCampaignTests(unittest.TestCase):
    def test_analysis_capability_catalog_is_single_governed_authority(self) -> None:
        path = REPO_ROOT / "common/multipole/analysis_capabilities.json"
        catalog = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertEqual(
            set(catalog), {"schema_version", "role", "capabilities"}
        )
        self.assertEqual(
            catalog["role"], "multipole_campaign_analysis_capability_catalog"
        )
        capability = catalog["capabilities"][0]
        self.assertEqual(
            capability["capability_id"],
            "multipole_exit_state_comparison_v1",
        )
        self.assertEqual(
            set(capability["allowed_parameters"]), {"bin_count", "dpi"}
        )
        for module in capability["consumer"].values():
            self.assertRegex(module, r"^common\.multipole\.[a-z][a-z0-9_]*$")
            self.assertTrue(
                (REPO_ROOT / (module.replace(".", "/") + ".py")).is_file()
            )

    def test_campaign_v4_status_validates_analysis_without_writing_runs(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        campaign = analysis_campaign_fixture()
        run_dirs = [
            REPO_ROOT.parent
            / "artifacts/projects"
            / row["project_id"]
            / "runs"
            / row["authorized_run_id"]
            for row in campaign["experiments"]
        ]
        analysis_dir = (
            REPO_ROOT.parent
            / "artifacts/projects"
            / campaign["experiments"][0]["project_id"]
            / "runs"
            / campaign["analysis_requests"][0]["analysis_run_id"]
        )
        self.assertFalse(any(path.exists() for path in (*run_dirs, analysis_dir)))
        with written_campaign(campaign) as path:
            completed = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-File",
                    str(REPO_ROOT / "common/multipole/run_simion_transport_campaign.ps1"),
                    "-CampaignPath",
                    str(path),
                    "-Status",
                    "-RepoRoot",
                    str(REPO_ROOT),
                    "-PythonExe",
                    sys.executable,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("MULTIPOLE_CAMPAIGN_ANALYSIS_STATUS=PENDING", completed.stdout)
        self.assertFalse(any(path.exists() for path in (*run_dirs, analysis_dir)))

    def test_campaign_v4_rejects_capability_reference_and_parameter_escape(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        cases = (
            ("capability_id", "unknown_capability"),
            ("experiment_ids", None),
            ("dpi", 301),
        )
        for field, value in cases:
            campaign = analysis_campaign_fixture()
            if field in {"capability_id", "experiment_ids"}:
                if field == "experiment_ids":
                    value = [
                        campaign["analysis_requests"][0]["baseline_experiment_id"],
                        "outside_campaign",
                    ]
                campaign["analysis_requests"][0][field] = value
            else:
                campaign["analysis_requests"][0]["parameters"][field] = value
            with self.subTest(field=field), written_campaign(campaign) as path:
                completed = subprocess.run(
                    [
                        pwsh,
                        "-NoProfile",
                        "-File",
                        str(REPO_ROOT / "common/multipole/run_simion_transport_campaign.ps1"),
                        "-CampaignPath",
                        str(path),
                        "-Status",
                        "-RepoRoot",
                        str(REPO_ROOT),
                        "-PythonExe",
                        sys.executable,
                    ],
                    cwd=REPO_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                    check=False,
                )
            self.assertNotEqual(completed.returncode, 0)
            self.assertRegex(
                completed.stdout + completed.stderr,
                "Unknown analysis capability|missing campaign experiment|"
                "outside its capability envelope",
            )

    def test_campaign_v4_requires_case_set(self) -> None:
        campaign = analysis_campaign_fixture()
        del campaign["experiments"][0]["case_set"]
        with written_campaign(campaign) as path:
            with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign"):
                resolve_runtime_selection(
                    REPO_ROOT,
                    campaign["experiments"][0]["project_id"],
                    campaign_path=path,
                    experiment_id=campaign["experiments"][0]["experiment_id"],
                )

    def test_campaign_v1_to_v3_forbid_case_set(self) -> None:
        v3 = analysis_campaign_fixture()
        v3["schema_version"] = 3
        del v3["analysis_requests"]
        for row in v3["experiments"]:
            del row["case_set"]
        campaigns = []
        for version in (1, 2, 3):
            campaign = copy.deepcopy(v3)
            campaign["schema_version"] = version
            if version < 3:
                del campaign["design_variable_authorization"]
                del campaign["particle_source_phase_policy"]
                for row in campaign["experiments"]:
                    del row["execution_profile_id"]
                    del row["design_variable_values"]
            if version == 1:
                del campaign["downstream_terminal_profile"]
            campaign["experiments"][0]["case_set"] = "primary_only"
            campaigns.append(campaign)
        for campaign in campaigns:
            with self.subTest(schema_version=campaign["schema_version"]), written_campaign(
                campaign
            ) as path:
                with self.assertRaisesRegex(
                    ValueError, "invalid multipole transport campaign"
                ):
                    resolve_runtime_selection(
                        REPO_ROOT,
                        campaign["experiments"][0]["project_id"],
                        campaign_path=path,
                        experiment_id=campaign["experiments"][0]["experiment_id"],
                    )

    def test_campaign_status_accepts_repository_relative_path(self) -> None:
        status = campaign_status(
            REPO_ROOT,
            Path(
                "common/multipole/campaigns/"
                "20260731__oatof_shield_terminal_h15_n100.json"
            ),
        )
        self.assertEqual(
            status["campaign_id"], "20260731__oatof_shield_terminal_h15_n100"
        )
        self.assertEqual(len(status["experiments"]), 9)

    def test_oatof_terminal_campaign_resolves_one_shared_terminal_for_nine_rows(
        self,
    ) -> None:
        path = CAMPAIGN_ROOT / "20260731__oatof_shield_terminal_h15_n100.json"
        campaign = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(campaign["schema_version"], 2)
        self.assertEqual(len(campaign["experiments"]), 9)
        self.assertEqual(
            set(campaign["downstream_terminal_profile"]),
            {"integration_id", "terminal_profile_id", "registry_sha256"},
        )
        for experiment in campaign["experiments"]:
            self.assertNotIn("downstream_terminal_profile", experiment)
            resolved = resolve_runtime_selection(
                REPO_ROOT,
                experiment["project_id"],
                campaign_path=path,
                experiment_id=experiment["experiment_id"],
            )
            terminal = resolved["design_profile_resolution"]["resolved_design"][
                "downstream_terminal"
            ]
            self.assertEqual(terminal["owner"], "downstream")
            self.assertEqual(terminal["surface_plane_z_mm"], 80.6)
            self.assertEqual(terminal["rod_end_clearance_mm"], 1.0)
            self.assertEqual(
                terminal["aperture"],
                {
                    "shape": "rectangular",
                    "width_mm": 1.0,
                    "height_mm": 0.9,
                    "width_axis": "multipole_x",
                    "height_axis": "multipole_y",
                },
            )
            self.assertFalse(terminal["upstream_terminal_electrode_present"])
            self.assertEqual(
                resolved["design_profile_resolution"]["resolved_design"]["axial_dc"]
                ["terminal_electrode_potential_V"],
                0.0,
            )

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

    def test_family_campaign_launcher_dry_run_resolves_each_case_without_artifacts(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        campaign = analysis_campaign_fixture()
        with tempfile.TemporaryDirectory() as directory, written_campaign(campaign) as path:
            plan_path = Path(directory) / "resolved_execution_plan.json"
            completed = subprocess.run(
                [
                    pwsh, "-NoProfile", "-File",
                    str(REPO_ROOT / "common/multipole/run_simion_transport_campaign.ps1"),
                    "-CampaignPath", str(path), "-All", "-DryRun",
                    "-DryRunOutput", str(plan_path),
                    "-RepoRoot", str(REPO_ROOT), "-PythonExe", sys.executable,
                ],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120, check=False,
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        expected = [row["experiment_id"] for row in campaign["experiments"]]
        observed = [
            line.split("EXPERIMENT=", 1)[1].split(" RUN=", 1)[0]
            for line in completed.stdout.splitlines()
            if line.startswith("MULTIPOLE_CAMPAIGN=DRY_RUN ")
        ]
        self.assertEqual(observed, expected)
        self.assertIn("CASE_SET=primary_only", completed.stdout)
        self.assertEqual(plan["role"], "multipole_campaign_resolved_execution_plan")
        self.assertEqual(
            [profile["runtime_profile_id"] for profile in plan["experiments"]],
            expected,
        )
        self.assertTrue(all("solver_numerics" in profile for profile in plan["experiments"]))

    def test_campaign_semantic_diff_resolves_profiles_without_execution_policy(self) -> None:
        campaign = campaign_fixture()
        compared = copy.deepcopy(campaign["experiments"][0])
        compared["experiment_id"] = "quad_noacc_simion_refined_grid"
        compared["authorized_run_id"] = RUN_ID.replace("t160", "t320")
        compared["simion_solver_numerics"]["values"]["cell_mm_xyz"]["x"] = 0.12
        campaign["experiments"].append(compared)
        with written_campaign(campaign) as path:
            diff = semantic_diff_campaign_experiments(
                REPO_ROOT, path, EXPERIMENT_ID, compared["experiment_id"]
            )
        self.assertEqual(diff["role"], "multipole_campaign_resolved_semantic_diff")
        self.assertEqual(diff["classification_scope"], "review_only_not_execution_policy")
        changes = {item["path"]: item for item in diff["changes"]}
        self.assertEqual(changes["solver_numerics.simion.values.cell_mm_xyz.x"]["category"], "solver_numerics")
        self.assertEqual(changes["runtime_profile_id"]["category"], "run_control_or_budget")

    def test_campaign_launcher_exposes_resolved_semantic_diff(self) -> None:
        pwsh = shutil.which("pwsh")
        if pwsh is None:
            self.skipTest("PowerShell Core is unavailable")
        campaign = campaign_fixture()
        compared = copy.deepcopy(campaign["experiments"][0])
        compared["experiment_id"] = "quad_noacc_simion_refined_grid"
        compared["authorized_run_id"] = RUN_ID.replace("t160", "t320")
        compared["simion_solver_numerics"]["values"]["trajectory_quality"] = 11
        campaign["experiments"].append(compared)
        with written_campaign(campaign) as path:
            completed = subprocess.run(
                [
                    pwsh, "-NoProfile", "-File",
                    str(REPO_ROOT / "common/multipole/run_simion_transport_campaign.ps1"),
                    "-CampaignPath", str(path), "-ExperimentId", EXPERIMENT_ID,
                    "-SemanticDiffAgainst", compared["experiment_id"],
                    "-RepoRoot", str(REPO_ROOT), "-PythonExe", sys.executable,
                ],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=120, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        diff = json.loads(completed.stdout)
        self.assertEqual(diff["role"], "multipole_campaign_resolved_semantic_diff")
        self.assertTrue(any(item["path"] == "solver_numerics.simion.values.trajectory_quality" for item in diff["changes"]))


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

    def test_campaign_keeps_large_exploration_numerics_separate_from_dispatch(self) -> None:
        campaign = campaign_fixture()
        values = campaign["experiments"][0]["simion_solver_numerics"]["values"]
        values["cell_mm_xyz"] = {"x": 101.0, "y": 125.0, "z": 150.0}
        values["trajectory_quality"] = 10_001
        values["trajectory"]["rf_steps_per_period"] = 10_001
        values["trajectory"]["maximum_global_time_us"] = 1_000_001.0
        dispatch = {
            "dispatch": "single_wave_parallel", "batch_count": 17
        }
        campaign["experiments"][0]["simion_dispatch"] = dispatch
        with written_campaign(campaign) as path:
            selected = resolve_runtime_selection(
                REPO_ROOT,
                PROJECT_ID,
                campaign_path=path,
                experiment_id=EXPERIMENT_ID,
            )
            self.assertEqual(
                selected["solver_numerics"]["simion"]["values"], values
            )
            self.assertNotIn("execution_batching", selected["solver_numerics"]["simion"]["values"])
            self.assertEqual(selected["simion_dispatch"], dispatch)

    def test_campaign_accepts_small_positive_exploration_numerics(self) -> None:
        campaign = campaign_fixture()
        values = campaign["experiments"][0]["simion_solver_numerics"]["values"]
        values["cell_mm_xyz"] = {"x": 1e-6, "y": 2e-6, "z": 3e-6}
        values["trajectory"]["maximum_global_time_us"] = 1e-6
        with written_campaign(campaign) as path:
            selected = resolve_runtime_selection(
                REPO_ROOT,
                PROJECT_ID,
                campaign_path=path,
                experiment_id=EXPERIMENT_ID,
            )
        self.assertEqual(selected["solver_numerics"]["simion"]["values"], values)

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

"""Contract tests for the campaign-only multipole-to-oaTOF workflow."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from common.contracts.machine_contracts import ContractError, validate_schema
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.prepare import (
    prepare_family_source_closure,
)
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run import (
    INTEGRATION_ID,
    publish_family_source_closure_run,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
INTEGRATION_ROOT = REPO_ROOT / "integrations" / INTEGRATION_ID
CONFIG_ROOT = INTEGRATION_ROOT / "config"
CAMPAIGN_PATH = CONFIG_ROOT / "experiment_campaign.json"
N1000_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_simion_aperture050_n1000_campaign.json"
)
SINGLE_FLIGHT_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_simion_single_flight_aperture100_n1000_campaign.json"
)
TERMINAL_DESIGN_REFERENCE_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics"
    / "octupole_terminal_15mm_sleeve_single_flight_n1000_campaign.json"
)
Z_ACCEPTANCE_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_z_acceptance_d1_4mm_n1000_campaign.json"
)
GRID_CONVERGENCE_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_frontend_grid_convergence_n1000_campaign.json"
)
ACCELERATION_AXIS_GRID_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics"
    / "octupole_frontend_acceleration_axis_grid_n1000_campaign.json"
)
IDEAL_FIELD_CAMPAIGN_PATH = (
    CONFIG_ROOT / "diagnostics" / "octupole_accelerator_ideal_field_n1000_campaign.json"
)
PROFILE_REGISTRY = CONFIG_ROOT / "connection_profiles.json"
ADAPTER_REGISTRY = CONFIG_ROOT / "execution_adapter_profiles.json"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class FamilySourceClosureWorkflowTests(unittest.TestCase):
    def test_native_grid_short_focus_row_rebuilds_current_reflectron(self) -> None:
        campaign_path = (
            CONFIG_ROOT / "diagnostics" /
            "octupole_native_grid_short_focus_r100_n100_campaign.json"
        )
        campaign = load(campaign_path)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        row = campaign["experiments"][0]
        self.assertIn("native-grid diagnostic", campaign["claim_limit"])
        self.assertNotIn("Candidate claim", campaign["claim_limit"])
        self.assertEqual(row["single_flight_layout_profile_id"], "theory_source_z10_d1_3")
        self.assertEqual(row["single_flight_frontend_grid_profile_id"], "frontend_isotropic_020_accelerator_overlay_z005")
        self.assertEqual(row["single_flight_oatof_numerical_profile_id"], "oatof_reflectron_z010_r100")
        self.assertEqual(row["source"]["launched_particle_count"], 100)
        scratch = (
            REPO_ROOT.parent / "artifacts" / "projects" / INTEGRATION_ID / "scratch"
        )
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            output = Path(directory)
            prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=campaign_path,
                experiment_id=row["experiment_id"],
                resolved_output=output / "resolved.json",
                plan_output=output / "plan.json",
            )
            geometry = load(output / "resolved_oatof_geometry.json")
        rebuild = geometry["single_flight_layout_derivation"]["design_compilation"][
            "simion_rebuild_plan"
        ]
        self.assertTrue(rebuild["frontend_pa"])
        self.assertTrue(rebuild["flight_tube_pa"])
        self.assertTrue(rebuild["reflectron_pa"])

    def test_ideal_accelerator_field_is_a_registered_counterfactual(self) -> None:
        campaign = load(IDEAL_FIELD_CAMPAIGN_PATH)
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        row = campaign["experiments"][0]
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        profiles = {
            item["profile_id"]: item
            for item in configuration["accelerator_field_profiles"]
        }
        self.assertEqual(
            configuration["default_accelerator_field_profile_id"],
            "accelerator_real_pa",
        )
        selected = profiles[row["single_flight_accelerator_field_profile_id"]]
        self.assertEqual(selected["single_flight_ideal_accel_enable"], 1)
        self.assertEqual(
            row["single_flight_frontend_grid_profile_id"],
            "frontend_isotropic_0125",
        )

    def test_grid_convergence_campaign_uses_registered_single_variable_profiles(self) -> None:
        campaign = load(GRID_CONVERGENCE_CAMPAIGN_PATH)
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        profiles = {
            item["profile_id"]: item
            for item in configuration["frontend_grid_profiles"]
        }
        self.assertEqual(
            configuration["default_frontend_grid_profile_id"],
            "frontend_isotropic_020",
        )
        selected = [
            row["single_flight_frontend_grid_profile_id"]
            for row in campaign["experiments"]
        ]
        self.assertEqual(
            [profiles[profile_id]["cell_mm_xyz"] for profile_id in selected],
            [
                {"x": 0.2, "y": 0.2, "z": 0.2},
                {"x": 0.15, "y": 0.15, "z": 0.15},
                {"x": 0.125, "y": 0.125, "z": 0.125},
            ],
        )
        frozen_physics = [
            (
                row["single_flight_layout_profile_id"],
                row["single_flight_design_overrides"],
                row["single_flight_particle_source"],
            )
            for row in campaign["experiments"]
        ]
        self.assertTrue(all(item == frozen_physics[0] for item in frozen_physics))

    def test_acceleration_axis_grid_campaign_changes_only_z_discretization(self) -> None:
        campaign = load(ACCELERATION_AXIS_GRID_CAMPAIGN_PATH)
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        configuration = load(CONFIG_ROOT / "simion_single_flight.json")
        profiles = {
            item["profile_id"]: item
            for item in configuration["frontend_grid_profiles"]
        }
        rows = campaign["experiments"]
        cells = [
            profiles[row["single_flight_frontend_grid_profile_id"]]["cell_mm_xyz"]
            for row in rows
        ]
        self.assertEqual(cells, [
            {"x": 0.2, "y": 0.2, "z": 0.1},
            {"x": 0.2, "y": 0.2, "z": 0.05},
        ])
        self.assertTrue(all("single_flight_design_overrides" not in row for row in rows))
        frozen_physics = [
            (
                row["single_flight_layout_profile_id"],
                row["single_flight_particle_source"],
                row["source"],
                row["single_flight_design_reference"],
            )
            for row in rows
        ]
        self.assertEqual(frozen_physics[0], frozen_physics[1])

    def test_unknown_frontend_grid_profile_is_rejected_before_execution(self) -> None:
        campaign = load(GRID_CONVERGENCE_CAMPAIGN_PATH)
        campaign["experiments"][0][
            "single_flight_frontend_grid_profile_id"
        ] = "missing_grid_profile"
        with tempfile.TemporaryDirectory(dir=CONFIG_ROOT) as directory:
            root = Path(directory)
            campaign_path = root / "campaign.json"
            write_json(campaign_path, campaign)
            with self.assertRaisesRegex(
                ContractError, "grid profile must resolve exactly once"
            ):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=campaign_path,
                    experiment_id="octupole_frontend_grid_020_n1000",
                    resolved_output=root / "resolved.json",
                    plan_output=root / "plan.json",
                )

    def test_pulse_offset_is_a_governed_campaign_value_with_zero_default(self) -> None:
        campaign = load(GRID_CONVERGENCE_CAMPAIGN_PATH)
        experiment = campaign["experiments"][0]
        source_run = (
            REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics/runs"
            / experiment["single_flight_design_reference"]["run_id"]
        )
        if not source_run.is_dir():
            self.skipTest("local single-flight design reference is unavailable")
        experiment["single_flight_pulse_offset_rf_periods"] = -0.125
        validate_schema(
            campaign, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        with tempfile.TemporaryDirectory(dir=CONFIG_ROOT) as config_directory, \
                tempfile.TemporaryDirectory(
                    dir=REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics"
                ) as output_directory:
            campaign_path = Path(config_directory) / "campaign.json"
            write_json(campaign_path, campaign)
            output = Path(output_directory)
            prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=campaign_path,
                experiment_id=experiment["experiment_id"],
                resolved_output=output / "resolved.json",
                plan_output=output / "plan.json",
            )
            schedule = load(output / "resolved_single_flight_pulse_schedule.json")
            self.assertEqual(schedule["pulse_offset_rf_periods"], -0.125)
            self.assertLess(
                schedule["derived_pulse_time_us"],
                schedule["base_derived_pulse_time_us"],
            )
            self.assertAlmostEqual(
                schedule["base_predicted_centroid_error_x_mm"], 0.0, places=9
            )
            self.assertNotEqual(schedule["predicted_centroid_error_x_mm"], 0.0)

    def test_single_flight_design_overrides_are_optional_contract_data(self) -> None:
        default_campaign = load(SINGLE_FLIGHT_CAMPAIGN_PATH)
        self.assertNotIn(
            "single_flight_design_overrides", default_campaign["experiments"][0]
        )
        candidate = load(Z_ACCEPTANCE_CAMPAIGN_PATH)
        validate_schema(
            candidate, "rf_multipole_oatof_experiment_campaign.schema.json"
        )
        overrides = candidate["experiments"][0]["single_flight_design_overrides"]
        self.assertEqual(
            [item["variable"] for item in overrides],
            [
                "accelerator_stage1_length",
                "accelerator_stage2_length",
                "accelerator_grid1_voltage",
            ],
        )

    def test_campaign_rows_select_registered_runtime_bound_profiles(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        profiles = load(PROFILE_REGISTRY)["profiles"]
        profile_by_id = {
            profile["connection_profile_id"]: profile for profile in profiles
        }
        self.assertEqual(len(profile_by_id), len(profiles))
        for experiment in campaign["experiments"]:
            profile = profile_by_id[experiment["connection_profile_id"]]
            self.assertEqual(
                profile["upstream"]["port_binding"],
                "source_run_resolved_design",
            )
            self.assertNotIn("port_contract", profile["upstream"])

    def test_campaign_and_experiment_identities_are_unique(self) -> None:
        campaign = load(CAMPAIGN_PATH)
        experiment_ids = [row["experiment_id"] for row in campaign["experiments"]]
        sequences = [row["sequence"] for row in campaign["experiments"]]
        run_ids = [row["run_id"] for row in campaign["experiments"]]
        self.assertEqual(len(experiment_ids), len(set(experiment_ids)))
        self.assertEqual(len(sequences), len(set(sequences)))
        self.assertEqual(len(run_ids), len(set(run_ids)))

    def test_n1000_campaign_freezes_population_specific_handoff_contract(self) -> None:
        campaign = load(N1000_CAMPAIGN_PATH)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        source = campaign["experiments"][0]["source"]
        record = source["handoff_publication_contract"]
        contract = load(REPO_ROOT / record["path"])
        self.assertEqual(source["launched_particle_count"], 1000)
        self.assertEqual(
            contract["population"]["expected_source_particle_count"],
            source["launched_particle_count"],
        )
        self.assertEqual(
            contract["canonical_state"]["source_component_id"],
            "rf_octupole_ion_optics",
        )

    def test_single_flight_can_reuse_population_with_a_frozen_design_reference(self) -> None:
        campaign = load(TERMINAL_DESIGN_REFERENCE_CAMPAIGN_PATH)
        validate_schema(campaign, "rf_multipole_oatof_experiment_campaign.schema.json")
        experiment = campaign["experiments"][0]
        self.assertEqual(experiment["source"]["launched_particle_count"], 1000)
        self.assertEqual(
            experiment["single_flight_design_reference"]["launched_particle_count"],
            100,
        )
        reference_run = (
            REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics/runs"
            / experiment["single_flight_design_reference"]["run_id"]
        )
        if not reference_run.is_dir():
            self.skipTest("local corrected terminal design reference is unavailable")
        with tempfile.TemporaryDirectory(
            dir=REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics"
        ) as directory:
            output = Path(directory)
            _, plan = prepare_family_source_closure(
                repo_root=REPO_ROOT,
                profile_registry_path=PROFILE_REGISTRY,
                adapter_registry_path=ADAPTER_REGISTRY,
                campaign_path=TERMINAL_DESIGN_REFERENCE_CAMPAIGN_PATH,
                experiment_id=experiment["experiment_id"],
                resolved_output=output / "resolved.json",
                plan_output=output / "plan.json",
            )
            design = load(plan.with_name("upstream_resolved_design.json"))
            source_contract = load(plan.with_name("resolved_source_contract.json"))
            sleeve = design["axial_dc"]["entrance_reference_sleeve"]
            self.assertEqual(sleeve["inner_radius_mm"], 0.75)
            self.assertEqual(sleeve["downstream_face_z_mm"], 0.0)
            self.assertEqual(
                source_contract["design_reference"]["run_id"],
                experiment["single_flight_design_reference"]["run_id"],
            )

    def test_superseded_non_grounded_single_flight_source_is_rejected(self) -> None:
        source_run = (
            REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics/runs"
            / "20260804_112000__sim__simion__oct-segmented-aperture050__n1000"
        )
        if not source_run.is_dir():
            self.skipTest("local N=1000 source artifact is unavailable")
        with tempfile.TemporaryDirectory(
            dir=REPO_ROOT.parent / "artifacts/projects/rf_octupole_ion_optics"
        ) as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ContractError, "0.0 was expected"):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=SINGLE_FLIGHT_CAMPAIGN_PATH,
                    experiment_id="octupole_segmented_aperture100_simion_single_flight",
                    resolved_output=output / "resolved.json",
                    plan_output=output / "plan.json",
                )

    def test_prepare_rejects_campaign_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT.parent) as directory:
            outside = Path(directory)
            campaign = outside / "campaign.json"
            write_json(campaign, load(CAMPAIGN_PATH))
            with self.assertRaisesRegex(ContractError, "repository-managed"):
                prepare_family_source_closure(
                    repo_root=REPO_ROOT,
                    profile_registry_path=PROFILE_REGISTRY,
                    adapter_registry_path=ADAPTER_REGISTRY,
                    campaign_path=campaign,
                    experiment_id="unused",
                    resolved_output=outside / "resolved.json",
                    plan_output=outside / "plan.json",
                )

    def test_parent_publisher_requires_campaign_identity(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT.parent) as directory:
            workspace = Path(directory)
            run_id = "20260803_220000__sim__cross__campaign-parent__n100"
            run_dir = workspace / run_id
            run_dir.mkdir()
            receipt = run_dir / "receipt.json"
            resolved = run_dir / "resolved.json"
            plan = run_dir / "plan.json"
            budget = run_dir / "budget.json"
            write_json(
                receipt,
                {
                    "role": "integration_family_source_closure_execution_receipt",
                    "integration_run_id": run_id,
                    "execution_status": "completed_pending_paired_analysis",
                },
            )
            write_json(resolved, {"integration_id": INTEGRATION_ID})
            write_json(plan, {"integration_id": INTEGRATION_ID})
            write_json(budget, {})
            with self.assertRaisesRegex(ContractError, "campaign identity is missing"):
                publish_family_source_closure_run(
                    repo_root=REPO_ROOT,
                    workspace_root=workspace,
                    integration_run_dir=run_dir,
                    receipt_path=receipt,
                    resolved_path=resolved,
                    plan_path=plan,
                    budget_path=budget,
                )


if __name__ == "__main__":
    unittest.main()

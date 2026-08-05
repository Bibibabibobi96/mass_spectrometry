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
PROFILE_REGISTRY = CONFIG_ROOT / "connection_profiles.json"
ADAPTER_REGISTRY = CONFIG_ROOT / "execution_adapter_profiles.json"


def load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class FamilySourceClosureWorkflowTests(unittest.TestCase):
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

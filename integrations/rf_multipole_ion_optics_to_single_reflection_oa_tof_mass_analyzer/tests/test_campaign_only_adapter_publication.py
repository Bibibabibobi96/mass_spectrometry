"""Tests for the campaign-only RF-multipole to oaTOF execution tail."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from common.contracts.file_identity import file_sha256
from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run import (
    INTEGRATION_ID,
    STAGES,
    publish_family_source_closure_run,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER_PATH = (
    REPO_ROOT
    / "integrations"
    / INTEGRATION_ID
    / "workflows"
    / "family_source_closure"
    / "adapter.ps1"
)
WORKFLOW_ROOT = ADAPTER_PATH.parent


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def record(path: Path) -> dict[str, object]:
    return {
        "path": str(path.resolve()),
        "exists": True,
        "bytes": path.stat().st_size,
        "sha256": file_sha256(path),
    }


class CampaignOnlyAdapterPublicationTests(unittest.TestCase):
    def test_public_entry_and_prepare_are_campaign_only(self) -> None:
        execute_source = (WORKFLOW_ROOT / "execute.ps1").read_text(
            encoding="utf-8-sig"
        )
        prepare_source = (WORKFLOW_ROOT / "prepare.py").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn("[Parameter(Mandatory)][string]$Campaign", execute_source)
        self.assertIn("[Parameter(Mandatory)][string]$ExperimentId", execute_source)
        self.assertIn("[string]$OutputDirectory = ''", execute_source)
        self.assertIn("$campaignRunId = [string]$experimentRows[0].run_id", execute_source)
        self.assertIn("Select exactly one of ValidateOnly", execute_source)
        self.assertIn("OutputDirectory is accepted only for PrepareOnly", execute_source)
        self.assertIn("validation_tmp", execute_source)
        self.assertIn("Remove-Item -LiteralPath $outputRoot -Recurse -Force", execute_source)
        for obsolete in (
            "[string]$RunId",
            "SourceRevisionId",
            "ConnectionProfileId",
            "SourceBranchId",
            "preregistration",
            "revision-registry",
        ):
            self.assertNotIn(obsolete, execute_source)
        self.assertIn('shutil.copyfile(evidence["resolved_design_path"]', prepare_source)
        self.assertIn('resolved_upstream.pop("port_binding", None)', prepare_source)
        self.assertIn(
            '"upstream_resolved_design_filename=upstream_resolved_design.json"',
            prepare_source,
        )

    def test_adapter_has_one_campaign_argument_contract(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8-sig")
        required = (
            "campaign_path",
            "campaign_sha256",
            "campaign_id",
            "experiment_id",
            "experiment_row_sha256",
            "resolved_source_contract_filename",
            "upstream_resolved_design_filename",
        )
        for name in required:
            self.assertIn(f"'{name}'", source)
        for obsolete in (
            "campaignMode",
            "sourceRevision",
            "source_revision",
            "preregistration",
        ):
            self.assertNotIn(obsolete, source)
        self.assertIn("json.dumps(rows[0], ensure_ascii=False, sort_keys=True", source)
        self.assertIn("$stageParticleCount = [int]$budget.launched_particle_count", source)

    def test_parent_publication_is_n_neutral_and_preserves_both_counts(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT.parent) as directory:
            workspace = Path(directory)
            fixture_repo = workspace / "simulation_repo"
            fixture_campaign = (
                fixture_repo
                / "integrations"
                / INTEGRATION_ID
                / "config"
                / "experiment_campaign.json"
            )
            fixture_campaign.parent.mkdir(parents=True)
            write_json(fixture_campaign, {"role": "campaign_fixture"})
            run_id = "20260803_220000__sim__cross__campaign-parent__n1000"
            run_dir = (
                workspace
                / "artifacts"
                / "projects"
                / INTEGRATION_ID
                / "runs"
                / run_id
            )
            run_dir.mkdir(parents=True)
            profile_id = (
                "rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm"
            )
            project_id = "rf_octupole_ion_optics"
            launched_count = 1000
            selected_count = 41
            source_identity = {
                "source_branch_id": "simion",
                "solver_id": "simion",
                "run_id": "source_run",
                "project_id": project_id,
                "manifest_sha256": "A" * 64,
                "event_sha256": "B" * 64,
                "particle_source_sha256": "C" * 64,
                "metadata_sha256": "D" * 64,
            }
            runtime = run_dir / "runtime.json"
            resolved_source_contract = run_dir / "resolved_source_contract.json"
            upstream_resolved_design = run_dir / "upstream_resolved_design.json"
            resolved = run_dir / "resolved.json"
            plan = run_dir / "plan.json"
            budget = run_dir / "budget.json"
            receipt = run_dir / "receipt.json"
            write_json(runtime, {"role": "runtime_fixture"})
            write_json(resolved_source_contract, {"role": "source_fixture"})
            write_json(upstream_resolved_design, {"role": "design_fixture"})
            write_json(
                resolved,
                {
                    "integration_id": INTEGRATION_ID,
                    "selection": {
                        "connection_profile_id": profile_id,
                        "upstream_project_id": project_id,
                    },
                },
            )
            write_json(
                plan,
                {
                    "integration_id": INTEGRATION_ID,
                    "selection": {"connection_profile_id": profile_id},
                },
            )
            campaign_identity = {
                "campaign_id": "campaign_identity_test",
                "experiment_id": "octupole_segmented_test",
                "experiment_row_sha256": "E" * 64,
                "launched_particle_count": launched_count,
                "particle_count": selected_count,
                "policy_id": "compact_serial_commercial_solvers",
                "retention_class": "compact",
            }
            write_json(
                budget,
                {
                    "connection_profile_id": profile_id,
                    "source_identity": source_identity,
                    **campaign_identity,
                },
            )
            stage_ids = {
                phase: run_id[:15] + contract["run_stem"] + str(launched_count)
                for phase, contract in STAGES.items()
            }
            runtime_sha = file_sha256(runtime)
            write_json(
                receipt,
                {
                    "role": "integration_family_source_closure_execution_receipt",
                    "integration_run_id": run_id,
                    "execution_status": "completed_pending_paired_analysis",
                    "connection_profile_id": profile_id,
                    "campaign_path": (
                        "integrations/"
                        + INTEGRATION_ID
                        + "/config/experiment_campaign.json"
                    ),
                    "campaign_sha256": file_sha256(
                        fixture_campaign
                    ),
                    "resolved_source_contract_filename": (
                        resolved_source_contract.name
                    ),
                    "resolved_source_contract_sha256": file_sha256(
                        resolved_source_contract
                    ),
                    "upstream_resolved_design_filename": (
                        upstream_resolved_design.name
                    ),
                    "upstream_resolved_design_sha256": file_sha256(
                        upstream_resolved_design
                    ),
                    "source_branch_id": "simion",
                    "source_identity": source_identity,
                    "resolved_connection_sha256": file_sha256(resolved),
                    "stage_run_ids": stage_ids,
                    "stage_runtime_binding_sha256s": {
                        phase: runtime_sha for phase in STAGES
                    },
                    **campaign_identity,
                },
            )
            stage_root = (
                workspace / "artifacts" / "projects" / project_id / "runs"
            )
            for phase, contract in STAGES.items():
                stage = stage_root / stage_ids[phase]
                stage.mkdir(parents=True)
                source_field = (
                    "source_particle_identity"
                    if phase == "pre_pulse_interface_transport"
                    else "upstream_source_identity"
                )
                stage_config = {
                    "schema_version": 2,
                    "run_id": stage.name,
                    "project": project_id,
                    "mode": contract["mode"],
                    "parameters": {
                        "connection_profile_id": profile_id,
                        "source_branch_id": "simion",
                    },
                    "inputs": {
                        "runtime_binding": str(runtime.resolve()),
                        "resolved_connection": str(resolved.resolve()),
                    },
                    source_field: source_identity,
                }
                write_json(stage / "run_config.json", stage_config)
                write_json(
                    stage / "run_manifest.json",
                    {
                        "role": "simulation_run_manifest",
                        "run_id": stage.name,
                        "project": project_id,
                        "mode": contract["mode"],
                        "status": "success",
                        "run_config": record(stage / "run_config.json"),
                    },
                )
                if phase == "analyzer_transport":
                    write_json(stage / "summary.json", {"census": {}})

            with patch(
                "integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.workflows.family_source_closure.publish_run.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ):
                publish_family_source_closure_run(
                    repo_root=fixture_repo,
                    workspace_root=workspace,
                    integration_run_dir=run_dir,
                    receipt_path=receipt,
                    resolved_path=resolved,
                    plan_path=plan,
                    budget_path=budget,
                )

            parent_config = json.loads(
                (run_dir / "run_config.json").read_text(encoding="utf-8")
            )
            parent_summary = json.loads(
                (run_dir / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(parent_config["mode"], "multipole_family_source_closure")
            self.assertEqual(parent_config["launched_particle_count"], 1000)
            self.assertEqual(parent_config["particle_count"], 41)
            self.assertEqual(parent_summary["launched_particle_count"], 1000)
            self.assertEqual(parent_summary["particle_count"], 41)
            self.assertNotIn("source_revision_id", parent_config)
            self.assertNotIn("source_revision_id", parent_summary)


if __name__ == "__main__":
    unittest.main()

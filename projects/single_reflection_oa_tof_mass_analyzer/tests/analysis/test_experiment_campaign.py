from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from common.contracts.machine_contracts import load_json, sha256
from common.contracts.artifact_naming import validate_task_id
from projects.single_reflection_oa_tof_mass_analyzer.analysis import (
    experiment_campaign as campaign_module,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.experiment_campaign import (
    DEFAULT_CAMPAIGN,
    PROJECT_ROOT,
    campaign_status,
    execute_campaign,
    preflight_campaign,
    validate_campaign,
)


@contextmanager
def authorized_campaign_fixture():
    with tempfile.TemporaryDirectory(
        prefix=".experiment_campaign_test_", dir=PROJECT_ROOT / "config"
    ) as root:
        root_path = Path(root)
        request = load_json(
            PROJECT_ROOT
            / "config"
            / "requests"
            / "reflectron_midgrid_structural_campaign.json"
        )
        request["status"] = "approved"
        request["approval"] = {
            "approved_by": "test_owner",
            "approved_on": "2026-07-31",
        }
        request_path = root_path / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")

        science = load_json(PROJECT_ROOT / "config" / "modes" / "design_candidate.json")
        science["current_validated_extent"]["nonzero_design_variables"] = [
            "reflectron_midgrid_voltage"
        ]
        science_path = root_path / "design_candidate.json"
        science_path.write_text(json.dumps(science), encoding="utf-8")

        campaign = load_json(DEFAULT_CAMPAIGN)
        campaign["campaign_id"] = "authorized_midgrid_fixture"
        campaign["status"] = "authorized"
        campaign["execution_authorized"] = True
        campaign["preregistered_before_run"] = True
        campaign["base_request"] = {
            "path": request_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256(request_path),
        }
        campaign["authorities"]["science_profile"] = {
            "path": science_path.relative_to(PROJECT_ROOT).as_posix(),
            "sha256": sha256(science_path),
        }
        campaign_path = root_path / "campaign.json"
        campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
        yield campaign_path, campaign


class ExperimentCampaignTests(unittest.TestCase):
    def test_public_entry_runs_as_repository_module_without_path_injection(self):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                (
                    "projects.single_reflection_oa_tof_mass_analyzer."
                    "workflows.experiment_campaign.run_campaign"
                ),
                "--status",
            ],
            cwd=PROJECT_ROOT.parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "authorized")

    def test_checked_in_campaign_is_authorized_and_preflights(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root = Path(root)
            status = campaign_status(artifact_root=artifact_root)
            self.assertEqual(status["status"], "authorized")
            self.assertTrue(status["execution_authorized"])
            self.assertEqual(status["authorization_blockers"], [])
            self.assertFalse(status["mass_spectrum_internal_species_are_campaign_rows"])
            self.assertEqual(
                [item["status"] for item in status["experiments"]],
                ["NOT_STARTED", "NOT_STARTED"],
            )
            prepared = preflight_campaign(
                DEFAULT_CAMPAIGN,
                "20260802_122900__test__cross__campaign-preflight",
                run_all=True,
                artifact_root=artifact_root,
            )
            self.assertEqual(len(prepared["rows"]), 2)
            validate_task_id(prepared["scratch"].name)

    def test_campaign_value_outside_narrow_envelope_is_rejected(self):
        with authorized_campaign_fixture() as (campaign_path, campaign):
            campaign["experiments"][1]["variation_values"][0]["value"] = 1599.0
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid value"):
                validate_campaign(campaign_path, require_authorized=True)

    def test_profile_identity_is_resolved_from_its_frozen_authority(self):
        with authorized_campaign_fixture() as (campaign_path, campaign):
            campaign["execution_profile"]["profile_id"] = "missing_profile"
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "execution profile must resolve exactly once"
            ):
                validate_campaign(campaign_path, require_authorized=True)

    def test_status_requires_complete_bound_terminal_child_evidence(self):
        with authorized_campaign_fixture() as (campaign_path, campaign):
            with tempfile.TemporaryDirectory() as root:
                artifact_root = Path(root)
                experiment = campaign["experiments"][0]
                run_root = artifact_root / "runs" / experiment["authorized_run_id"]
                run_root.mkdir(parents=True)
                status = campaign_status(
                    campaign_path, artifact_root=artifact_root
                )
                self.assertEqual(
                    status["experiments"][0]["status"], "FAILED_OR_INVALID"
                )
                binding = {
                    "campaign_id": campaign["campaign_id"],
                    "campaign_sha256": sha256(campaign_path),
                    "experiment_id": experiment["experiment_id"],
                }
                (run_root / "run_config.json").write_text(
                    json.dumps(
                        {
                            "run_id": experiment["authorized_run_id"],
                            "project": "single_reflection_oa_tof_mass_analyzer",
                            "campaign_binding": binding,
                        }
                    ),
                    encoding="utf-8",
                )
                (run_root / "summary.json").write_text(
                    json.dumps({"status": "success"}), encoding="utf-8"
                )
                (run_root / "run_manifest.json").write_text(
                    json.dumps(
                        {
                            "run_id": experiment["authorized_run_id"],
                            "project": "single_reflection_oa_tof_mass_analyzer",
                            "status": "success",
                            "lifecycle_state": "terminal",
                            "campaign_binding": binding,
                        }
                    ),
                    encoding="utf-8",
                )
                status = campaign_status(
                    campaign_path, artifact_root=artifact_root
                )
                self.assertEqual(status["experiments"][0]["status"], "SUCCESS")
                self.assertTrue(status["experiments"][0]["ended"])
                self.assertEqual(status["experiments"][1]["status"], "NOT_STARTED")

    def test_authorized_fixture_preflights_every_row_before_launch(self):
        with authorized_campaign_fixture() as (campaign_path, campaign):
            with tempfile.TemporaryDirectory() as root:
                prepared = preflight_campaign(
                    campaign_path,
                    "20260731_231100__test__cross__campaign-preflight",
                    run_all=True,
                    artifact_root=Path(root),
                )
                self.assertEqual(
                    [item["experiment"]["experiment_id"] for item in prepared["rows"]],
                    [item["experiment_id"] for item in campaign["experiments"]],
                )
                for item in prepared["rows"]:
                    self.assertTrue(item["request_path"].is_file())
                    self.assertTrue(item["proposal_path"].is_file())

    def test_single_selection_still_compiles_the_entire_table_before_launch(self):
        with authorized_campaign_fixture() as (campaign_path, campaign):
            with tempfile.TemporaryDirectory() as root:
                with mock.patch.object(
                    campaign_module,
                    "compile_proposal",
                    wraps=campaign_module.compile_proposal,
                ) as compiler:
                    prepared = preflight_campaign(
                        campaign_path,
                        "20260731_231150__test__cross__campaign-single-preflight",
                        experiment_id=campaign["experiments"][0]["experiment_id"],
                        artifact_root=Path(root),
                    )
                self.assertEqual(compiler.call_count, len(campaign["experiments"]))
                self.assertEqual(len(prepared["rows"]), 1)

    def test_bad_late_row_prevents_every_candidate_launch(self):
        with authorized_campaign_fixture() as (campaign_path, campaign):
            bad = copy.deepcopy(campaign)
            bad["experiments"][1]["variation_values"][0]["value"] = 20000.0
            campaign_path.write_text(json.dumps(bad), encoding="utf-8")
            executor = mock.Mock()
            with tempfile.TemporaryDirectory() as root:
                with self.assertRaisesRegex(ValueError, "invalid value"):
                    execute_campaign(
                        campaign_path,
                        "20260731_231200__test__cross__campaign-bad-row",
                        run_all=True,
                        artifact_root=Path(root),
                        candidate_executor=executor,
                    )
            executor.assert_not_called()

    def test_all_is_serial_and_stops_after_first_failure_without_retry(self):
        with authorized_campaign_fixture() as (campaign_path, campaign):
            calls: list[str] = []

            def failing_executor(_request, run_id, **kwargs):
                calls.append(run_id)
                raise RuntimeError("fixture failure")

            with tempfile.TemporaryDirectory() as root:
                run_root, summary = execute_campaign(
                    campaign_path,
                    "20260731_231300__test__cross__campaign-serial",
                    run_all=True,
                    artifact_root=Path(root),
                    candidate_executor=failing_executor,
                )
                self.assertEqual(calls, [campaign["experiments"][0]["authorized_run_id"]])
                self.assertEqual(summary["status"], "failed")
                self.assertFalse(
                    any((Path(root) / "scratch").glob("*campaign-preflight*"))
                )
                self.assertEqual(
                    [item["status"] for item in summary["rows"]],
                    ["failed", "not_started_due_to_prior_failure"],
                )
                config = load_json(run_root / "run_config.json")
                manifest = load_json(run_root / "run_manifest.json")
                self.assertEqual(config["schema_version"], 2)
                self.assertEqual(manifest["schema_version"], 2)
                self.assertEqual(manifest["artifact_retention"]["class"], "compact")
                self.assertEqual(manifest["lifecycle_state"], "terminal")
                self.assertEqual(
                    config["parameters"]["commercial_solver_parallelism"], 1
                )
                self.assertEqual(config["parameters"]["automatic_retry_count"], 0)

    def test_parameter_roles_and_named_profiles_cannot_drift_by_row(self):
        with authorized_campaign_fixture() as (campaign_path, campaign):
            invalid = copy.deepcopy(campaign)
            invalid["experiments"][0]["particle_source_seed"] = 7
            campaign_path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(Exception):
                validate_campaign(campaign_path)

    def test_mass_spectrum_points_remain_one_joint_condition(self):
        mode = load_json(PROJECT_ROOT / "config" / "modes" / "mass_spectrum.json")
        profile = next(
            item
            for item in load_json(PROJECT_ROOT / "config" / "execution_profiles.json")[
                "profiles"
            ]
            if item["profile_id"] == "mass_spectrum_candidate"
        )
        self.assertEqual(len(mode["species"]), 5)
        self.assertTrue(mode["particle_source"]["paired_initial_conditions_across_species"])
        self.assertEqual(len([s for s in profile["steps"] if s["kind"] == "run"]), 1)
        self.assertEqual(profile["supported_design_variables"], [])


if __name__ == "__main__":
    unittest.main()

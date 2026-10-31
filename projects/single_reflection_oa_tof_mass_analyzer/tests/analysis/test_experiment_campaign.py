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
        campaign["execution_profile"]["authority"]["sha256"] = sha256(
            PROJECT_ROOT/campaign["execution_profile"]["authority"]["path"])
        campaign_path = root_path / "campaign.json"
        campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
        yield campaign_path, campaign


class ExperimentCampaignTests(unittest.TestCase):
    def test_external_campaign_public_status_cli_keeps_request_and_authority(self):
        repo = PROJECT_ROOT.parents[1]
        with authorized_campaign_fixture() as (inside, _), tempfile.TemporaryDirectory() as directory:
            outside = Path(directory) / "campaign.json"
            payload = inside.read_bytes()
            outside.write_bytes(payload)
            statuses = []
            for path in (inside, outside):
                actual = subprocess.run([sys.executable, "-B", "-m",
                    "projects.single_reflection_oa_tof_mass_analyzer.workflows.experiment_campaign.run_campaign",
                    "--campaign", str(path), "--status"], cwd=repo, capture_output=True,
                    text=True, encoding="utf-8", timeout=30)
                self.assertEqual(actual.returncode, 0, actual.stdout + actual.stderr)
                statuses.append(json.loads(actual.stdout))
                self.assertEqual(path.read_bytes(), payload)
            self.assertEqual(statuses[0], statuses[1])
            outside.write_text("{}", encoding="utf-8")
            rejected = subprocess.run([sys.executable, "-B", "-m",
                "projects.single_reflection_oa_tof_mass_analyzer.workflows.experiment_campaign.run_campaign",
                "--campaign", str(outside), "--status"], cwd=repo, capture_output=True,
                text=True, encoding="utf-8", timeout=30)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(inside.read_bytes(), payload)


    def test_explicit_external_campaign_relocates_without_changing_rows_or_authority(self):
        import shutil
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owner = root/"owner"
            document = load_json(DEFAULT_CAMPAIGN)
            document.update(campaign_id="external_request_fixture", status="authorized",
                            execution_authorized=True, preregistered_before_run=True)
            records = [document["base_request"], document["execution_profile"]["authority"],
                       *document["authorities"].values()]
            for record in records:
                destination = owner/record["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PROJECT_ROOT/record["path"], destination)
                if record is document["base_request"]:
                    request = load_json(destination)
                    request.update(status="approved", approval=dict(approved_by="fixture", approved_on="2026-10-30"))
                    destination.write_text(json.dumps(request), encoding="utf-8")
                if record is document["authorities"]["science_profile"]:
                    science = load_json(destination)
                    science["current_validated_extent"]["nonzero_design_variables"] = ["reflectron_midgrid_voltage"]
                    destination.write_text(json.dumps(science), encoding="utf-8")
                record["sha256"] = sha256(destination)
            payload = json.dumps(document).encode("utf-8")
            paths = [root/"case/campaign.json", root/"data/campaign.json"]
            for path in paths:
                path.parent.mkdir()
                path.write_bytes(payload)
            with mock.patch.object(campaign_module, "PROJECT_ROOT", owner):
                first, second = [validate_campaign(path, require_authorized=True) for path in paths]
                for key in ("document", "profile", "authorities", "axes", "request", "sha256"):
                    self.assertEqual(first[key], second[key])
                plans = [preflight_campaign(path, "20261030_234500__test__cross__external-campaign",
                            run_all=True, artifact_root=root/("artifact"+str(index)))
                         for index,path in enumerate(paths)]
                self.assertEqual([row["experiment"] for row in plans[0]["rows"]],
                                 [row["experiment"] for row in plans[1]["rows"]])
                for left,right in zip(plans[0]["rows"], plans[1]["rows"]):
                    # Provenance includes each output root; the physical request
                    # and compiler-governed variations are location-independent.
                    self.assertEqual(left["request_path"].read_bytes(), right["request_path"].read_bytes())
                    self.assertEqual(load_json(left["proposal_path"])["values"], load_json(right["proposal_path"])["values"])
                self.assertTrue(all(path.read_bytes()==payload for path in paths))
                paths[1].write_text("{}", encoding="utf-8")
                self.assertEqual(second["source_bytes"], payload)
                paths[0].write_text("{}", encoding="utf-8")
                observed = []
                def no_native_executor(_request, _run_id, **kwargs):
                    observed.append(kwargs["campaign_table"].read_bytes())
                    raise RuntimeError("software fixture stops before native")
                with mock.patch.object(campaign_module, "preflight_campaign", return_value=plans[0]):
                    run, summary = execute_campaign(paths[0], plans[0]["campaign_run_id"], run_all=True,
                        artifact_root=plans[0]["artifact_root"], candidate_executor=no_native_executor)
                self.assertEqual(observed, [payload])
                self.assertEqual((run/"inputs/experiment_campaign.json").read_bytes(), payload)
                self.assertEqual(summary["status"], "failed")
                self.assertEqual(paths[0].read_text(encoding="utf-8"), "{}")
                document["preregistered_before_run"] = False
                paths[1].write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "not preregistered"):
                    validate_campaign(paths[1], require_authorized=True)
                document["base_request"]["path"] = "../external_code.py"
                paths[1].write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "project-relative"):
                    validate_campaign(paths[1])

    def test_retired_status_reports_changed_authority_without_reauthorizing_history(self):
        before = DEFAULT_CAMPAIGN.read_bytes()
        document = json.loads(before)
        document["execution_profile"]["authority"]["sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            stale = Path(directory) / "stale_retired_campaign.json"
            stale.write_text(json.dumps(document), encoding="utf-8")
            stale_before = stale.read_bytes()
            status = campaign_status(stale)
            self.assertEqual(status["status"], "retired")
            self.assertFalse(status["execution_authorized"])
            self.assertEqual(status["science_status"], "not_evaluated")
            self.assertTrue(any(row["authority"] == "execution_profile" for row in status["authority_diagnostics"]))
            self.assertEqual(stale.read_bytes(), stale_before)
            with self.assertRaisesRegex(ValueError, "status is retired"):
                validate_campaign(stale, require_authorized=True)
        self.assertEqual(DEFAULT_CAMPAIGN.read_bytes(), before)

    def test_authority_refresh_uses_current_profile_without_reauthorizing_campaign(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis import sync_geometry_contract as sync
        before = DEFAULT_CAMPAIGN.read_bytes()
        original = json.loads(before)
        rendered = sync.render_authority_document(DEFAULT_CAMPAIGN, sync.render_optimization_envelope())
        refreshed = json.loads(rendered)
        self.assertEqual(refreshed["execution_profile"]["authority"]["sha256"],
                         sha256(PROJECT_ROOT / "config/execution_profiles.json"))
        self.assertEqual({k: v for k, v in refreshed.items() if k != "execution_profile"},
                         {k: v for k, v in original.items() if k != "execution_profile"})
        self.assertEqual(refreshed["execution_profile"]["profile_id"], original["execution_profile"]["profile_id"])
        self.assertEqual(refreshed["execution_profile"]["capability_id"], original["execution_profile"]["capability_id"])
        self.assertEqual(refreshed["status"], "retired")
        self.assertFalse(refreshed["execution_authorized"])
        self.assertEqual(rendered.encode("utf-8"), before, "checked-in author binding must be current and idempotent")
        self.assertEqual(DEFAULT_CAMPAIGN.read_bytes(), before)
        changed = copy.deepcopy(original)
        changed["execution_profile"]["authority"]["path"] = "config/unexpected_profiles.json"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected execution profile authority path"):
                sync.render_authority_document(path, sync.render_optimization_envelope())


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
        self.assertEqual(json.loads(completed.stdout)["status"], "retired")

    def test_checked_in_campaign_is_retired_after_its_completed_runs(self):
        with tempfile.TemporaryDirectory() as root:
            artifact_root = Path(root)
            status = campaign_status(artifact_root=artifact_root)
            self.assertEqual(status["status"], "retired")
            self.assertFalse(status["execution_authorized"])
            self.assertIn("campaign status is retired", status["authorization_blockers"])
            self.assertFalse(status["mass_spectrum_internal_species_are_campaign_rows"])
            self.assertEqual(
                [item["status"] for item in status["experiments"]],
                ["NOT_STARTED", "NOT_STARTED"],
            )
            with self.assertRaisesRegex(ValueError, "not authorized"):
                preflight_campaign(
                    DEFAULT_CAMPAIGN,
                    "20260802_122900__test__cross__campaign-preflight",
                    run_all=True,
                    artifact_root=artifact_root,
                )

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

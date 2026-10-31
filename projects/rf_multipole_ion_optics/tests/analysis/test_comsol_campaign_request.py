"""Public campaign resolver/budget and real CLI parameter transport; no solver."""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest
from common.contracts.machine_contracts import validate_schema
from projects.rf_multipole_ion_optics.runtime import runtime_profile as runtime
from projects.rf_multipole_ion_optics.runtime import design_profile as design_provider
from projects.rf_multipole_ion_optics.runtime.resource_budget import (
    validate_pilot_budget,
)

REPO = Path(design_provider.__file__).resolve().parents[3]
PROJECT = Path(runtime.__file__).resolve().parents[1]
SCHEMA = (
    Path(__file__).resolve().parents[4]
    / "common/contracts/schemas/multipole_transport_experiment_campaign.schema.json"
)


def request():
    return dict(
        schema_version=7,
        role="multipole_transport_experiment_campaign",
        family_id="rf_multipole_ion_optics",
        campaign_id="comsol_development_fixture",
        preregistered_before_run=True,
        claim_limit="Fixture only, no commercial launch",
        experiments=[
            dict(
                experiment_id="octupole_goal_n100_8us",
                project_id="rf_multipole_ion_optics",
                authorized_run_id="20261030_235900__test__comsol__fixture",
                solver="comsol",
                stop_stage="transport",
                design_profile_id="octupole_no_acceleration_full_length",
                particle_source_profile_id="octupole_continuous_axial_volume_snapshot_v1_n100",
                comsol_solver_numerics_profile_id="core_flow_development_coarse_8us",
                simion_solver_numerics=dict(
                    kind="profile", profile_id="octupole_baseline_finite_3d"
                ),
                retention_class="solver_review",
                resource_authorization=dict(
                    authorized=True,
                    limits=dict(
                        wall_clock_seconds_by_solver=dict(comsol=1200, simion=720),
                        transient_run_directory_bytes=2147483648,
                        process_tree_working_set_bytes=17179869184,
                        minimum_system_available_memory_bytes=8589934592,
                        compact_final_retained_bytes=26214400,
                        automatic_retry_count=0,
                    ),
                    full_matrix_authorization=dict(
                        authorized=False, reason="No matrix"
                    ),
                    budget_exhaustion_result="INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED",
                ),
                claim_limit="No transport/scientific qualification",
            )
        ],
    )


class ComsolCampaignRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def resolve(self, data):
        path = self.root / "request.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        resolved = runtime.resolve_runtime_selection(
            REPO,
            "rf_multipole_ion_optics",
            campaign_path=path,
            experiment_id=data["experiments"][0]["experiment_id"],
        )
        return (path, resolved)

    def budget(self, path, resolved, **changes):
        args = dict(
            repo_root=REPO,
            budget_path=path,
            project_id="rf_multipole_ion_optics",
            solver="comsol",
            runtime_profile_id=resolved["runtime_profile_id"],
            design_profile_id=resolved["design_profile_id"],
            particle_source_path=Path(resolved["particle_source"]["path"]),
            retention_class="solver_review",
            run_id=resolved["engineering_budget"]["inline_contract"][
                "pilot_authorization"
            ]["scope"]["authorized_run_id"],
            resolved_runtime=resolved,
        )
        args.update(changes)
        return validate_pilot_budget(**args)

    def test_real_resolver_budget_new_explicit_scope(self):
        path, resolved = self.resolve(request())
        budget = self.budget(path, resolved)
        self.assertEqual(
            resolved["engineering_budget"]["inline_contract"]["pilot_authorization"][
                "scope"
            ]["allowed_solvers"],
            ["comsol"],
        )
        self.assertIn("volume_snapshot_receipt", resolved["particle_source"])
        self.assertEqual(budget["solver_numerics"]["mesh"]["global_auto_level"], 9)
        self.assertEqual(budget["limits"]["wall_clock_seconds"], 1200)

    def test_unauthorized_wrong_solver_and_wrong_run_fail(self):
        data = request()
        data["experiments"][0]["resource_authorization"]["authorized"] = False
        path, resolved = self.resolve(data)
        with self.assertRaisesRegex(ValueError, "not authorized"):
            self.budget(path, resolved)
        path, resolved = self.resolve(request())
        with self.assertRaises(ValueError):
            self.budget(path, resolved, run_id="wrong")
        with self.assertRaises(ValueError):
            self.budget(path, resolved, solver="simion")

    def test_schema_and_unimplemented_comsol_policy_reject(self):
        data = request()
        data["experiments"][0]["solver"] = "unknown"
        with self.assertRaises(ValueError):
            self.resolve(data)
        data = request()
        data["experiments"][0]["source_kinetic_energy_eV"] = 2.0
        with self.assertRaises(ValueError):
            self.resolve(data)

    def wrapper(self):
        target = (
            self.root
            / "projects/rf_multipole_ion_optics/workflows/no_collision_transport/run_comsol.ps1"
        )
        target.parent.mkdir(parents=True)
        target.write_text(
            (PROJECT / "workflows/no_collision_transport/run_comsol.ps1").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        support = (
            self.root
            / "projects/rf_multipole_ion_optics/runtime/project_transport_launcher_support.ps1"
        )
        support.parent.mkdir(parents=True)
        support.write_text(
            "function Invoke-MultipoleProjectFinite3dTransport { param($Solver,$ProjectId,$RepoRoot,$CampaignPath,$ExperimentId,$RuntimeProfileId,$ResolvedRuntimeProfilePath,$EvidenceContractPath,$RunId,$RetentionClass,$RetentionReason,$PythonExe) $PSBoundParameters | ConvertTo-Json | Set-Content -LiteralPath $env:RF_TEST_CAPTURE -Encoding utf8 }",
            encoding="utf-8",
        )
        return target

    def test_original_public_cli_forwards_campaign(self):
        target = self.wrapper()
        env = os.environ.copy()
        capture = self.root / "capture.json"
        env["RF_TEST_CAPTURE"] = str(capture)
        execution = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-File",
                str(target),
                "-CampaignPath",
                "request.json",
                "-ExperimentId",
                "example",
            ],
            env=env,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
        )
        self.assertEqual(execution.returncode, 0, execution.stderr)
        actual = json.loads(capture.read_text(encoding="utf-8-sig"))
        self.assertEqual(actual["Solver"], "comsol")
        self.assertEqual(actual["CampaignPath"], "request.json")
        self.assertEqual(actual["ExperimentId"], "example")
        self.assertNotIn("RuntimeProfileId", actual)
        self.assertNotIn("RetentionClass", actual)

    def test_original_public_cli_rejects_ambiguous_selection(self):
        target = self.wrapper()
        quoted = "'" + str(target).replace("'", "''") + "'"
        command = (
            "try { & "
            + quoted
            + " -CampaignPath request.json -ExperimentId example -RuntimeProfileId other } catch { Write-Output ('PARAMETER_FAILURE=' + $_.FullyQualifiedErrorId); exit 7 }"
        )
        execution = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command],
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
        )
        self.assertEqual(execution.returncode, 7, execution.stdout + execution.stderr)
        self.assertIn("AmbiguousParameterSet", execution.stdout)

    def test_legacy_simion_campaign_schema_unchanged(self):
        legacy = json.loads(
            (
                REPO
                / "projects/rf_multipole_ion_optics/config/campaigns/20260731__noacc_vs_segmented_h15_n100.json"
            ).read_text(encoding="utf-8")
        )
        validate_schema(legacy, SCHEMA)
        legacy["experiments"][0]["resource_authorization"]["limits"].pop(
            "maximum_pa_grid_points"
        )
        with self.assertRaises(ValueError):
            validate_schema(legacy, SCHEMA)

    def test_actual_launcher_transports_one_compiled_runtime(self):
        path, resolved = self.resolve(request())
        snapshot = self.root / "resolved.json"
        snapshot.write_text(json.dumps(resolved), encoding="utf-8")
        capture = self.root / "capture.json"
        entry = (
            self.root
            / "projects/rf_multipole_ion_optics/runtime/run_finite_3d_transport.ps1"
        )
        entry.parent.mkdir(parents=True)
        entry.write_text(
            "param($ProjectId,$RuntimeProfileId,$DesignProfileId,$EngineeringBudgetPath,$RunId,$ResolvedRuntimeProfilePath,$RetentionClass,$RetentionReason,$PythonExe,$RfStepsPerPeriod,$MaximumTimeUs,$ParticleSourcePath,$StopStage,$MeshAutoLevel,$WorkingRegionMaximumElementSizeMm) $resolved=Get-Content -LiteralPath $ResolvedRuntimeProfilePath -Raw -Encoding UTF8|ConvertFrom-Json; @{id=$resolved.runtime_profile_id;passed_id=$RuntimeProfileId;read_ir=$true;maximum_us=$MaximumTimeUs;mesh=$MeshAutoLevel} | ConvertTo-Json | Set-Content -LiteralPath $env:RF_TEST_CAPTURE -Encoding utf8",
            encoding="utf-8",
        )

        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"

        support = (
            REPO
            / "projects/rf_multipole_ion_optics/runtime/project_transport_launcher_support.ps1"
        )
        script = self.root / "invoke.ps1"
        script.write_text(
            "$ErrorActionPreference='Stop';$global:LASTEXITCODE=0; . "
            + quote(support)
            + "; Invoke-MultipoleProjectFinite3dTransport -Solver comsol -ProjectId rf_multipole_ion_optics -RepoRoot "
            + quote(self.root)
            + " -PythonExe "
            + quote(sys.executable)
            + " -CampaignPath "
            + quote(path)
            + " -ExperimentId octupole_goal_n100_8us -ResolvedRuntimeProfilePath "
            + quote(snapshot),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["RF_TEST_CAPTURE"] = str(capture)
        execution = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(script)],
            env=env,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
        )
        self.assertEqual(execution.returncode, 0, execution.stdout + execution.stderr)
        actual = json.loads(capture.read_text(encoding="utf-8-sig"))
        self.assertTrue(actual["read_ir"])
        self.assertEqual(actual["id"], actual["passed_id"])
        self.assertEqual(actual["maximum_us"], 8)
        self.assertEqual(actual["mesh"], 9)



if __name__ == "__main__":
    unittest.main(verbosity=2)

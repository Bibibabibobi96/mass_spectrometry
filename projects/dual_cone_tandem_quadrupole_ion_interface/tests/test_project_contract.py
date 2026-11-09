"""Static ownership and capability checks for the supported preparation chain."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from common.contracts.build_project_registry import validate_descriptor
from common.paths.repository_root import REPO_ROOT
from msplatform.contracts.machine_contracts import validate_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ProjectContractTests(unittest.TestCase):
    def test_actual_scheduler_source_table_loads_frozen_budget_observation(self) -> None:
        from msplatform.backends.comsol.gas_flow import RESOURCES
        from msplatform.backends.comsol.native_execution import freeze_native_sources
        from common.contracts.test_support.comsol_model import InertComsolSession

        with tempfile.TemporaryDirectory(prefix="dual_cone_budget_closure_") as directory:
            session = InertComsolSession(Path(directory), model_relative_paths=())
            launcher, records = freeze_native_sources(session, RESOURCES)
            resources = launcher.parents[3] / "execution/resources"
            host = dict(
                workspace=directory,
                python_executable=sys.executable,
                host_state_path=str(Path(directory) / "state.sqlite3"),
                policy_path=str(session.context.policy_path),
            )
            script = """param($Resources,$Context)
$ErrorActionPreference='Stop'
. (Join-Path $Resources 'host_execution_lease.ps1') -HostContext (ConvertFrom-Json -InputObject $Context -AsHashtable)
. (Join-Path $Resources 'resource_process_support.ps1')
if((Get-Command New-RepositoryProcessObservation).ScriptBlock.File-ne(Join-Path $Resources 'resource_process_support.ps1')){throw 'Observation escaped frozen source'}
$observation=New-RepositoryProcessObservation
if($null-ne$observation.usage){throw 'Unbudgeted observation created usage output'}
'FROZEN_BUDGET_OBSERVATION=PASS'
"""
            task = Path(directory) / "observe.ps1"
            task.write_text(script, encoding="utf-8")
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(task), str(resources), json.dumps(host)],
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("FROZEN_BUDGET_OBSERVATION=PASS", result.stdout)
            self.assertTrue(records)

    def test_descriptor_and_execution_profiles_are_valid(self) -> None:
        descriptor_path = PROJECT_ROOT / "config/project.json"
        descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
        validate_descriptor(descriptor, descriptor_path, REPO_ROOT)
        profiles = json.loads((PROJECT_ROOT / "config/execution_profiles.json").read_text(encoding="utf-8"))
        validate_schema(profiles, "execution_profiles.schema.json")
        self.assertEqual(
            {profile["mode"] for profile in profiles["profiles"]},
            {
                "axisymmetric_gas_flow_screening",
            },
        )
        self.assertTrue(
            all(
                profile["action"] == "run" and profile["qualification_support"] == ["none"]
                for profile in profiles["profiles"]
            )
        )
        run_steps = [step for profile in profiles["profiles"] for step in profile["steps"] if step["kind"] == "run"]
        self.assertEqual(len(run_steps), 1)
        self.assertTrue(all("-RunId" in step["arguments"] for step in run_steps))
        comsol_runner = (PROJECT_ROOT / "workflows/gas_assisted_transport/run_axisymmetric_gas_flow.ps1").read_text(
            encoding="utf-8"
        )
        for token in (
            "msplatform.backends.comsol.gas_flow",
            "--compiled-inputs $ResolvedInputsPath",
            "--deployment $DeploymentPath",
            "--workspace $Workspace",
            "--engineering-profile $EngineeringProfile",
            "--run-id $RunId",
        ):
            self.assertIn(token, comsol_runner)
        self.assertNotIn("New-RunPackage", comsol_runner)
        self.assertNotIn("Enter-HostResourceStage", comsol_runner)
        self.assertNotIn(".venv", comsol_runner)
        self.assertNotIn("DUAL_CONE_PROJECT_ROOT", comsol_runner)

    def test_comsol_capacity_session_uses_public_owner(self) -> None:
        from unittest.mock import patch
        from msplatform.backends.comsol import gas_flow
        from common.contracts.test_comsol_gas_flow import input_paths
        from msplatform.execution import owner

        self.assertIs(gas_flow.run_managed_stage, owner.run_managed_stage)
        request = gas_flow.resolve_gas_flow_request(*input_paths())
        self.assertEqual(set(request["inputs"]), {"baseline", "geometry", "science", "numerics"})
        with patch.object(gas_flow, "run_managed_stage", side_effect=RuntimeError("actual owner boundary")) as boundary:
            from common.contracts.test_execution_runtime import NormalOwnerTests

            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                helper = NormalOwnerTests()
                context = helper._context(root)
                # This is a no-native dispatch check; the complete owner lifecycle
                # remains exercised by the shared owner and gas operation tests.
                from dataclasses import replace

                context = replace(context, tools=dict(comsol_launcher=Path(sys.executable), matlab_root=root))
                policy = root / "stages.json"
                policy.write_text(
                    json.dumps(
                        dict(
                            schema_version=1,
                            role="execution_stage_policy",
                            stages=dict(
                                solve_gas_flow=dict(
                                    limits=dict(
                                        wall_clock_seconds=120,
                                        transient_run_directory_bytes=64 * 1024**2,
                                        process_tree_working_set_bytes=1024**3,
                                        minimum_system_available_memory_bytes=1,
                                        compact_final_retained_bytes=64 * 1024**2,
                                        automatic_retry_count=0,
                                    ),
                                    artifact_retention=dict(
                                        policy_version=1, **{"class": "solver_review"}, reason="inert dispatch"
                                    ),
                                )
                            ),
                        )
                    ),
                    encoding="utf-8",
                )
                context = replace(context, stage_policy_path=policy)
                with self.assertRaisesRegex(RuntimeError, "actual owner boundary"):
                    gas_flow.solve_axisymmetric_gas_flow(*input_paths(), context=context)
        self.assertEqual(boundary.call_count, 1)
        self.assertEqual(boundary.call_args.kwargs["expected_operation_ids"], ("solve_gas_flow",))
        self.assertEqual(boundary.call_args.kwargs["committed_new_bytes"], 64 * 1024**2)

    def test_retired_python_integrator_is_not_an_active_entry(self) -> None:
        profiles = (PROJECT_ROOT / "config/execution_profiles.json").read_text(encoding="utf-8")
        descriptor = (PROJECT_ROOT / "config/project.json").read_text(encoding="utf-8")
        self.assertNotIn("pressure_drag_screening", profiles)
        self.assertNotIn("pressure_drag_screening", descriptor)
        for relative in (
            "analysis/reduced_order_transport.py",
            "analysis/run_reduced_order_transport.py",
            "config/modes/pressure_drag_screening.json",
        ):
            self.assertFalse((PROJECT_ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()

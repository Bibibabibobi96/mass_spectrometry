"""Real OA–MR Store composition, failure and publication recovery tests."""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution.context import ExecutionContext
from msplatform.execution.resources import resource_path
from msplatform.execution.run_session import RunSession
from msplatform.storage import ArtifactStore
from msplatform.workflows.oa_mr import store_workflow

PWSH = shutil.which("pwsh")
RUN_ID = "20261128_120000__test__simion__oa-mr-store"


@unittest.skipUnless(os.name == "nt" and PWSH, "Windows PowerShell 7 required")
class OaMrStoreWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="oa-mr-store-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ArtifactStore(self.root / "store")
        simion = self.root / "simion.exe"
        simion.write_bytes(b"inert executable identity; never launched")
        self.context = ExecutionContext(workspace=self.root / "workspace",
            python_executable=Path(sys.executable), powershell_executable=Path(PWSH),
            tools={"simion": simion}, host_state_path=self.root / "private-host.sqlite3",
            policy_path=resource_path("host_resource_policy.json"),
            execution_root=self.root / "aliases")
        self.script = self.root / "inert_oa_mr_controller.ps1"
        self.script.write_text(r"""param($RunId,$PythonExe,$RepoRoot)
$ErrorActionPreference='Stop'
$run=$env:MASS_SPECTROMETRY_RUN_DIRECTORY
if((Split-Path -Leaf $run)-cne$RunId){throw 'run identity differs'}
if($env:MASS_SPECTROMETRY_OA_MR_CAPACITY_JSON-notmatch'active'){throw 'Store capacity missing'}
$result=Join-Path $run 'results/science.json'
[IO.File]::WriteAllText($result,'{"role":"inert_science","run_id":"'+$RunId+'"}')
$role=if($env:INERT_FAILURE){'mrtof_finite_3d_two_prism_voltage_trial'}else{'mrtof_finite_3d_two_prism_voltage_trial'}
$summary=@{schema_version=1;role=$role;status=$(if($env:INERT_FAILURE){'failed'}else{'success'});execution_status=$(if($env:INERT_FAILURE){'failed'}else{'completed'});scientific_result='not_evaluated'}
[IO.File]::WriteAllText((Join-Path $run 'summary.json'),($summary|ConvertTo-Json -Depth 20 -Compress))
if($env:INERT_FAILURE){exit 7}
""", encoding="utf-8")
        contract = self.root / "contract.json"
        contract.write_text('{"simion": {}}', encoding="utf-8")
        self.request_path = self.root / "request.json"
        self.request = dict(run_id=RUN_ID, repository_root=str(self.root / "author"),
            legacy_artifact_root=str(self.root / "legacy"),
            accelerator_component_contract_path=str(self.root / "oa.json"),
            accelerator_geometry_profile_id="closed_two_zone_compact_mr_axial_r3_gap1_4mm",
            geometry_review_run_path=str(self.root / "geometry"),
            mirror_run_path=str(self.root / "mirror"), stripe_run_path=str(self.root / "stripe"),
            accelerator_provider_receipt_path=str(self.root / "provider.json"),
            composition_plan_path=str(self.root / "plan.json"),
            prism1_voltage_v=190.0, prism2_voltage_v=-186.0,
            field_binding_path=str(self.root / "binding.json"), contract_path=str(contract),
            retain_gui_workbench=False)
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")
        (self.root / "binding.json").write_text('{"mode": "native_static_pa"}', encoding="utf-8")
        self.calls = 0

    def invoke(self, *, failure=False, interrupt_publication=False, tamper_request=False):
        real_run = RunSession.run_process
        def inert_process(session, operation_id, **kwargs):
            self.calls += 1
            self.assertEqual(operation_id, "oa_mr")
            self.assertEqual((kwargs["role"], kwargs["stage"]), ("SIMION", "mrtof_flight"))
            arguments = list(kwargs["arguments"])
            arguments[arguments.index("-File") + 1] = str(self.script)
            if tamper_request:
                self.request_path.write_text(json.dumps(dict(self.request, prism1_voltage_v=191.0)), encoding="utf-8")
            environment = dict(kwargs.get("environment", {}))
            if failure:
                environment["INERT_FAILURE"] = "1"
            return real_run(session, operation_id, **dict(kwargs, arguments=arguments, environment=environment))
        patches = [patch.object(store_workflow, "_controller_path", return_value=self.script),
                   patch.object(store_workflow, "_guard_request_sources"),
                   patch.object(store_workflow, "_guard_static_sources"),
                   patch.object(store_workflow, "_controller_arguments", return_value=[]),
                   patch.object(store_workflow, "_native_peak", return_value=32 * 1024**2),
                   patch.object(RunSession, "run_process", new=inert_process)]
        if interrupt_publication:
            real_replace = os.replace
            def interrupted(source, destination):
                if (Path(source).is_relative_to(self.store.root / "work")
                        and Path(destination).is_relative_to(self.store.root / "runs")):
                    raise OSError("OA_MR_PUBLICATION_SENTINEL")
                return real_replace(source, destination)
            patches.append(patch("msplatform.storage.store.os.replace", side_effect=interrupted))
        started = []
        try:
            for apply in patches:
                apply.start()
                started.append(apply)
            return store_workflow.run_oa_mr(context=self.context,
                artifact_store=self.store, request_path=self.request_path)
        finally:
            for apply in reversed(started):
                apply.stop()

    def test_real_store_success_and_repeat_recovery_without_native_rerun(self) -> None:
        result = self.invoke()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["run_id"], RUN_ID)
        self.assertEqual(self.calls, 1)
        self.assertTrue(self.store.inspect_run(result["store_run_id"]).is_dir())
        self.assertEqual(len(result["native_stage_asset_ids"]), 1)
        self.assertFalse(store_workflow.recover_oa_mr_publication(
            artifact_store=self.store, store_run_id=result["store_run_id"])["recovered"])
        self.assertFalse(store_workflow.recover_oa_mr_stage(artifact_store=self.store,
            native_stage_asset_id=result["native_stage_asset_ids"][0], context=self.context)["recovered"])
        self.assertEqual(self.calls, 1)
        with self.assertRaises(Exception):
            self.invoke()
        self.assertEqual(self.calls, 1)

    def test_interrupted_publication_rejects_tamper_then_replays_exact_run_once(self) -> None:
        with self.assertRaisesRegex(OSError, "OA_MR_PUBLICATION_SENTINEL") as caught:
            self.invoke(interrupt_publication=True)
        notes = caught.exception.__notes__
        store_id = next(note.rsplit(": ", 1)[1] for note in notes
                        if note.startswith("OA–MR Store run_id: "))
        status = self.store.run_status(store_id)
        self.assertEqual(status["publication_status"], "publishing")
        work = self.store.root / Path(status["work_path"])
        manifest = work / "run_manifest.json"
        original = manifest.read_bytes()
        try:
            manifest.write_bytes(original + b" ")
            with self.assertRaisesRegex(ValueError, "missing or modified"):
                store_workflow.recover_oa_mr_publication(
                    artifact_store=self.store, store_run_id=store_id)
        finally:
            manifest.write_bytes(original)
        self.assertTrue(store_workflow.recover_oa_mr_publication(
            artifact_store=self.store, store_run_id=store_id)["recovered"])
        self.assertFalse(store_workflow.recover_oa_mr_publication(
            artifact_store=self.store, store_run_id=store_id)["recovered"])
        self.assertEqual(self.calls, 1)

    def test_failed_stage_preserves_identity_and_never_becomes_success(self) -> None:
        with self.assertRaisesRegex(Exception, "Observed process failed|scientific controller failed") as caught:
            self.invoke(failure=True)
        notes = caught.exception.__notes__
        store_id = next(note.rsplit(": ", 1)[1] for note in notes
                        if note.startswith("OA–MR Store run_id: "))
        asset_id = next(note.rsplit(": ", 1)[1] for note in notes
                        if note.startswith("OA–MR native stage asset_id: "))
        self.assertEqual(self.store.run_status(store_id)["execution_status"], "failed")
        with self.store._db() as database:
            state, reason = database.execute("SELECT state,failure FROM assets WHERE id=?",
                (asset_id,)).fetchone()
        self.assertEqual(state, "failed")
        self.assertTrue("scientific controller failed" in reason or "Observed process failed" in reason)
        self.assertFalse(store_workflow.recover_oa_mr_stage(artifact_store=self.store,
            native_stage_asset_id=asset_id, context=self.context)["recovered"])
        self.assertEqual(self.calls, 1)

    def test_missing_request_fields_fail_before_controller(self) -> None:
        del self.request["mirror_run_path"]
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing=.*mirror_run_path"):
            self.invoke()
        self.assertEqual(self.calls, 0)

    def test_legacy_owner_parameters_are_not_a_compatibility_entry(self) -> None:
        for name in ("CapacityWorkflowSession", "NativeCorridorRuntimeSession", "ResumeFinalization"):
            with self.subTest(name=name):
                self.request[name] = {} if name != "ResumeFinalization" else True
                self.request_path.write_text(json.dumps(self.request), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "unknown=.*" + name):
                    self.invoke()
                self.assertEqual(self.calls, 0)
                self.request.pop(name)

    def test_missing_declared_input_fails_before_controller(self) -> None:
        (self.root / "binding.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.invoke()
        self.assertEqual(self.calls, 0)

    def test_request_tamper_after_admission_fails_closed(self) -> None:
        with self.assertRaises(PermissionError):
            self.invoke(tamper_request=True)
        self.assertEqual(self.calls, 1)

    def test_small_scientific_authorities_stay_write_protected(self) -> None:
        from contextlib import ExitStack
        for name in ("mirror", "stripe"):
            directory = self.root / name
            directory.mkdir()
            for filename in ("summary.json", "run_manifest.json"):
                (directory / filename).write_text("{}", encoding="utf-8")
        plan = self.root / "provider-plan.json"
        campaign = self.root / "provider-campaign.json"
        provider_run = self.root / "provider-run"
        (provider_run / "results").mkdir(parents=True)
        provider = provider_run / "results/provider.json"
        self.request["accelerator_provider_receipt_path"] = str(provider)
        for path in (plan, campaign):
            path.write_text("{}", encoding="utf-8")
        provider.write_text(json.dumps(dict(provider_plan=dict(path=str(plan)),
            resolved_campaign=dict(path=str(campaign)))), encoding="utf-8")
        for name in ("plan.json", "binding.json", "native-system.json", "bunch.json"):
            (self.root / name).write_text("{}", encoding="utf-8")
        (provider_run / "run_manifest.json").write_text("{}", encoding="utf-8")
        states, fly2 = self.root / "states.csv", self.root / "source.fly2"
        states.write_text("id", encoding="utf-8")
        fly2.write_bytes(b"inert")
        (self.root / "bunch.json").write_text(json.dumps(dict(
            state_table=dict(path=str(states)), fly2=dict(path=str(fly2)))), encoding="utf-8")
        self.request.update(native_system_runtime_bundle_path=str(self.root / "native-system.json"),
                            bunch_source_receipt_path=str(self.root / "bunch.json"))
        with ExitStack() as guards:
            store_workflow._guard_request_sources(guards, self.request)
            with self.assertRaises(PermissionError):
                plan.write_text("tampered", encoding="utf-8")
            with self.assertRaises(PermissionError):
                (self.root / "mirror/run_manifest.json").write_text("tampered", encoding="utf-8")
        plan.write_text("{}", encoding="utf-8")

    def test_controller_arguments_preserve_science_and_checkpoint_without_capacity_session(self) -> None:
        arguments = store_workflow._controller_arguments(dict(self.request,
            native_runtime_checkpoint="checkpoint.json", retain_gui_workbench=True,
            inherited_host_resource_lease={"token": "parent", "inherited": True}))
        self.assertIn("checkpoint.json", arguments)
        self.assertIn("-RetainGuiWorkbench", arguments)
        self.assertIn("-InheritedHostResourceLeaseJson", arguments)
        self.assertNotIn("CapacityWorkflowSession", arguments)
        self.assertNotIn("NativeCorridorRuntimeSession", arguments)

    def test_recovery_adapters_fail_closed_for_missing_and_tampered_inputs(self) -> None:
        for message in ("active native binding prevents run publication recovery",
                        "run writer lock evidence is unavailable",
                        "interrupted publication payload is missing or modified"):
            with self.subTest(message=message), patch.object(
                    ArtifactStore, "recover_run_publication", side_effect=ValueError(message)) as recover:
                with self.assertRaisesRegex(ValueError, message):
                    store_workflow.recover_oa_mr_publication(
                        artifact_store=self.store, store_run_id="store-run")
                recover.assert_called_once_with("store-run")
        for message in ("native writer is still active", "native Store stage run identity is unavailable",
                        "guarded file SHA-256 does not match"):
            with self.subTest(message=message), patch(
                    "msplatform.workflows.oa_mr.store_workflow.recover_managed_native_store_stage",
                    side_effect=ValueError(message)) as recover:
                with self.assertRaisesRegex(ValueError, message):
                    store_workflow.recover_oa_mr_stage(artifact_store=self.store,
                        native_stage_asset_id="native-stage", context=self.context)
                recover.assert_called_once_with(self.store, "native-stage", context=self.context)
        for function, options in ((store_workflow.recover_oa_mr_publication,
                                   dict(artifact_store=self.store, store_run_id="")),
                                  (store_workflow.recover_oa_mr_stage,
                                   dict(artifact_store=self.store, native_stage_asset_id="",
                                        context=self.context))):
            with self.assertRaisesRegex(ValueError, "exact"):
                function(**options)


if __name__ == "__main__":
    unittest.main()

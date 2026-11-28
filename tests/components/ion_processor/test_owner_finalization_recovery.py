"""Standalone IP Store recovery adapters; the public owner holds the full matrix."""
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
from msplatform.workflows.ion_processor import native_functional

PWSH = shutil.which("pwsh")
RUN_ID = "20261128_120000__test__simion__ip-store-recovery"


def _interrupted_publishing_writer(root, ready, release, result) -> None:
    from tests.contracts.test_artifact_store import _publishing_writer
    try:
        _publishing_writer(root, ready, release, result)
    except OSError as error:
        if str(error) != "publication interrupted":
            raise


@unittest.skipUnless(os.name == "nt" and PWSH, "Windows PowerShell 7 required")
class OwnerFinalizationRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ip-store-recovery-")
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
        self.script = self.root / "inert_native_stage.ps1"
        self.script.write_text(r"""param($RunId,$PythonExe,$ResourceProfileRunsRoot,$SimionExe,$SourceProfile,$ConfigurationDirectory,$NativeFieldRun,$ContinuationPredecessorManifestPath,$InjectedSource,$Failure)
$ErrorActionPreference='Stop'
$run=$env:MASS_SPECTROMETRY_RUN_DIRECTORY
$result=Join-Path $run 'results/science.json'
[IO.File]::WriteAllText($result,'{"role":"inert_science","run_id":"'+$RunId+'"}')
$role=if($Failure){'ion_processor_failed_run'}else{'ion_processor_functional_summary'}
$summary=@{schema_version=1;role=$role;status=$(if($Failure){'failed'}else{'success'});execution_status=$(if($Failure){'failed'}else{'completed'});science_status=$(if($Failure){'unknown'}else{'passed'});native_completed=$false}
[IO.File]::WriteAllText((Join-Path $run 'summary.json'),($summary|ConvertTo-Json -Compress))
if($Failure){exit 7}
""", encoding="utf-8")
        self.profile_path = self.root / "runtime_profiles.json"
        from importlib.resources import files
        project = Path(str(files("msplatform.components.ion_processor")))
        _, original = native_functional._runtime_profile(project)
        profile = dict(original, committed_new_bytes=32 * 1024**2,
            limits=dict(original["limits"], transient_run_directory_bytes=32 * 1024**2))
        self.profile_path.write_text(json.dumps(dict(schema_version=1,
            role="ion_processor_runtime_profiles", project_id="ion_processor",
            profiles=[profile])), encoding="utf-8")
        self.profile = profile
        self.calls = 0

    def invoke(self, *, failure=False, interrupt_publication=False):
        real_run = RunSession.run_process
        def inert_process(session, operation_id, **kwargs):
            self.calls += 1
            self.assertEqual((kwargs["role"], kwargs["stage"]), ("SIMION", "workflow"))
            arguments = list(kwargs["arguments"])
            arguments[arguments.index("-File") + 1] = str(self.script)
            if failure:
                arguments.append("-Failure")
            return real_run(session, operation_id, **dict(kwargs, arguments=arguments))
        patches = [patch.object(native_functional, "_runtime_profile",
                                return_value=(self.profile_path, self.profile)),
                   patch.object(RunSession, "run_process", new=inert_process)]
        if interrupt_publication:
            real_replace = os.replace
            def interrupted(source, destination):
                if (Path(source).is_relative_to(self.store.root / "work")
                        and Path(destination).is_relative_to(self.store.root / "runs")):
                    raise OSError("IP_PUBLICATION_SENTINEL")
                return real_replace(source, destination)
            patches.append(patch("msplatform.storage.store.os.replace", side_effect=interrupted))
        started = []
        try:
            for apply in patches:
                apply.start()
                started.append(apply)
            return native_functional.run_native_functional(context=self.context,
                artifact_store=self.store, run_id=RUN_ID)
        finally:
            for apply in reversed(started):
                apply.stop()

    def test_real_store_success_and_recovery_are_idempotent_without_native_rerun(self) -> None:
        result = self.invoke()
        self.assertEqual(result["status"], "success")
        self.assertEqual(self.calls, 1)
        self.assertTrue(self.store.inspect_run(result["store_run_id"]).is_dir())
        self.assertEqual(len(result["native_stage_asset_ids"]), 1)
        self.assertFalse(native_functional.recover_native_publication(
            artifact_store=self.store, store_run_id=result["store_run_id"])["recovered"])
        self.assertFalse(native_functional.recover_native_stage(artifact_store=self.store,
            native_stage_asset_id=result["native_stage_asset_ids"][0], context=self.context)["recovered"])
        self.assertEqual(self.calls, 1)

    def test_interrupted_publication_rejects_tamper_then_replays_exact_run_once(self) -> None:
        with self.assertRaisesRegex(OSError, "IP_PUBLICATION_SENTINEL") as caught:
            self.invoke(interrupt_publication=True)
        notes = caught.exception.__notes__
        store_id = next(note.rsplit(": ", 1)[1] for note in notes
                        if note.startswith("IP Store run_id: "))
        status = self.store.run_status(store_id)
        self.assertEqual(status["publication_status"], "publishing")
        work = self.store.root / Path(status["work_path"])
        manifest = work / "run_manifest.json"
        original = manifest.read_bytes()
        try:
            manifest.write_bytes(original + b" ")
            with self.assertRaisesRegex(ValueError, "missing or modified"):
                native_functional.recover_native_publication(
                    artifact_store=self.store, store_run_id=store_id)
        finally:
            manifest.write_bytes(original)
        self.assertTrue(native_functional.recover_native_publication(
            artifact_store=self.store, store_run_id=store_id)["recovered"])
        self.assertFalse(native_functional.recover_native_publication(
            artifact_store=self.store, store_run_id=store_id)["recovered"])
        self.assertEqual(self.calls, 1)

    def test_failed_native_stage_preserves_ids_and_never_becomes_success(self) -> None:
        with self.assertRaisesRegex(Exception, "Observed process failed|native workflow failed") as caught:
            self.invoke(failure=True)
        notes = caught.exception.__notes__
        store_id = next(note.rsplit(": ", 1)[1] for note in notes
                        if note.startswith("IP Store run_id: "))
        asset_id = next(note.rsplit(": ", 1)[1] for note in notes
                        if note.startswith("IP native stage asset_id: "))
        self.assertEqual(self.store.run_status(store_id)["execution_status"], "failed")
        with self.store._db() as database:
            state, reason = database.execute("SELECT state,failure FROM assets WHERE id=?",
                (asset_id,)).fetchone()
        self.assertEqual(state, "failed")
        self.assertTrue("native workflow failed" in reason or "Observed process failed" in reason)
        self.assertFalse(native_functional.recover_native_stage(artifact_store=self.store,
            native_stage_asset_id=asset_id, context=self.context)["recovered"])
        self.assertEqual(self.calls, 1)

    def test_live_writer_blocks_real_publication_recovery_before_idempotent_replay(self) -> None:
        from multiprocessing import get_context
        context = get_context("spawn")
        ready = context.Event()
        release = context.Event()
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=_interrupted_publishing_writer,
            args=(str(self.store.root), ready, release, send))
        process.start()
        try:
            self.assertTrue(ready.wait(30))
            run_id = receive.recv()
            with self.assertRaises(TimeoutError):
                native_functional.recover_native_publication(
                    artifact_store=self.store, store_run_id=run_id)
            self.assertEqual(self.store.run_status(run_id)["publication_status"], "publishing")
            release.set()
            process.join(30)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
            self.assertTrue(native_functional.recover_native_publication(
                artifact_store=self.store, store_run_id=run_id)["recovered"])
            self.assertFalse(native_functional.recover_native_publication(
                artifact_store=self.store, store_run_id=run_id)["recovered"])
        finally:
            release.set()
            if process.is_alive():
                process.terminate()
                process.join(30)

    def test_injected_source_records_are_absolute_guarded_and_reject_drift(self) -> None:
        from contextlib import ExitStack
        from msplatform.io.manifest_records import file_record
        source = self.root / "injected/source.json"
        source.parent.mkdir()
        states = source.parent / "states.csv"
        states.write_bytes(b"canonical source fixture")
        record = dict(file_record(states), path="states.csv")
        source.write_text(json.dumps({"source_states": record}), encoding="utf-8")
        with ExitStack() as guards:
            records = native_functional._source_records(guards, native_field_run=None,
                continuation_manifest=None, injected_source=source)
            self.assertTrue(all(Path(row["path"]).is_absolute() for row in records))
            with self.assertRaises(PermissionError):
                states.write_bytes(b"blocked writer")
        states.write_bytes(b"tampered source")
        with ExitStack() as guards, self.assertRaisesRegex(ValueError, "byte count|SHA-256"):
            native_functional._source_records(guards, native_field_run=None,
                continuation_manifest=None, injected_source=source)
        states.unlink()
        with ExitStack() as guards, self.assertRaises(FileNotFoundError):
            native_functional._source_records(guards, native_field_run=None,
                continuation_manifest=None, injected_source=source)

    def test_recovery_adapters_fail_closed_for_live_writer_missing_and_tampered_inputs(self) -> None:
        for message in ("active native binding prevents run publication recovery",
                        "run writer lock evidence is unavailable",
                        "interrupted publication payload is missing or modified"):
            with self.subTest(message=message), patch.object(
                    ArtifactStore, "recover_run_publication", side_effect=ValueError(message)) as recover:
                with self.assertRaisesRegex(ValueError, message):
                    native_functional.recover_native_publication(
                        artifact_store=self.store, store_run_id="store-run")
                recover.assert_called_once_with("store-run")
        for message in ("native writer is still active", "native Store stage run identity is unavailable",
                        "guarded file SHA-256 does not match"):
            with self.subTest(message=message), patch(
                    "msplatform.workflows.ion_processor.native_functional.recover_managed_native_store_stage",
                    side_effect=ValueError(message)) as recover:
                with self.assertRaisesRegex(ValueError, message):
                    native_functional.recover_native_stage(artifact_store=self.store,
                        native_stage_asset_id="native-stage", context=self.context)
                recover.assert_called_once_with(self.store, "native-stage", context=self.context)
        for function, options in ((native_functional.recover_native_publication,
                                   dict(artifact_store=self.store, store_run_id="")),
                                  (native_functional.recover_native_stage,
                                   dict(artifact_store=self.store, native_stage_asset_id="",
                                        context=self.context))):
            with self.assertRaisesRegex(ValueError, "exact"):
                function(**options)


if __name__ == "__main__":
    unittest.main()

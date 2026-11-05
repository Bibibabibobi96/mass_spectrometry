"""Installed owner parity for stopped-stage accounting; only inert Python children."""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from msplatform.execution import owner
from msplatform.execution.capacity_admission import _capacity_policy
from msplatform.execution.capacity_ledger import load_capacity_ledger
from msplatform.execution.capacity_protection import load_capacity_protection_leases
from msplatform.execution.context import ExecutionContext
from msplatform.execution.manifest_records import file_record
from msplatform.execution.recorded_file_removal import write_json_atomic
from msplatform.execution.resources import resource_path


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell required")
class ExecutionAccountingHoldTests(unittest.TestCase):
    def test_original_capacity_authority_controls_resume_despite_stale_result_hold(self):
        """A stale Result is not accounting; this does not reconcile a real hold."""
        from msplatform.backends.simion import native_completion
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = ExecutionContext(workspace=root/'study', python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which('pwsh')), tools={},
                host_state_path=root/'private-host.sqlite3', policy_path=resource_path('host_resource_policy.json'))
            budget = root/'budget.json'
            budget.write_text('{"bytes":1048576}', encoding='utf-8')
            calls = []

            def action(session):
                calls.append(session.run_id)
                evidence = session.declare_file(session.result_dir/'failed-evidence.txt', 'required_evidence')
                evidence.write_bytes(b'ORIGINAL_FAILED_EVIDENCE')
                raise ValueError('ORIGINAL_ACTION_FAILURE')

            policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
            environment = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN='', MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID='',
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE='', MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
            with patch.dict(os.environ, environment), patch.object(owner, '_capacity_policy', return_value=policy), patch(
                    'msplatform.execution.capacity_admission._capacity_policy', return_value=policy):
                with patch.object(owner, '_finalize', side_effect=OSError('PUBLICATION_INTERRUPTED')):
                    with self.assertRaisesRegex(ValueError, 'ORIGINAL_ACTION_FAILURE'):
                        owner.run_managed_stage(context,
                            descriptor=dict(project='instrument_assembly', mode='accounting_fixture', software=[]),
                            run_id='20261104_120000__test__python__stale-accounting-result', payload={},
                            committed_new_bytes=1048576, commitment_inputs=[file_record(budget,'required_evidence')],
                            retention=dict(policy_version=1, **{'class':'solver_review'}, reason='inert failed evidence'),
                            expected_operation_ids=[], operation_dependencies={}, action=action,
                            action_record=file_record(Path(__file__), 'required_evidence'),
                            completion_api=lambda:native_completion)
                result_path = next((context.workspace/'artifacts').rglob('result.json'))
                original = json.loads(result_path.read_text())
                run = Path(original['run_directory'])
                authority = run/'logs/capacity_session.json'
                authority_bytes = authority.read_bytes()
                self.assertNotIn('defer_capacity_finalization', json.loads(authority_bytes))
                lease_path = context.workspace/'artifacts/common/capacity_protection_leases'/(
                    json.loads(authority_bytes)['lease_id']+'.json')
                lease_bytes = lease_path.read_bytes()
                completion = (run/'results/execution_completion.json').read_bytes()
                for field in ('owner','artifact_root','lease_id'):
                    with self.subTest(identity=field):
                        broken = json.loads(json.dumps(original))
                        broken['capacity_session'][field] = 'WRONG_ORIGINAL_IDENTITY'
                        write_json_atomic(result_path, broken)
                        with patch.object(owner, 'renew_capacity_session') as renew, patch.object(owner, '_publish') as publish:
                            with self.assertRaisesRegex(ValueError, 'capacity identity differs'):
                                owner.resume_finalization(context, result_path)
                            renew.assert_not_called()
                            publish.assert_not_called()
                        self.assertEqual(authority.read_bytes(), authority_bytes)
                fake = json.loads(json.dumps(original))
                fake.update(stage='complete', manifest=file_record(run/'run_manifest.json', 'required_evidence'))
                write_json_atomic(result_path, fake)
                with self.assertRaisesRegex(ValueError, 'checkpoint source requires'):
                    owner.resume_finalization(context, result_path)
                self.assertEqual(authority.read_bytes(), authority_bytes)
                self.assertEqual(lease_path.read_bytes(), lease_bytes)
                stale = json.loads(json.dumps(original))
                stale['capacity_session']['defer_capacity_finalization'] = 'STALE_TRANSPORT_ONLY'
                write_json_atomic(result_path, stale)
                result = owner.resume_finalization(context, result_path, completion_api=lambda:native_completion)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['stage'], 'complete')
                self.assertEqual(result['exception']['message'], 'ORIGINAL_ACTION_FAILURE')
                self.assertEqual((run/'results/execution_completion.json').read_bytes(), completion)
                self.assertEqual((run/'results/failed-evidence.txt').read_bytes(), b'ORIGINAL_FAILED_EVIDENCE')
                self.assertEqual(calls, ['20261104_120000__test__python__stale-accounting-result'])
                self.assertEqual(load_capacity_protection_leases(context.workspace/'artifacts')['committed_new_bytes'], 0)
                final_bytes = result_path.read_bytes()
                for _ in range(2):
                    with patch.object(owner, 'renew_capacity_session') as renew, patch.object(owner, '_publish') as publish, patch.object(
                            owner, 'exit_capacity_session') as release:
                        self.assertEqual(owner.resume_finalization(context, result_path), result)
                        renew.assert_not_called()
                        publish.assert_not_called()
                        release.assert_not_called()
                    self.assertEqual(result_path.read_bytes(), final_bytes)
                    self.assertEqual(authority.read_bytes(), authority_bytes)
                # Recreate only this private fixture's original lease document:
                # a complete Result cannot override a still-present lease.
                lease_path.write_bytes(lease_bytes)
                try:
                    with self.assertRaisesRegex(ValueError, 'still has an original capacity protection lease'):
                        owner.resume_finalization(context, result_path)
                finally:
                    lease_path.unlink()

    def test_original_accounting_hold_survives_three_masked_resumes_without_recompute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context = ExecutionContext(workspace=root / "study", python_executable=Path(sys.executable),
                powershell_executable=Path(shutil.which("pwsh")), tools={},
                host_state_path=root / "private-host.sqlite3",
                policy_path=resource_path("host_resource_policy.json"))
            budget = root / "budget.json"
            budget.write_text('{"bytes":1048576}', encoding="utf-8")
            snapshots = {}
            calls = []

            def action(session):
                calls.append(session.run_id)
                session.run_process("inert", executable=Path(sys.executable),
                    arguments=["-c", "print('INERT_COMPLETED_ONCE')"], role="GATE",
                    stage="software_tests", limits=None)
                payload = session.declare_file(session.result_dir / "science.txt", "required_evidence")
                payload.write_bytes(b"INERT_OUTPUT_NOT_SOLVER_EVIDENCE")
                session.defer_capacity_finalization("STOPPED_STAGE_ACCOUNTING_FAILURE")
                session.defer_capacity_finalization("MUST_NOT_REPLACE_FIRST_REASON")
                lease = session.artifact_root / "common/capacity_protection_leases" / (
                    session.capacity_session["lease_id"] + ".json")
                for path in (lease, session.artifact_run_dir / "run_manifest.json", payload,
                             session.artifact_run_dir / "logs/capacity_session.json"):
                    snapshots[path] = path.read_bytes()
                raise ValueError("ORIGINAL_SCIENTIFIC_FAILURE")

            policy = dict(_capacity_policy(), target_gib=1, minimum_free_gib=0)
            environment = dict(MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN="",
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_OWNER_PID="",
                MASS_SPECTROMETRY_HOST_EXECUTION_LEASE_ROLE="",
                MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH=str(context.host_state_path))
            with patch.dict(os.environ, environment), patch.object(owner, "_capacity_policy", return_value=policy), patch(
                    "msplatform.execution.capacity_admission._capacity_policy", return_value=policy):
                with self.assertRaisesRegex(ValueError, "ORIGINAL_SCIENTIFIC_FAILURE") as caught:
                    owner.run_managed_stage(context,
                        descriptor=dict(project="instrument_assembly", mode="accounting_fixture", software=[]),
                        run_id="20261104_120000__test__python__accounting-hold", payload={},
                        committed_new_bytes=1048576, commitment_inputs=[file_record(budget, "required_evidence")],
                        retention=dict(policy_version=1, **{"class": "solver_review"}, reason="inert accounting fixture"),
                        expected_operation_ids=["inert"], operation_dependencies={}, action=action,
                        action_record=file_record(Path(__file__), "required_evidence"))
                self.assertTrue(any("STOPPED_STAGE_ACCOUNTING_FAILURE" in note for note in caught.exception.__notes__))
                result_path = next((context.workspace / "artifacts").rglob("result.json"))
                result = json.loads(result_path.read_text())
                run = Path(result["run_directory"])
                completion_path = run / "results/execution_completion.json"
                completion_bytes = completion_path.read_bytes()
                completion = json.loads(completion_bytes)
                observation = completion["writer_completion"]["operations"][0]["observation"]
                self.assertTrue(observation["exit_confirmed"])
                self.assertEqual(observation["returncode"], 0)
                self.assertGreater(observation["process_id"], 0)
                self.assertGreater(observation["process_started_at_utc_ticks"], 0)
                for attempt in range(3):
                    with self.subTest(resume=attempt), patch.object(owner, "renew_capacity_session") as renew, patch.object(
                            owner, "_publish") as publish, patch.object(owner, "exit_capacity_session") as release:
                        masked = json.loads(result_path.read_text())
                        masked["capacity_session"].pop("defer_capacity_finalization", None)
                        if attempt == 2:
                            masked["stage"] = "complete"
                        write_json_atomic(result_path, masked)
                        with self.assertRaisesRegex(owner.CapacityAccountingDeferredError, "STOPPED_STAGE_ACCOUNTING_FAILURE"):
                            owner.resume_finalization(context, result_path)
                        renew.assert_not_called()
                        publish.assert_not_called()
                        release.assert_not_called()
                    result = json.loads(result_path.read_text())
                    self.assertEqual(result["execution_status"], "capacity_accounting_deferred")
                    self.assertEqual(result["resume_action"], "return_to_capacity_accounting_owner")
                    self.assertTrue(result["writers_confirmed"])
                    for key in ("lease_released", "capacity_finalized", "terminal_published"):
                        self.assertFalse(result[key])
                    self.assertEqual(result["exception"]["message"], "ORIGINAL_SCIENTIFIC_FAILURE")
                    self.assertIn("STOPPED_STAGE_ACCOUNTING_FAILURE", " ".join(result["secondary_errors"]))
                    for path, original in snapshots.items():
                        self.assertEqual(path.read_bytes(), original, str(path))
                    self.assertEqual(completion_path.read_bytes(), completion_bytes)
                    self.assertFalse((run / "retention_actions.json").exists())
                self.assertEqual(calls, ["20261104_120000__test__python__accounting-hold"])
                protection = load_capacity_protection_leases(context.workspace / "artifacts")
                self.assertEqual(protection["committed_new_bytes"], 1048576)
                self.assertIn(run.resolve(), protection["protected_paths"])
                ledger = load_capacity_ledger(context.workspace / "artifacts")
                self.assertEqual([row["status"] for row in ledger["objects"]], ["writing"])

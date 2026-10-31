from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from projects.single_reflection_oa_tof_mass_analyzer.analysis.native_stage_completion import append_native_stage_completion


class NativeStageCompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.receipt = Path(temporary.name) / "producer.json"
        self.writer = {"operations": [], "resource_releases": []}

    def publish(self, **changes) -> dict:
        managed = {"schema_version": 1, "role": "repository_managed_python_completion", "exit_code": 0,
                   "worker_process_id": 42, "worker_started_at_utc_ticks": 77}
        managed.update({k: True for k in ("ownership_confirmed", "worker_exit_confirmed", "launcher_exit_confirmed", "stdout_drained", "stderr_drained")})
        value = {"schema_version": 1, "role": "oatof_component_build_completion", "run_id": "new-run", "context_sha256": "A"*64,
                 "operations": [{"operation_id": "refine", "observation": {"exit_confirmed": True, "returncode": 0},
                                 "managed_process_completion": managed}]}
        value.update(changes)
        self.receipt.write_text(json.dumps(value), encoding="utf-8")
        return value

    def consume(self, **kwargs) -> None:
        append_native_stage_completion(self.writer, self.receipt, role="oatof_component_build_completion",
                                       run_id="new-run", context_sha256="A"*64, **kwargs)

    def test_python_and_powershell_owner_keep_their_existing_observation_contracts(self) -> None:
        original = self.publish()
        before = self.receipt.read_bytes()
        self.consume()
        self.assertEqual(self.writer["operations"][0]["observation"], {"exit_confirmed": True, "returncode": 0})
        self.assertEqual(self.writer["resource_releases"][0]["completion_receipt"], original)
        self.writer = {"operations": [], "resource_releases": []}
        self.consume(powershell_owner=True)
        self.assertEqual(self.writer["operations"][0]["observation"], {
            "exit_confirmed": True, "returncode": 0, "process_id": 42, "process_started_at_utc_ticks": 77})
        self.assertEqual(before, self.receipt.read_bytes())

    def test_missing_receipt_retains_unknown_without_inventing_process_identity(self) -> None:
        self.consume(powershell_owner=True)
        self.assertEqual(self.writer["resource_releases"], [])
        self.assertEqual(self.writer["operations"][0]["observation"], {
            "exit_confirmed": False, "returncode": None, "process_id": None, "process_started_at_utc_ticks": None})

    def test_primary_failure_survives_wrong_context_and_records_secondary_error(self) -> None:
        self.publish(context_sha256="B"*64)
        primary = ValueError("original preparation failure")
        with self.assertRaises(ValueError) as caught:
            self.consume(original_failure=primary)
        self.assertIs(caught.exception, primary)
        self.assertIn("scientific context differs", primary.__notes__[0])
        self.assertFalse(self.writer["operations"][-1]["observation"]["exit_confirmed"])

    def test_unconfirmed_worker_is_not_replaced_with_native_success(self) -> None:
        receipt = self.publish()
        receipt["operations"][0]["managed_process_completion"]["worker_exit_confirmed"] = False
        self.publish(operations=receipt["operations"])
        with self.assertRaisesRegex(RuntimeError, "unconfirmed"):
            self.consume()
        self.assertFalse(self.writer["operations"][-1]["observation"]["exit_confirmed"])

    def test_known_nonzero_worker_preserves_real_native_fact_and_release_receipt(self) -> None:
        receipt = self.publish()
        receipt["operations"][0]["managed_process_completion"]["exit_code"] = 3
        receipt["operations"][0]["observation"]["returncode"] = 3
        self.publish(operations=receipt["operations"])
        with self.assertRaisesRegex(RuntimeError, "failed.*3"):
            self.consume(powershell_owner=True)
        self.assertEqual(self.writer["operations"][0]["observation"]["returncode"], 3)
        self.assertEqual(len(self.writer["resource_releases"]), 1)


if __name__ == "__main__":
    unittest.main()

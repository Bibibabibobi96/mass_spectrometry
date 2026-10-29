"""Exercise capacity owners without importing their verifier/maintenance CLIs."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common.contracts import reconcile_artifact_capacity as capacity
from common.contracts.gui_source_protection import current_gui_source_retention


ROOT = Path(__file__).resolve().parents[2]


class SharedArtifactContractTests(unittest.TestCase):
    def test_owner_queries_do_not_import_command_entrypoints(self) -> None:
        """Run a fresh interpreter so earlier imports cannot conceal a cycle."""
        code = '''
import sys,tempfile
from pathlib import Path
sys.modules['common.contracts.verify_artifact_layout']=None
sys.modules['common.contracts.reconcile_artifact_capacity']=None
from common.contracts import capacity_ledger, legacy_capacity_calibration
from common.contracts.solver_review_retirement import _assert_runtime_retirement_unprotected
with tempfile.TemporaryDirectory() as temporary:
    root=Path(temporary)
    _assert_runtime_retirement_unprotected(root,root/'projects/p/runs/source')
    try:
        capacity_ledger.approve_published_cache_retirement(root,path=root/'unregistered',
            expected_identity='a'*64,expected_bytes=1,disposition_id='b'*64,
            manifest_sha256='c'*64,files=[dict(path='payload.pa',bytes=1,sha256='d'*64)],
            expected_project_owner='p')
    except ValueError as error:
        assert 'registered exact owner namespace' in str(error),str(error)
    else:
        raise AssertionError('unregistered cache accepted')
'''
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_new_gui_receipt_is_visible_to_each_owner_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / "projects/p/runs/source"
            run.mkdir(parents=True)
            (run / "run_manifest.json").write_text('{"status":"checkpoint"}', encoding="utf-8")
            ledger = {"objects": [{"path": "projects/p/runs/source", "status": "writing",
                "bytes": 1, "owner": "p", "recovery_reason": "run_manifest_not_terminal"}]}
            leases = {"protected_paths": set(), "protected_cache_keys": set()}

            def classification() -> str:
                return capacity._historical_closure_summary(root, ledger, leases)[0]["classification"]

            self.assertFalse(current_gui_source_retention(root, run))
            self.assertEqual(classification(), "workflow_checkpoint_requires_owner_decision")
            review = root / "projects/p/reviews/current_gui"
            review.mkdir(parents=True)
            receipt = review / "inspection_receipt.json"
            receipt.write_text(json.dumps({"status": "ready", "source_run": "source"}), encoding="utf-8")
            self.assertTrue(current_gui_source_retention(root, run))
            self.assertEqual(classification(), "normal_managed_retention")
            receipt.unlink()
            self.assertFalse(current_gui_source_retention(root, run))
            self.assertEqual(classification(), "workflow_checkpoint_requires_owner_decision")


if __name__ == "__main__":
    unittest.main()

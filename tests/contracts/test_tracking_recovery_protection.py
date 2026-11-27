"""Real stopped Store unit evidence remains guarded during public replay admission."""
import copy
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from msplatform.backends.simion.tracking_units import inspect_tracking_recovery
from msplatform.execution.native_source_guard import guard_tracking_recovery
from msplatform.io.manifest_records import file_record
from tests.contracts.test_support.tracking_recovery_store_fixture import create_stopped_tracking


@unittest.skipUnless(os.name == "nt", "Windows file identity guard is required")
class TrackingRecoveryProtectionTests(unittest.TestCase):
    def test_failed_and_interrupted_units_are_held_and_revalidated(self):
        ledger = Path("C:/Users/Liao/mass_spectrometry/artifacts/platform/host_resources.sqlite3")
        if not ledger.is_file():
            self.skipTest("shared host ledger is unavailable")
        from tests.contracts import test_simion_tracking_execution as fixture
        case = fixture.TrackingExecutionPlanTests()
        case.setUp()
        plan = case.plan(unit_size=50)
        with patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(ledger),
                                     "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": ""}):
            for status in ("failed", "interrupted"):
                with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                    store, manifest, context = create_stopped_tracking(Path(directory), plan, status=status)
                    with guard_tracking_recovery(store, manifest, raw_root=context.workspace / "artifacts", asset_ids=set()):
                        admitted = inspect_tracking_recovery(plan, manifest)
                        self.assertEqual(admitted["reused_unit_keys"], ["unit_0001"])
                        index = Path(admitted["index_path"])
                        with self.assertRaises(PermissionError):
                            index.unlink()
                    index.unlink()
                    with self.assertRaises((ValueError, OSError)):
                        with guard_tracking_recovery(store, manifest, raw_root=context.workspace / "artifacts", asset_ids=set()):
                            pass

    def test_shared_input_output_identity_is_consistent_and_existing(self):
        ledger = Path("C:/Users/Liao/mass_spectrometry/artifacts/platform/host_resources.sqlite3")
        if not ledger.is_file():
            self.skipTest("shared host ledger is unavailable")
        from tests.contracts import test_simion_tracking_execution as fixture
        from tests.contracts.test_support import tracking_recovery_store_fixture as store_fixture
        case = fixture.TrackingExecutionPlanTests()
        case.setUp()
        plan = case.plan(unit_size=50)
        actual_action = store_fixture.stopped_tracking_action

        def shared_input_output_action(session, *, plan, status):
            result = actual_action(session, plan=plan, status=status)
            shared = file_record(session.canonical_path(session.input_dir / "inert_tracking.json"),
                                 "required_evidence")
            result["output_paths"].append(shared["path"])
            result["required_output_paths"].append(shared["path"])
            return result

        with patch.dict(os.environ, {"MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(ledger),
                                     "MASS_SPECTROMETRY_HOST_RESOURCE_TOKEN": ""}), \
                tempfile.TemporaryDirectory() as directory:
            with patch.object(store_fixture, "stopped_tracking_action", new=shared_input_output_action), \
                    patch.object(store_fixture, "__file__", str(Path(__file__).resolve())):
                store, manifest, context = create_stopped_tracking(Path(directory), plan, status="success")
            manifest_path = Path(manifest["path"])
            document = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            shared = document["inputs"]["inert_payload"]
            self.assertEqual(document["outputs"].count(shared), 1)
            assets = set()
            with guard_tracking_recovery(store, manifest, raw_root=context.workspace / "artifacts", asset_ids=assets):
                admitted = inspect_tracking_recovery(plan, manifest)
                self.assertEqual(admitted["reused_unit_keys"], ["unit_0001"])
                with self.assertRaises(PermissionError):
                    Path(shared["path"]).unlink()
            self.assertTrue(assets)

            def assert_rejected(value, name, error, match):
                alternate = manifest_path.with_name(name + ".json")
                alternate.write_text(json.dumps(value), encoding="utf-8")
                with patch("msplatform.execution.native_source_guard.guard_native_source",
                           return_value=nullcontext()), self.assertRaisesRegex(error, match):
                    with guard_tracking_recovery(store, file_record(alternate),
                                                 raw_root=context.workspace / "artifacts"):
                        pass

            for field, changed in (("bytes", shared["bytes"] + 1), ("sha256", "0" * 64),
                                   ("retention_role", "solver_native_binary")):
                with self.subTest(conflict=field):
                    conflict = copy.deepcopy(document)
                    conflict["outputs"] = [dict(row, **{field: changed}) if row == shared else row
                                           for row in conflict["outputs"]]
                    assert_rejected(conflict, "conflict_" + field, ValueError, "conflicting file identity")
            Path(shared["path"]).unlink()
            assert_rejected(document, "missing", FileNotFoundError, "inert_tracking.json")

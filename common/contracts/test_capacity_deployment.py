"""Explicit deployment capacity policies over the existing owner and shared leases."""
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from msplatform.execution import capacity_protection as protection
from msplatform.execution import capacity_admission as admission, capacity_session as sessions, owner
from msplatform.execution.context import load_environment
from msplatform.execution.capacity_ledger import initialize_capacity_ledger
from msplatform.io.manifest_records import file_record
from common.contracts import test_execution_runtime as runtime


def declared_action(session):
    path = session.declare_file(session.result_dir / "evidence.txt", "required_evidence")
    path.write_text("actual owner software evidence", encoding="utf-8")
    return dict(status="success", summary={}, output_paths=[str(path)], required_output_paths=[str(path)],
                retention_preserve_paths=[], manifest_extra_fields={})


class _CapacityClock(datetime):
    """Controlled wall clock for the real protection implementation."""
    current = datetime(2026, 1, 1, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz)


class CapacityDeploymentTests(unittest.TestCase):
    def policy(self, root, reserve=0):
        path = root / "deployment-policy.json"
        value = dict(admission._capacity_policy(), target_gib=1, minimum_free_gib=reserve)
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_default_identity_and_saved_environment_explicit_path(self):
        self.assertEqual(admission._capacity_policy()["minimum_free_gib"], 295)
        self.assertEqual(admission._capacity_policy()["target_gib"], 700)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = runtime.NormalOwnerTests()._context(root)
            policy = self.policy(root)
            config = dict(schema_version=1, role="execution_environment",
                tools=dict(python=str(base.python_executable), powershell=str(base.powershell_executable)),
                policy=dict(host_state_path=str(base.host_state_path), capacity_policy_path=str(policy)),
                profiles=dict(local=dict(stage_policy_path=str(root / "stages.json"))))
            context = load_environment(config, workspace=base.workspace, profile="local")
            self.assertEqual(context.capacity_policy_path, policy)
            self.assertEqual(context.host_state_path, base.host_state_path)
            self.assertFalse(base.workspace.exists())
            self.assertFalse(base.host_state_path.exists())

    def test_two_captured_policies_do_not_reread_changed_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = self.policy(root)
            first = admission.capture_capacity_policy(path)
            path.write_text(json.dumps(dict(first["snapshot"], minimum_free_gib=2)), encoding="utf-8")
            second = admission.capture_capacity_policy(path)
            self.assertEqual(sessions.selected_capacity_policy(dict(capacity_policy=first))["minimum_free_gib"], 0)
            self.assertEqual(sessions.selected_capacity_policy(dict(capacity_policy=second))["minimum_free_gib"], 2)
            self.assertNotEqual(first["source_record"]["sha256"], second["source_record"]["sha256"])
            changed = copy.deepcopy(first)
            changed["snapshot"]["minimum_free_gib"] = 9
            with self.assertRaisesRegex(ValueError, "snapshot differs"):
                sessions.selected_capacity_policy(dict(capacity_policy=changed))

    def test_actual_owner_freezes_policy_and_completed_replay_never_reads_new_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = runtime.NormalOwnerTests()
            path = self.policy(root)
            context = replace(helper._context(root), capacity_policy_path=path)
            args = helper._arguments(root, declared_action)
            args["action_record"] = file_record(Path(__file__), "required_evidence")
            result = owner.run_managed_stage(context, **args)
            run = Path(result["run_directory"])
            captured = json.loads((run / "logs/capacity_session.json").read_text())
            self.assertEqual(captured["capacity_policy"]["snapshot"]["minimum_free_gib"], 0)
            self.assertEqual(Path(captured["capacity_policy"]["frozen_record"]["path"]), run / "inputs/capacity_policy.json")
            before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob("*") if p.is_file()}
            path.write_text("now invalid deployment", encoding="utf-8")
            resumed = owner.resume_finalization(context, context.workspace / "artifacts/projects/instrument_assembly/scratch/workflow_results" / args["run_id"] / "result.json")
            self.assertEqual(resumed, result)
            self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob("*") if p.is_file()})

    def test_legacy_same_commitment_renewal_and_explicit_increase_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_capacity_ledger(root, objects=[])
            _CapacityClock.current = datetime(2026, 1, 1, tzinfo=timezone.utc)
            with patch.object(protection, "datetime", _CapacityClock):
                session = sessions.create_capacity_session(root, root / "runs/legacy", owner="legacy", committed_new_bytes=10)
                try:
                    _CapacityClock.current += timedelta(milliseconds=1)
                    sessions.renew_capacity_session(session)
                    self.assertNotIn("capacity_policy", session)
                    with self.assertRaisesRegex(ValueError, "current-phase policy authority"):
                        sessions.renew_capacity_session(session, remaining_committed_new_bytes=11)
                    self.assertEqual(session["committed_new_bytes"], 10)
                finally:
                    sessions.exit_capacity_session(session)

    def test_session_refresh_keeps_expiry_on_same_or_backward_clock_and_admits_scope_changes(self):
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, patch.object(protection, "datetime", _CapacityClock):
            root = Path(directory)
            initialize_capacity_ledger(root, objects=[])
            policy = admission.capture_capacity_policy(self.policy(root))
            _CapacityClock.current = started
            session = sessions.create_capacity_session(root, root / "runs/active", owner="clock",
                committed_new_bytes=10, lease_ttl_seconds=60, protected_cache_keys=["a" * 64], capacity_policy=policy)
            try:
                original_creation = session["lease"]["created_at_utc"]
                original_deadline = session["lease"]["closure_deadline_at_utc"]
                for delta, expected_expiry in ((timedelta(0), "2026-01-01T00:01:00Z"),
                        (timedelta(milliseconds=-1), "2026-01-01T00:01:00Z"),
                        (timedelta(milliseconds=1), "2026-01-01T00:01:00.001000Z"),
                        (timedelta(seconds=1), "2026-01-01T00:01:01Z")):
                    with self.subTest(clock_delta=delta):
                        _CapacityClock.current = started + delta
                        result = sessions.renew_capacity_session(session)
                        self.assertEqual(result["expires_at_utc"], expected_expiry)
                        self.assertEqual(result["created_at_utc"], original_creation)
                        self.assertEqual(result["committed_new_bytes"], 10)
                # Same-tick scope/commitment changes still traverse actual admission.
                result = sessions.renew_capacity_session(session, remaining_committed_new_bytes=11,
                    protected_paths=[root / "runs/additional"], protected_cache_keys=["b" * 64])
                self.assertEqual(result["expires_at_utc"], expected_expiry)
                self.assertEqual(result["protected_cache_keys"], ["a" * 64, "b" * 64])
                self.assertIn("runs/active", result["protected_paths"])
                self.assertIn("runs/additional", result["protected_paths"])
                self.assertEqual(session["committed_new_bytes"], 11)
                self.assertTrue(session["startup_gate"]["satisfied"])
                result = sessions.renew_capacity_session(session, remaining_committed_new_bytes=8)
                self.assertEqual(result["committed_new_bytes"], 8)
                self.assertEqual(result["closure_deadline_at_utc"], original_deadline)
            finally:
                sessions.exit_capacity_session(session)

    def test_session_refresh_checks_real_source_lease_clock_and_preserves_owner_expiry_and_bootstrap_guards(self):
        started = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory, patch.object(protection, "datetime", _CapacityClock):
            base = Path(directory)
            root, source = base / "target", base / "source"
            root.mkdir(); source.mkdir()
            initialize_capacity_ledger(root, objects=[])
            initialize_capacity_ledger(source, objects=[])
            _CapacityClock.current = started
            session = sessions.create_capacity_session(root, root / "runs/active", owner="clock", committed_new_bytes=10, lease_ttl_seconds=60)
            source_lease = protection.create_capacity_protection_lease(source, lease_id="actual-source", owner="clock",
                ttl_seconds=60, protected_paths=[source / "runs/input"], committed_new_bytes=0)
            session["source_protection_leases"].append(dict(artifact_root=str(source), lease_id=source_lease["lease_id"], status="active",
                protected_paths=[str(source / "runs/input")], protected_cache_keys=[]))
            lease_path = Path(session["lease"]["path"])
            try:
                before = lease_path.read_bytes()
                sessions.renew_capacity_session(session)
                self.assertEqual(lease_path.read_bytes(), before)
                self.assertEqual(protection.load_capacity_protection_leases(source)["audit"][0]["expires_at_utc"], source_lease["expires_at_utc"])
                session["owner"] = "different-owner"
                with self.assertRaisesRegex(ValueError, "owner differs"):
                    sessions.renew_capacity_session(session)
                self.assertEqual(lease_path.read_bytes(), before)
                session["owner"] = "clock"
                # Missing-ledger bootstrap still cannot expand scope at the same tick.
                (root / "common/capacity_ledger.json").unlink()
                with self.assertRaisesRegex(ValueError, "bootstrap lease renewal cannot expand"):
                    sessions.renew_capacity_session(session, protected_paths=[root / "other"])
                self.assertEqual(lease_path.read_bytes(), before)
                _CapacityClock.current = started + timedelta(seconds=60)
                with self.assertRaisesRegex(ValueError, "expired"):
                    sessions.renew_capacity_session(session)
                self.assertEqual(lease_path.read_bytes(), before)
            finally:
                session["owner"] = "clock"
                sessions.exit_capacity_session(session)

    def test_refresh_preserves_strict_explicit_renewal_and_immutable_closure_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_capacity_ledger(root, objects=[])
            started = datetime(2026, 1, 1, tzinfo=timezone.utc)
            created = protection.create_capacity_protection_lease(root, lease_id="bounded", owner="clock", ttl_seconds=60,
                protected_paths=[root / "protected"], closure_deadline_at_utc=(started + timedelta(seconds=60)).isoformat(), now=started)
            before = Path(created["path"]).read_bytes()
            with self.assertRaisesRegex(ValueError, "must extend its expiry"):
                protection.renew_capacity_protection_lease(root, lease_id="bounded", owner="clock", ttl_seconds=60, now=started)
            self.assertEqual(Path(created["path"]).read_bytes(), before)
            refreshed = protection.refresh_capacity_protection_lease(root, lease_id="bounded", owner="clock", ttl_seconds=60, now=started)
            self.assertEqual(refreshed["expires_at_utc"], created["expires_at_utc"])
            self.assertEqual(refreshed["closure_deadline_at_utc"], created["closure_deadline_at_utc"])
            with self.assertRaisesRegex(ValueError, "beyond its closure deadline"):
                protection.refresh_capacity_protection_lease(root, lease_id="bounded", owner="clock", ttl_seconds=60, now=started + timedelta(seconds=1))
            self.assertEqual(Path(created["path"]).read_bytes(), before)

    def test_selected_reserve_still_blocks_real_admission_and_cleans_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initialize_capacity_ledger(root, objects=[])
            path = self.policy(root, reserve=10**9)
            with self.assertRaises(sessions.CapacityAdmissionError) as caught:
                sessions.enter_capacity_session(root, root / "runs/blocked", owner="explicit", committed_new_bytes=1,
                    capacity_policy=admission.capture_capacity_policy(path))
            self.assertEqual(caught.exception.receipt["blocking_reason"], "MINIMUM_FREE_CAPACITY_UNAVAILABLE")
            self.assertEqual(caught.exception.capacity_lease_cleanup["status"], "released")

    def test_frozen_copy_tamper_is_rejected_without_reading_deployment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.policy(root)
            captured = admission.capture_capacity_policy(source)
            frozen = root / "frozen.json"
            frozen.write_text(json.dumps(captured["snapshot"]), encoding="utf-8")
            captured["frozen_record"] = file_record(frozen, "required_evidence")
            source.write_text("deployment now changed", encoding="utf-8")
            self.assertEqual(sessions.selected_capacity_policy(dict(capacity_policy=captured))["minimum_free_gib"], 0)
            frozen.write_text(json.dumps(dict(captured["snapshot"], target_gib=2)), encoding="utf-8")
            with self.assertRaisesRegex(AssertionError, "manifest frozen capacity policy .* changed"):
                sessions.selected_capacity_policy(dict(capacity_policy=captured))

    def test_invalid_selected_policy_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            path.write_text('{"schema_version": 2}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "fields differ"):
                admission.capture_capacity_policy(path)

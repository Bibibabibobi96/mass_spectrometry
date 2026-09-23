from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from common.contracts import capacity_ledger, capacity_protection, legacy_owner_disposition
from common.contracts.run_capacity_lifecycle import resume_partial_retirements


class OwnerDispositionAuthoringTests(unittest.TestCase):
    def _run(self, root: Path, name: str = "abandoned") -> tuple[Path, Path, Path]:
        run = root / "projects" / "instrument" / "runs" / name
        run.mkdir(parents=True)
        (run / "run_config.json").write_text('{"source":"fixture"}\n', encoding="utf-8")
        preserved = run / "summary.json"
        preserved.write_text('{"result":"keep"}\n', encoding="utf-8")
        heavy = run / "simion" / "field.pa0"
        heavy.parent.mkdir()
        heavy.write_bytes(b"rebuildable payload")
        (run / "run_manifest.json").write_text(json.dumps({"outputs": [{
            "path": "simion/field.pa0", "bytes": heavy.stat().st_size, "sha256": "A" * 64,
        }]}), encoding="utf-8")
        return run, heavy, preserved

    def _initialize(self, root: Path, run: Path, heavy: Path, preserved: Path, **extra: object) -> None:
        capacity_ledger.initialize_capacity_ledger(root, objects=[
            {"path": heavy.relative_to(root).as_posix(), "class": "rebuildable_payload",
             "bytes": heavy.stat().st_size, "status": "writing", "pin": False,
             "owner": "instrument", "recovery_reason": "run_contract_missing_or_invalid",
             "review_deadline": "2026-10-22", **extra},
            {"path": preserved.relative_to(root).as_posix(), "class": "light_evidence",
             "bytes": preserved.stat().st_size, "status": "writing", "pin": False,
             "owner": "instrument", "recovery_reason": "run_contract_missing_or_invalid",
             "review_deadline": "2026-10-22"},
        ], external_scopes=[])

    def _author(self, root: Path, run: Path) -> dict[str, object]:
        return legacy_owner_disposition.author_owner_disposition(
            root, target_path=run.relative_to(root).as_posix(),
            authority_evidence_path=(run / "run_config.json").relative_to(root).as_posix(),
        )

    def test_partial_authorization_marks_only_heavy_file_for_existing_executor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, preserved = self._run(root)
            self._initialize(root, run, heavy, preserved)
            ledger_before = (root / "common" / "capacity_ledger.json").read_bytes()
            created = self._author(root, run)
            document_path = Path(str(created["document_path"]))
            document = json.loads(document_path.read_text(encoding="utf-8"))
            self.assertEqual(document["scope"], "partial_run_heavy_files")
            self.assertEqual(document["disposition"]["files"], [{
                "path": "simion/field.pa0", "bytes": heavy.stat().st_size,
            }])
            self.assertEqual((root / "common" / "capacity_ledger.json").read_bytes(), ledger_before)
            self.assertFalse(self._author(root, run)["created"])

            self.assertEqual(legacy_owner_disposition.activate_owner_dispositions(root)["activated_count"], 1)
            by_path = {item["path"]: item for item in capacity_ledger.load_capacity_ledger(root)["objects"]}
            self.assertEqual(by_path[heavy.relative_to(root).as_posix()]["recovery_task"], "explicit_user_authorized_abandonment")
            self.assertNotIn("recovery_task", by_path[preserved.relative_to(root).as_posix()])
            self.assertEqual(resume_partial_retirements(root)["completed_count"], 1)
            self.assertFalse(heavy.exists())
            self.assertTrue(preserved.exists())
            self.assertTrue(document_path.exists())

    def test_rejects_whole_range_and_missing_manifest_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, _ = self._run(root)
            capacity_ledger.initialize_capacity_ledger(root, objects=[{
                "path": run.relative_to(root).as_posix(), "class": "rebuildable_payload",
                "bytes": sum(item.stat().st_size for item in run.rglob("*") if item.is_file()),
                "status": "writing", "pin": False, "owner": "instrument",
                "recovery_reason": "run_contract_missing_or_invalid", "review_deadline": "2026-10-22",
            }], external_scopes=[])
            with self.assertRaisesRegex(ValueError, "no classified eligible heavy ledger file"):
                self._author(root, run)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, preserved = self._run(root)
            self._initialize(root, run, heavy, preserved)
            (run / "run_manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "lacks one manifest identity"):
                self._author(root, run)

    def test_rejects_active_lease_pin_and_consumer(self) -> None:
        for case in ("lease", "pin", "consumer"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "artifacts"
                run, heavy, preserved = self._run(root)
                extra: dict[str, object] = {}
                if case == "pin":
                    extra = {"pin": True, "pin_reason": "must retain"}
                if case == "consumer":
                    consumer = root / "projects" / "instrument" / "runs" / "consumer"
                    consumer.mkdir(parents=True)
                    extra = {"consumers": [consumer.relative_to(root).as_posix()]}
                self._initialize(root, run, heavy, preserved, **extra)
                if case == "consumer":
                    capacity_ledger.record_capacity_object(
                        root, path=consumer, object_class="rebuildable_payload", bytes_count=0,
                        status="writing", owner="instrument",
                        recovery_reason="run_contract_missing_or_invalid", review_deadline="2026-10-22",
                    )
                if case == "lease":
                    capacity_protection.create_capacity_protection_lease(
                        root, lease_id="protect-run", owner="fixture", ttl_seconds=300,
                        protected_paths=[heavy],
                    )
                with self.assertRaisesRegex(ValueError, "(eligible owner-managed|active protection)"):
                    self._author(root, run)

    def test_rejects_gui_pa_and_evidence_outside_exact_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, _, _ = self._run(root)
            review = root / "projects" / "instrument" / "reviews"
            review.mkdir(parents=True)
            (review / "iob.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "evidence must be a regular file in the target"):
                legacy_owner_disposition.author_owner_disposition(
                    root, target_path=run.relative_to(root).as_posix(),
                    authority_evidence_path=(review / "iob.json").relative_to(root).as_posix(),
                )
            with self.assertRaisesRegex(ValueError, "exact project run"):
                legacy_owner_disposition.author_owner_disposition(
                    root, target_path=review.relative_to(root).as_posix(),
                    authority_evidence_path=(review / "iob.json").relative_to(root).as_posix(),
                )

    def test_cli_replays_sealed_authorization(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "artifacts"
            run, heavy, preserved = self._run(root)
            self._initialize(root, run, heavy, preserved)
            arguments = ["--workspace-root", str(root), "--target-path", run.relative_to(root).as_posix(),
                         "--authority-evidence-path", (run / "run_config.json").relative_to(root).as_posix()]
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(legacy_owner_disposition.main(arguments), 0)
            self.assertTrue(json.loads(stdout.getvalue())["created"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(legacy_owner_disposition.main(arguments), 0)


if __name__ == "__main__":
    unittest.main()

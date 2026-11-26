"""Small, real filesystem and process checks for dedicated store ownership."""
from __future__ import annotations

from multiprocessing import get_context
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import hashlib
import os
import subprocess
from threading import Barrier
import unittest
from unittest.mock import patch

from msplatform.storage import ArtifactStore


def _claim_worker(root: str, identity: str, ready, release) -> None:
    store = ArtifactStore(root)
    with store.claim(identity):
        ready.set()
        if not release.wait(20):
            raise RuntimeError("parent failed to release claim")


def _crash_worker(root: str, identity: str, ready) -> None:
    store = ArtifactStore(root)
    with store.claim(identity), store.reserve(8):
        ready.set()
        os._exit(0)


def _running_worker(root: str, identity: str, ready, release, result) -> None:
    store = ArtifactStore(root)
    run, work = store.begin_run()
    (work / "resolved.json").write_text('{"input": 1}', encoding="utf-8")
    (work / "evidence.txt").write_text("partial", encoding="utf-8")
    with store.run_writer(run):
        store.mark_running(run)
        with store.claim(identity), store.reserve(8):
            result.send((run, str(work)))
            ready.set()
            release.wait(30)
            store.finish_run(run, "cancelled", reason="test complete")


class ArtifactStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ArtifactStore(Path(self.temp.name) / "store")

    def asset(self, key: str, content: bytes = b"abc") -> str:
        work = self.store.new_work()
        (work / "data").write_bytes(content)
        return self.store.put_asset("field", key, work)

    def test_shared_required_reference_and_claim_survive_collection(self) -> None:
        identity = self.asset("same")
        for _ in range(2):
            work = self.store.new_work()
            (work / "result").write_text("ok", encoding="utf-8")
            run, _ = self.store.publish_run(work, required_assets=(identity,))
            self.assertTrue(self.store.inspect_run(run).exists())
        self.assertEqual(self.store.collect(100)["released_bytes"], 0)
        self.assertEqual(self.store.find_asset("same")[0], identity)

    def test_process_claim_competes_with_gc_without_sleep(self) -> None:
        identity = self.asset("protected")
        context = get_context("spawn")
        ready, release = context.Event(), context.Event()
        process = context.Process(target=_claim_worker, args=(str(self.store.root), identity, ready, release))
        process.start()
        try:
            self.assertTrue(ready.wait(20))
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
        finally:
            release.set()
            process.join(20)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(self.store.collect(100)["released_bytes"], 3)
        self.assertIsNone(self.store.find_asset("protected"))

    def test_missing_member_is_miss_and_other_asset_remains(self) -> None:
        first = self.asset("first")
        second = self.asset("second", b"other")
        path = self.store.find_asset("first")[1]
        (path / "data").unlink()
        self.assertIsNone(self.store.find_asset("first"))
        self.assertEqual(self.store.find_asset("second")[0], second)
        self.assertNotEqual(first, second)

    def test_soft_pressure_and_physical_capacity(self) -> None:
        self.store.high, self.store.low = 0, 0
        self.asset("discard")
        with self.store.reserve(0):
            self.assertIsNone(self.store.find_asset("discard"))
        with patch("msplatform.storage.store.shutil.disk_usage") as disk:
            disk.return_value = type("Usage", (), {"free": 0})()
            with self.assertRaises(OSError):
                with self.store.reserve(1):
                    pass

    def test_resume_delete_pending_and_publish_after_interruption(self) -> None:
        identity = self.asset("pending")
        with self.store._transaction() as db:
            db.execute("UPDATE assets SET state='delete_pending' WHERE id=?", (identity,))
        with self.assertRaises(KeyError):
            with self.store.claim(identity):
                self.fail("a pending deletion must not gain a new claim")
        with self.assertRaises(KeyError):
            self.store.pin(identity)
        self.assertEqual(self.store.collect()["released_bytes"], 3)
        work = self.store.new_work()
        (work / "payload").write_bytes(b"x")
        from msplatform.storage.store import _records
        import json
        (work / "run_manifest.json").write_text(json.dumps({"schema_version": 1, "run_id": "interrupted", "files": _records(work)}), encoding="utf-8")
        records = json.dumps(_records(work), sort_keys=True)
        with self.store._transaction() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", ("interrupted", "runs/2026/11/interrupted", "publishing", records, work.name))
        self.assertEqual(self.store.recover_publications(), ["interrupted"])
        self.assertTrue((self.store.inspect_run("interrupted") / "payload").exists())

    def test_failed_removal_is_not_credited_and_is_retried(self) -> None:
        self.asset("locked")
        with patch("msplatform.storage.store.shutil.rmtree", side_effect=PermissionError("locked")):
            report = self.store.collect(3)
        self.assertEqual(report["released_bytes"], 0)
        self.assertEqual(len(report["failures"]), 1)
        self.assertEqual(self.store.collect()["released_bytes"], 3)

    def test_reserve_continues_after_locked_cache_and_preserves_protected(self) -> None:
        locked = self.asset("locked", b"aaa")
        removable = self.asset("removable", b"123456")
        pinned = self.asset("pinned", b"p")
        claimed = self.asset("claimed", b"c")
        self.store.pin(pinned)
        locked_path = self.store.find_asset("locked")[1]
        removable_path = self.store.find_asset("removable")[1]
        from shutil import rmtree

        def remove(path):
            if path == locked_path:
                raise PermissionError("locked")
            rmtree(path)

        def disk_usage(_path):
            return type("Usage", (), {"free": 0 if removable_path.exists() else 6})()

        with self.store.claim(claimed), patch("msplatform.storage.store.shutil.rmtree", side_effect=remove), \
                patch("msplatform.storage.store.shutil.disk_usage", side_effect=disk_usage):
            with self.store.reserve(5):
                self.assertFalse(removable_path.exists())
                self.assertIsNotNone(self.store.find_asset("pinned"))
                self.assertIsNotNone(self.store.find_asset("claimed"))
        with self.store._db() as db:
            states = dict(db.execute("SELECT id,state FROM assets"))
            failure = db.execute("SELECT failure FROM assets WHERE id=?", (locked,)).fetchone()[0]
        self.assertEqual(states[locked], "delete_pending")
        self.assertEqual(states[removable], "deleted")
        self.assertEqual(states[pinned], "ready")
        self.assertEqual(states[claimed], "ready")
        self.assertIn("locked", failure)

    def test_failed_candidates_are_attempted_once_per_pass(self) -> None:
        first = self.asset("first")
        second = self.asset("second")
        with patch("msplatform.storage.store.shutil.rmtree", side_effect=PermissionError("locked")) as remove:
            result = self.store.collect(100)
            self.assertEqual(remove.call_count, 2)
            self.assertEqual(result["released_bytes"], 0)
            self.assertEqual({f["asset_id"] for f in result["failures"]}, {first, second})
            again = self.store.collect(100)
            self.assertEqual(remove.call_count, 4)
            self.assertEqual(again["released_bytes"], 0)
            self.assertEqual(len(again["failures"]), 2)

    def test_cache_claim_covers_validation_and_consumer_lifetime(self) -> None:
        work = self.store.new_work()
        (work / "data").write_bytes(b"abc")
        with self.store.put_asset_claimed("field", "held", work) as (identity, path):
            self.assertEqual((path / "data").read_bytes(), b"abc")
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
        with self.store.claim_key("held") as hit:
            self.assertEqual(hit[0], identity)
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
        self.assertEqual(self.store.collect(100)["released_bytes"], 3)
        with self.store.claim_key("held") as miss:
            self.assertIsNone(miss)

    def test_concurrent_same_key_publications_do_not_overwrite(self) -> None:
        barrier = Barrier(2)

        def publish(content: bytes):
            work = self.store.new_work()
            (work / "data").write_bytes(content)
            barrier.wait(10)
            with self.store.put_asset_claimed("field", "shared_key", work) as result:
                identity, path = result
                return identity, (path / "data").read_bytes(), path

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(publish, (b"first", b"second")))
        self.assertNotEqual(results[0][0], results[1][0])
        self.assertEqual({r[1] for r in results}, {b"first", b"second"})
        self.assertTrue(all(path.exists() for _, _, path in results))

    def test_lookup_losing_to_collection_returns_miss(self) -> None:
        self.asset("race")
        claim = self.store.claim

        def collect_before_claim(identity):
            self.store.collect(100)
            return claim(identity)

        with patch.object(self.store, "claim", side_effect=collect_before_claim):
            with self.store.claim_key("race") as result:
                self.assertIsNone(result)

    def test_manifest_and_private_work_disposal(self) -> None:
        import json
        work = self.store.new_work()
        (work / "payload").write_bytes(b"data")
        run, path = self.store.publish_run(work)
        manifest = json.loads((path / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["run_id"], run)
        self.assertEqual(manifest["files"]["payload"]["bytes"], 4)
        self.assertEqual(self.store.inspect_run(run), path)
        other = ArtifactStore(self.store.root)
        disposable = self.store.new_work()
        (disposable / "temporary").write_bytes(b"123")
        with self.assertRaises(ValueError):
            other.discard_work(disposable)
        self.assertEqual(self.store.discard_work(disposable), 3)
        self.assertFalse(disposable.exists())

    def test_execution_state_and_fixed_run_identity(self) -> None:
        run, work = self.store.begin_run()
        self.assertEqual(self.store.run_status(run)["execution_status"], "queued")
        self.store.set_queued_reason(run, "capacity")
        self.assertEqual(self.store.run_status(run)["reason"], "capacity")
        with self.store.run_writer(run):
            self.store.mark_running(run)
            self.assertEqual(self.store.run_status(run)["execution_status"], "running")
            (work / "result").write_bytes(b"result")
            published, _ = self.store.publish_run(work, run_id=run, execution_status="cancelled")
        self.assertEqual(published, run)
        self.assertEqual(self.store.run_status(run)["execution_status"], "cancelled")
        self.assertEqual(self.store.run_status(run)["publication_status"], "ready")

    def test_terminated_running_writer_recovers_once_without_touching_live_or_ready(self) -> None:
        identity = self.asset("running-control")
        published_work = self.store.new_work()
        (published_work / "result").write_bytes(b"complete")
        completed, completed_path = self.store.publish_run(published_work)
        context = get_context("spawn")
        workers = []
        for _ in range(2):
            ready, release = context.Event(), context.Event()
            receive, send = context.Pipe(duplex=False)
            process = context.Process(target=_running_worker, args=(str(self.store.root), identity, ready, release, send))
            process.start()
            workers.append((process, ready, release, receive))
        try:
            for process, ready, _, _ in workers:
                self.assertTrue(ready.wait(20), f"writer {process.pid} did not start")
            dead_run, work_name = workers[0][3].recv()
            live_run, _ = workers[1][3].recv()
            work = Path(work_name)
            before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in work.iterdir()}
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            workers[0][0].terminate()
            workers[0][0].join(20)
            self.assertFalse(workers[0][0].is_alive())
            self.assertEqual(self.store.recover_interrupted_runs(), [dead_run])
            self.assertEqual(self.store.recover_interrupted_runs(), [])
            status = self.store.run_status(dead_run)
            self.assertEqual(status["execution_status"], "failed")
            self.assertEqual(status["publication_status"], "unpublished")
            self.assertIn("interrupted", status["reason"])
            after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in work.iterdir()}
            self.assertEqual(after, before)
            self.assertEqual((work / "resolved.json").read_text(encoding="utf-8"), '{"input": 1}')
            self.assertEqual((work / "evidence.txt").read_text(encoding="utf-8"), "partial")
            self.assertFalse((work / "terminal_states.parquet").exists())
            self.assertEqual(self.store.run_status(live_run)["execution_status"], "running")
            self.assertEqual(self.store.run_status(completed)["execution_status"], "succeeded")
            self.assertEqual(self.store.inspect_run(completed), completed_path)
            with self.store._db() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM claims").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM assets WHERE state='ready'").fetchone()[0], 1)
            with self.store.reserve(8):
                pass
        finally:
            for process, _, release, _ in workers:
                if process.is_alive():
                    release.set()
                    process.join(20)
                    if process.is_alive():
                        process.terminate()
                        process.join(20)

    def test_publication_interruption_recovers_after_failure_recorded(self) -> None:
        run, work = self.store.begin_run()
        (work / "result").write_bytes(b"complete")
        with self.store.run_writer(run):
            self.store.mark_running(run)
            with patch("msplatform.storage.store.os.replace", side_effect=OSError("publication interrupted")):
                with self.assertRaises(OSError):
                    self.store.publish_run(work, run_id=run)
        self.assertEqual(self.store.run_status(run)["publication_status"], "publishing")
        self.assertEqual(self.store.recover_interrupted_runs(), [])
        self.assertEqual(self.store.run_status(run)["execution_status"], "running")
        self.store.finish_run(run, "failed", reason="publication interrupted")
        self.assertEqual(self.store.recover_publications(), [run])
        self.assertEqual(self.store.run_status(run)["execution_status"], "succeeded")
        self.assertEqual(self.store.inspect_run(run).joinpath("result").read_bytes(), b"complete")
        self.assertEqual(self.store.recover_publications(), [])

    def test_dead_controls_recover_while_live_claim_survives(self) -> None:
        identity = self.asset("controls")
        context = get_context("spawn")
        ready, release, crashed = context.Event(), context.Event(), context.Event()
        live = context.Process(target=_claim_worker, args=(str(self.store.root), identity, ready, release))
        dead = context.Process(target=_crash_worker, args=(str(self.store.root), identity, crashed))
        live.start()
        dead.start()
        try:
            self.assertTrue(ready.wait(20))
            self.assertTrue(crashed.wait(20))
            dead.join(20)
            self.assertEqual(dead.exitcode, 0)
            self.assertEqual(len(self.store.recover_controls()), 2)
            self.assertEqual(self.store.collect(100)["released_bytes"], 0)
        finally:
            release.set()
            live.join(20)
            dead.join(20)
        self.assertEqual(live.exitcode, 0)
        self.assertEqual(self.store.collect(100)["released_bytes"], 3)

    def test_run_usage_triggers_soft_gc_without_deleting_run(self) -> None:
        work = self.store.new_work()
        (work / "result").write_bytes(b"x" * 100)
        run, _ = self.store.publish_run(work)
        self.asset("cold")
        self.store.high, self.store.low = 50, 10
        with self.store.reserve(0):
            self.assertIsNone(self.store.find_asset("cold"))
        self.assertTrue(self.store.inspect_run(run).exists())

    def test_hard_link_rejected_without_changing_source(self) -> None:
        work = self.store.new_work()
        source = Path(self.temp.name) / "source"
        source.write_bytes(b"original")
        try:
            os.link(source, work / "link")
        except OSError as exc:
            self.skipTest(f"hard links unavailable: {exc}")
        with self.assertRaises(ValueError):
            self.store.put_asset("field", "hardlink", work)
        self.assertEqual(source.read_bytes(), b"original")

    @unittest.skipUnless(os.name == "nt", "Windows junction test")
    def test_junction_rejected_without_traversing_target(self) -> None:
        work = self.store.new_work()
        target = Path(self.temp.name) / "target"
        target.mkdir()
        (target / "evidence").write_bytes(b"keep")
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(work / "junction"), str(target)],
                                capture_output=True, cwd=self.temp.name, timeout=10)
        if result.returncode:
            self.skipTest("Windows junction creation unavailable")
        with self.assertRaises(ValueError):
            self.store.put_asset("field", "junction", work)
        with self.assertRaises(ValueError):
            self.store.discard_work(work)
        self.assertEqual((target / "evidence").read_bytes(), b"keep")
        os.rmdir(work / "junction")


if __name__ == "__main__":
    unittest.main()

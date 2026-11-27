"""Atomic persistent native run identity on the existing Store catalog."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from threading import Barrier, Event, current_thread
import unittest
from unittest.mock import patch

from msplatform.storage.store import ArtifactStore


class StoreRunIdentityTests(unittest.TestCase):
    def test_upgrade_waits_for_gc_before_opening_write_transaction(self):
        from msplatform.storage import store as store_module
        with tempfile.TemporaryDirectory(prefix='store-lock-order-') as directory:
            store = ArtifactStore(Path(directory) / 'store')
            real_lock = store_module.process_file_lock
            attempted = Event()
            main_thread = current_thread()
            @contextmanager
            def observed(path, **kwargs):
                if Path(path).name == '.gc.lock' and current_thread() is not main_thread:
                    attempted.set()
                with real_lock(path, **kwargs):
                    yield
            def upgrade():
                with store.inplace_asset('native_stage', 'ordered', run_id='20261127_180030__test__python__ordered') as (_, path, _claim, seal):
                    (path / 'evidence').write_bytes(b'ordered')
                    seal()
            with ThreadPoolExecutor(max_workers=1) as pool:
                with store._gc_guard(), patch.object(store_module, 'process_file_lock', observed):
                    future = pool.submit(upgrade)
                    self.assertTrue(attempted.wait(5))
                    with closing(sqlite3.connect(store.root / 'catalog.sqlite', timeout=1)) as db:
                        db.execute('BEGIN IMMEDIATE')
                        db.rollback()
                future.result(timeout=5)

    def test_upgrade_backfills_and_rejects_legacy_writer(self):
        with tempfile.TemporaryDirectory(prefix='store-run-upgrade-') as directory:
            store = ArtifactStore(Path(directory) / 'store')
            old_id = '20261127_180010__test__python__old'
            with store.inplace_asset('native_stage', 'legacy') as (asset, path, _claim, seal):
                run = path / 'runs' / old_id
                run.mkdir(parents=True)
                (run / 'evidence').write_bytes(b'old')
                seal()
            original = (run / 'evidence').read_bytes()
            with store.inplace_asset('native_stage', 'new', run_id='20261127_180011__test__python__new') as (_, path, _claim, seal):
                (path / 'evidence').write_bytes(b'new')
                seal()
            self.assertEqual((run / 'evidence').read_bytes(), original)
            with self.assertRaises(FileExistsError):
                with store.inplace_asset('native_stage', 'retry', run_id=old_id):
                    self.fail('legacy identity was not backfilled')
            with store._db() as db:
                self.assertEqual(db.execute('SELECT asset_id FROM native_run_ids WHERE run_id=?', (old_id,)).fetchone()[0], asset)
            old_writer = r'''import sqlite3, sys
c=sqlite3.connect(sys.argv[1])
try:
    c.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,NULL,?)", ('old-writer','old','assets/native_stage/aa/old-writer','publishing','cache','{}',0,0,'time','inplace:old'))
    c.commit()
except sqlite3.IntegrityError as e:
    print(str(e))
else:
    raise SystemExit('old writer bypassed native run protocol')
'''
            result = subprocess.run([sys.executable, '-c', old_writer, str(store.root / 'catalog.sqlite')],
                                    cwd=store.root, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('native stage requires registered run identity', result.stdout)

    def test_upgrade_refuses_live_writer_and_ambiguous_legacy_ids(self):
        with tempfile.TemporaryDirectory(prefix='store-run-upgrade-') as directory:
            store = ArtifactStore(Path(directory) / 'store')
            old_id = '20261127_180020__test__python__old'
            with store.inplace_asset('native_stage', 'live') as (_, path, _claim, seal):
                run = path / 'runs' / old_id
                run.mkdir(parents=True)
                (run / 'evidence').write_bytes(b'live')
                with self.assertRaises(TimeoutError):
                    with store.inplace_asset('native_stage', 'new', run_id='20261127_180021__test__python__new'):
                        self.fail('upgrade accepted an active writer')
                seal()
            with store.inplace_asset('native_stage', 'duplicate') as (second, path, _claim, seal):
                run = path / 'runs' / old_id
                run.mkdir(parents=True)
                (run / 'evidence').write_bytes(b'duplicate')
                seal()
            with self.assertRaisesRegex(ValueError, 'native run identity conflict') as caught:
                with store.inplace_asset('native_stage', 'new', run_id='20261127_180021__test__python__new'):
                    self.fail('ambiguous legacy identity was accepted')
            self.assertIn(second, str(caught.exception))
            with store._db() as db:
                self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='native_run_id_required'").fetchone())

    def test_concurrent_identity_and_retry_after_gc_or_failure(self):
        with tempfile.TemporaryDirectory(prefix='store-run-id-') as directory:
            store = ArtifactStore(Path(directory) / 'store')
            run_id = '20261127_180000__test__python__unique'
            with self.assertRaisesRegex(ValueError, 'only valid for a native stage'):
                with store.inplace_asset('field', 'not-a-native-stage', run_id=run_id):
                    self.fail('non-native asset consumed a native run ID')
            barrier = Barrier(2)
            def publish(index):
                barrier.wait()
                try:
                    with store.inplace_asset('native_stage', 'same-science-key', run_id=run_id) as (asset, path, _claim, seal):
                        (path / 'evidence').write_text(str(index), encoding='utf-8')
                        seal()
                        return asset
                except FileExistsError:
                    return None
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(publish, (1, 2)))
            winners = [value for value in results if value is not None]
            self.assertEqual(len(winners), 1)
            self.assertEqual(store.asset_status(winners[0])['state'], 'ready')
            self.assertEqual(len(list((store.root / 'assets/native_stage').glob('*/*'))), 1)
            store.collect(1_000_000)
            with self.assertRaises(FileExistsError):
                with store.inplace_asset('native_stage', 'different-key', run_id=run_id):
                    self.fail('a collected run ID was reused')
            failed_id = '20261127_180001__test__python__failed'
            with store.inplace_asset('native_stage', 'failed', run_id=failed_id) as (asset, path, _claim, seal):
                (path / 'evidence').write_bytes(b'failure')
                seal(failure_reason='explicit failure')
            self.assertEqual(store.asset_status(asset)['state'], 'failed')
            with self.assertRaises(FileExistsError):
                with store.inplace_asset('native_stage', 'another-key', run_id=failed_id):
                    self.fail('a failed run ID was reused')
            with store.inplace_asset('native_stage', 'same-science-key', run_id='20261127_180002__test__python__other') as (_, path, _claim, seal):
                (path / 'evidence').write_bytes(b'other')
                seal()


if __name__ == '__main__':
    unittest.main()

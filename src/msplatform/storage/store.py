"""Single-owner local immutable assets and published run records.

Only a newly created, dedicated root is admitted. SQLite serializes protection
and deletion decisions; payload I/O happens outside its short transactions.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
from typing import Iterator
from uuid import uuid4
from msplatform.execution.file_lock import process_file_lock


def _check_entry(path: Path) -> os.stat_result:
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        raise ValueError("links and reparse points are not permitted")
    return info


def _entries(root: Path) -> Iterator[tuple[Path, os.stat_result]]:
    _check_entry(root)
    with os.scandir(root) as entries:
        paths = sorted(Path(entry.path) for entry in entries)
    for path in paths:
        info = _check_entry(path)
        yield path, info
        if stat.S_ISDIR(info.st_mode):
            yield from _entries(path)


def _records(root: Path) -> dict[str, dict[str, object]]:
    records = {}
    for path, info in _entries(root):
        if stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                raise ValueError("hard-linked payload files are not permitted")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            records[path.relative_to(root).as_posix()] = {
                "bytes": path.stat().st_size, "sha256": digest.hexdigest()
            }
    if not records:
        raise ValueError("an empty payload cannot be published")
    return records


def _token(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9_]+", value):
        raise ValueError("kind must contain lowercase ASCII letters, digits or underscores")
    return value


class ArtifactStore:
    """Own one dedicated artifact root; no operation targets legacy owners."""

    def __init__(self, root: str | Path, *, high_water_bytes: int | None = None,
                 low_water_bytes: int | None = None, safety_bytes: int = 0):
        root = Path(root).absolute()
        if any((p / ".git").exists() for p in (root, *root.parents)):
            raise ValueError("artifact root must be outside a Git worktree")
        if any((p / ".msplatform-store").exists() for p in root.parents):
            raise ValueError("a managed store cannot contain another store")
        if root.name.lower() in {"artifacts", "projects", "common", "platform"} or any(
            p.name.lower() in {"projects", "common", "platform"} and p.parent.name.lower() == "artifacts"
            for p in root.parents
        ):
            raise ValueError("legacy owner roots cannot be adopted")
        if root.is_symlink() or root.resolve() != root:
            raise ValueError("artifact root must not traverse links")
        if root.exists() and any(root.iterdir()) and not (root / ".msplatform-store").is_file():
            raise ValueError("artifact root must be empty or already owned by this store")
        if safety_bytes < 0 or ((high_water_bytes is None) != (low_water_bytes is None)):
            raise ValueError("invalid capacity policy")
        if high_water_bytes is not None and not 0 <= low_water_bytes <= high_water_bytes:
            raise ValueError("invalid watermarks")
        root.mkdir(parents=True, exist_ok=True)
        (root / ".msplatform-store").touch(exist_ok=True)
        for part in ("work", "assets", "runs", "cache", "control"):
            (root / part).mkdir(exist_ok=True)
        self.root = root
        self.high = high_water_bytes
        self.low = low_water_bytes
        self.safety = safety_bytes
        self._owned_work: set[Path] = set()
        self._active_run_writers: set[str] = set()
        self._active_control_ids: set[str] = set()
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, key TEXT NOT NULL,
              path TEXT NOT NULL, state TEXT NOT NULL, retention TEXT NOT NULL,
              records TEXT NOT NULL, size INTEGER NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
              created TEXT NOT NULL, failure TEXT, work TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS asset_key ON assets(key, state);
            CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY, asset_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, path TEXT NOT NULL,
              state TEXT NOT NULL, records TEXT NOT NULL, work TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS refs(run_id TEXT NOT NULL, asset_id TEXT NOT NULL,
              required INTEGER NOT NULL, PRIMARY KEY(run_id, asset_id));
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY, remaining INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS controls(id TEXT PRIMARY KEY, kind TEXT NOT NULL, owner_pid INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS run_execution(id TEXT PRIMARY KEY, path TEXT NOT NULL, work TEXT NOT NULL,
              status TEXT NOT NULL, reason TEXT);
            CREATE TABLE IF NOT EXISTS run_writers(run_id TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE);
            CREATE TABLE IF NOT EXISTS native_bindings(id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
              host_token TEXT NOT NULL, host_state_path TEXT NOT NULL, host_owner TEXT NOT NULL,
              host_file_id TEXT NOT NULL,
              operation_id TEXT NOT NULL, worker_pid INTEGER,
              worker_started INTEGER, state TEXT NOT NULL, completion TEXT);
            CREATE TABLE IF NOT EXISTS native_binding_controls(binding_id TEXT NOT NULL,
              control_id TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY(binding_id,control_id));
            CREATE TABLE IF NOT EXISTS native_recovery_issues(binding_id TEXT NOT NULL,
              receipt_path TEXT NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(binding_id,receipt_path));
            CREATE TABLE IF NOT EXISTS gc_lock(id INTEGER PRIMARY KEY CHECK(id=1));
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.root / "catalog.sqlite", timeout=30, isolation_level=None)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def new_work(self) -> Path:
        """Create an exclusive private writable directory."""
        path = self.root / "work" / uuid4().hex
        path.mkdir()
        self._owned_work.add(path)
        return path

    def discard_work(self, path: str | Path) -> int:
        """Remove this instance's private work after its outputs are safely published."""
        path = self._work(path)
        if path not in self._owned_work:
            raise ValueError("work directory is not owned by this store instance")
        total = 0
        for child, info in _entries(path):
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
        shutil.rmtree(path)
        self._owned_work.remove(path)
        return total

    def _work(self, path: str | Path) -> Path:
        path = Path(path).absolute()
        if (path.parent != self.root / "work" or not path.is_dir()
                or path not in self._owned_work):
            raise ValueError("payload must be an immediate private work directory")
        _check_entry(path)
        return path

    def put_asset(self, kind: str, key: str, source_dir: str | Path, *, retention: str = "cache") -> str:
        """Publish a complete immutable asset. Its source is a private work directory."""
        return self._put_asset(kind, key, source_dir, retention=retention, claim_id=None)[0]

    def _put_asset(self, kind: str, key: str, source_dir: str | Path, *, retention: str,
                   claim_id: str | None) -> tuple[str, Path]:
        _token(kind)
        if not isinstance(key, str) or not key or retention not in {"cache", "preserve"}:
            raise ValueError("explicit key and supported retention are required")
        source = self._work(source_dir)
        records = _records(source)
        asset_id = uuid4().hex
        prefix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:2]
        relative = Path("assets") / kind / prefix / asset_id
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,NULL,?)",
                       (asset_id, key, relative.as_posix(), "publishing", retention,
                        json.dumps(records, sort_keys=True), sum(r["bytes"] for r in records.values()),
                        0, datetime.now(timezone.utc).isoformat(), source.name))
        os.replace(source, destination)
        self._owned_work.discard(source)
        with self._transaction() as db:
            db.execute("UPDATE assets SET state='ready' WHERE id=? AND state='publishing'", (asset_id,))
            if claim_id is not None:
                db.execute("INSERT INTO claims VALUES(?,?)", (claim_id, asset_id))
                db.execute("INSERT INTO controls VALUES(?,?,?)", (claim_id, "claim", os.getpid()))
        return asset_id, destination

    @contextmanager
    def put_asset_claimed(self, kind: str, key: str, source_dir: str | Path,
                          *, retention: str = "cache") -> Iterator[tuple[str, Path]]:
        """Publish with a claim established atomically with the ready state."""
        claim_id = uuid4().hex
        with self._control_lock(claim_id):
            identity, path = self._put_asset(kind, key, source_dir, retention=retention, claim_id=claim_id)
            self._active_control_ids.add(claim_id)
            try:
                yield identity, path
            finally:
                self._active_control_ids.discard(claim_id)
                self._release_claim(claim_id)

    def find_asset(self, key: str) -> tuple[str, Path] | None:
        """Probe a cache; callers must claim it again before consuming the path."""
        with self.claim_key(key) as result:
            return result

    @contextmanager
    def claim_key(self, key: str) -> Iterator[tuple[str, Path] | None]:
        """Atomically protect a valid cache through the caller's consumption."""
        with self._db() as db:
            rows = db.execute("SELECT id,records FROM assets WHERE key=? AND state='ready' ORDER BY created DESC", (key,)).fetchall()
        for asset_id, records in rows:
            manager = self.claim(asset_id)
            try:
                path = manager.__enter__()
            except (OSError, ValueError, KeyError):
                continue
            try:
                valid = _records(path) == json.loads(records)
            except (OSError, ValueError):
                valid = False
            if not valid:
                manager.__exit__(None, None, None)
                continue
            try:
                yield asset_id, path
            finally:
                manager.__exit__(None, None, None)
            return
        yield None

    def _release_claim(self, claim_id: str) -> None:
        with self._transaction() as db:
            bound = db.execute("""SELECT 1 FROM native_binding_controls c JOIN native_bindings b
                ON b.id=c.binding_id WHERE c.control_id=? AND b.state='active'""", (claim_id,)).fetchone()
            if not bound:
                db.execute("DELETE FROM claims WHERE id=?", (claim_id,))
                db.execute("DELETE FROM controls WHERE id=?", (claim_id,))

    def _control_lock(self, identity: str):
        return process_file_lock(self.root / "control" / (identity + ".lock"), timeout_seconds=0)

    @contextmanager
    def claim(self, asset_id: str) -> Iterator[Path]:
        """Protect a ready asset from GC until explicitly released, with no TTL expiry."""
        with self.claim_token(asset_id) as (_, path):
            yield path

    @contextmanager
    def claim_token(self, asset_id: str) -> Iterator[tuple[str, Path]]:
        """Hold an asset claim and expose its identity for native binding."""
        claim_id = uuid4().hex
        with self._control_lock(claim_id):
            with self._transaction() as db:
                row = db.execute("SELECT path FROM assets WHERE id=? AND state='ready'", (asset_id,)).fetchone()
                if row is None:
                    raise KeyError(asset_id)
                db.execute("INSERT INTO claims VALUES(?,?)", (claim_id, asset_id))
                db.execute("INSERT INTO controls VALUES(?,?,?)", (claim_id, "claim", os.getpid()))
            self._active_control_ids.add(claim_id)
            try:
                yield claim_id, self.root / row[0]
            finally:
                self._active_control_ids.discard(claim_id)
                self._release_claim(claim_id)

    def pin(self, asset_id: str, pinned: bool = True) -> None:
        with self._transaction() as db:
            changed = db.execute("UPDATE assets SET pinned=? WHERE id=? AND state='ready'", (int(pinned), asset_id)).rowcount
            if not changed:
                raise KeyError(asset_id)

    def bind_native_controls(self, run_id: str, *, host_state_path: Path, host_token: str,
                             host_owner: dict, operation_id: str, claim_ids: tuple[str, ...],
                             reservation_ids: tuple[str, ...]) -> str:
        """Bind held controls to an acquired host grant before permitting native launch."""
        from msplatform.execution.native_artifact_controls import validate_host_binding
        host = validate_host_binding(host_state_path, host_token, host_owner)
        ids = [*claim_ids, *reservation_ids]
        if (not isinstance(operation_id, str) or not operation_id or not claim_ids or not reservation_ids
                or len(ids) != len(set(ids)) or not set(ids).issubset(self._active_control_ids)
                or run_id not in self._active_run_writers):
            raise ValueError("native binding requires this instance's active writer, claims and reservations")
        binding_id = uuid4().hex
        with self._transaction() as db:
            writer = db.execute("""SELECT 1 FROM run_writers w JOIN run_execution e ON e.id=w.run_id
                WHERE w.run_id=? AND e.status='running'""", (run_id,)).fetchone()
            if not writer:
                raise ValueError("native binding requires a running writer")
            for identity, kind in [(value, "claim") for value in claim_ids] + [(value, "reservation") for value in reservation_ids]:
                row = db.execute("SELECT kind,owner_pid FROM controls WHERE id=?", (identity,)).fetchone()
                already = db.execute("""SELECT 1 FROM native_binding_controls c JOIN native_bindings b
                    ON b.id=c.binding_id WHERE c.control_id=? AND b.state='active'""", (identity,)).fetchone()
                if row != (kind, os.getpid()) or already:
                    raise ValueError("native control identity is missing, foreign or already bound")
            db.execute("INSERT INTO native_bindings VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                (binding_id, run_id, host_token, host["host_state_path"], json.dumps(host["host_owner"], sort_keys=True),
                 json.dumps(host["host_file_id"]), operation_id, None, None, "active"))
            db.executemany("INSERT INTO native_binding_controls VALUES(?,?,?)",
                [(binding_id, value, "claim") for value in claim_ids]
                + [(binding_id, value, "reservation") for value in reservation_ids])
        return binding_id

    def record_native_worker(self, binding_id: str, *, process_id: int, started_at_utc_ticks: int) -> None:
        """Record the process owner's observed exact worker creation identity."""
        from msplatform.execution.native_artifact_controls import validate_host_worker
        if any(type(value) is not int or value <= 0 for value in (process_id, started_at_utc_ticks)):
            raise ValueError("worker requires positive process and creation identities")
        with self._db() as db:
            row = db.execute("""SELECT host_state_path,host_token,host_owner FROM native_bindings
                WHERE id=? AND state='active' AND worker_pid IS NULL""", (binding_id,)).fetchone()
        if row is None:
            raise ValueError("unknown, completed or already bound native worker")
        validate_host_worker(Path(row[0]), row[1], json.loads(row[2]), process_id, started_at_utc_ticks)
        with self._transaction() as db:
            changed = db.execute("""UPDATE native_bindings SET worker_pid=?,worker_started=?
                WHERE id=? AND state='active' AND worker_pid IS NULL""",
                (process_id, started_at_utc_ticks, binding_id)).rowcount
            if not changed:
                raise ValueError("unknown, completed or already bound native worker")

    def complete_native_controls(self, binding_id: str, *, completion: dict) -> bool:
        """Release bound controls after exact existing owner completion, idempotently."""
        from msplatform.execution.native_artifact_controls import validate_native_completion
        with self._db() as db:
            row = db.execute("""SELECT host_token,operation_id,worker_pid,worker_started,state,host_state_path,host_file_id
                FROM native_bindings WHERE id=?""", (binding_id,)).fetchone()
        if row is None:
            raise KeyError(binding_id)
        if row[4] == "complete":
            return False
        binding = dict(zip(("host_token", "operation_id", "worker_pid", "worker_started"), row[:4]))
        binding.update(host_state_path=row[5], host_file_id=json.loads(row[6]))
        validate_native_completion(binding, completion)
        with self._transaction() as db:
            current = db.execute("SELECT state FROM native_bindings WHERE id=?", (binding_id,)).fetchone()
            if current is None:
                raise KeyError(binding_id)
            if current[0] == "complete":
                return False
            bound_ids = tuple(row[0] for row in db.execute(
                "SELECT control_id FROM native_binding_controls WHERE binding_id=?", (binding_id,)))
            db.execute("UPDATE native_bindings SET state='complete',completion=? WHERE id=? AND state='active'",
                       (json.dumps(completion, sort_keys=True), binding_id))
        # Existing holders still own their controls across later stages. Dead
        # holders are released only by the normal per-token OS-lock recovery.
        self._recover_controls(bound_ids)
        return True

    def begin_run(self) -> tuple[str, Path]:
        """Register a queued run and its private workspace before admission."""
        work = self.new_work()
        run_id = uuid4().hex
        relative = (Path("runs") / datetime.now(timezone.utc).strftime("%Y/%m") / run_id).as_posix()
        with self._transaction() as db:
            db.execute("INSERT INTO run_execution VALUES(?,?,?,?,NULL)", (run_id, relative, work.name, "queued"))
        return run_id, work

    def _change_status(self, run_id: str, status: str, reason: str | None, allowed: tuple[str, ...]) -> None:
        with self._transaction() as db:
            row = db.execute("SELECT status FROM run_execution WHERE id=?", (run_id,)).fetchone()
            if row is None or row[0] not in allowed:
                raise ValueError("invalid run execution transition")
            db.execute("UPDATE run_execution SET status=?,reason=? WHERE id=?", (status, reason, run_id))

    def mark_running(self, run_id: str) -> None:
        if run_id not in self._active_run_writers:
            raise ValueError("mark_running requires an active run_writer")
        self._change_status(run_id, "running", None, ("queued",))

    @contextmanager
    def run_writer(self, run_id: str) -> Iterator[None]:
        """Hold the run's OS writer lock from before running until publication ends.

        The context only protects its holder. External/native consumers must
        hold their own claims and may not rely on this process's lifetime.
        """
        token = uuid4().hex
        with self._control_lock(token):
            with self._transaction() as db:
                row = db.execute("SELECT status FROM run_execution WHERE id=?", (run_id,)).fetchone()
                if row is None or row[0] != "queued":
                    raise ValueError("writer requires a queued run")
                db.execute("INSERT INTO run_writers VALUES(?,?)", (run_id, token))
            self._active_run_writers.add(run_id)
            try:
                yield
            finally:
                self._active_run_writers.discard(run_id)
                with self._transaction() as db:
                    db.execute("""DELETE FROM run_writers WHERE run_id=? AND token=?
                        AND EXISTS(SELECT 1 FROM run_execution WHERE id=? AND status!='running')
                        AND NOT EXISTS(SELECT 1 FROM native_bindings WHERE run_id=? AND state='active')""",
                               (run_id, token, run_id, run_id))

    def recover_interrupted_runs(self) -> list[str]:
        """Mark unlocked pre-publication running writers failed, retaining their work.

        Running records without a writer token and all publishing records are
        preserved for explicit investigation or publication recovery.
        """
        self.recover_controls()
        with self._db() as db:
            rows = db.execute("""SELECT w.run_id,w.token FROM run_writers w
                JOIN run_execution e ON e.id=w.run_id WHERE e.status='running'
                AND NOT EXISTS(SELECT 1 FROM native_bindings b WHERE b.run_id=w.run_id AND b.state='active')""").fetchall()
        recovered = []
        for run_id, token in rows:
            if not (self.root / "control" / (token + ".lock")).is_file():
                continue
            try:
                with self._control_lock(token), self._transaction() as db:
                    changed = db.execute("""UPDATE run_execution SET status='failed',reason=?
                        WHERE id=? AND status='running' AND NOT EXISTS
                        (SELECT 1 FROM runs WHERE id=?) AND EXISTS
                        (SELECT 1 FROM run_writers WHERE run_id=? AND token=?) AND NOT EXISTS
                        (SELECT 1 FROM native_bindings WHERE run_id=? AND state='active')""",
                        ("writer interrupted before publication", run_id, run_id, run_id, token, run_id)).rowcount
                    if changed:
                        recovered.append(run_id)
            except TimeoutError:
                continue
        return recovered

    def set_queued_reason(self, run_id: str, reason: str) -> None:
        self._change_status(run_id, "queued", reason, ("queued",))

    def finish_run(self, run_id: str, execution_status: str, *, reason: str | None = None) -> None:
        if execution_status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("invalid terminal execution status")
        self._change_status(run_id, execution_status, reason, ("running",))

    def run_status(self, run_id: str) -> dict[str, object]:
        with self._db() as db:
            row = db.execute("SELECT e.status,e.reason,e.path,r.state,e.work FROM run_execution e LEFT JOIN runs r ON r.id=e.id WHERE e.id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return {"execution_status": row[0], "reason": row[1], "run_path": row[2],
                "publication_status": row[3] or "unpublished", "work_path": f"work/{row[4]}"}

    def publish_run(self, work_dir: str | Path, *, required_assets: tuple[str, ...] = (),
                    provenance_assets: tuple[str, ...] = (), run_id: str | None = None,
                    execution_status: str = "succeeded") -> tuple[str, Path]:
        """Publish a run and retain its explicitly necessary asset dependencies."""
        work = self._work(work_dir)
        if execution_status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("invalid terminal execution status")
        if run_id is None:
            run_id = uuid4().hex
            relative = Path("runs") / datetime.now(timezone.utc).strftime("%Y/%m") / run_id
            with self._transaction() as db:
                db.execute("INSERT INTO run_execution VALUES(?,?,?,?,NULL)", (run_id, relative.as_posix(), work.name, "running"))
        else:
            with self._db() as db:
                row = db.execute("SELECT path,work,status FROM run_execution WHERE id=?", (run_id,)).fetchone()
            if row is None or row[1] != work.name or row[2] != "running":
                raise ValueError("run must be running and own the work directory")
            relative = Path(row[0])
        now = datetime.now(timezone.utc)
        manifest_path = work / "run_manifest.json"
        if manifest_path.exists():
            raise ValueError("run manifest is owned by ArtifactStore")
        payload_records = _records(work)
        manifest = {"schema_version": 1, "run_id": run_id, "created_utc": now.isoformat(),
                    "files": payload_records, "required_assets": sorted(set(required_assets)),
                    "provenance_assets": sorted(set(provenance_assets)), "execution_status": execution_status}
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, sort_keys=True, allow_nan=False, indent=2)
            stream.write("\n")
        records = _records(work)
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            for asset_id in set(required_assets) | set(provenance_assets):
                if not db.execute("SELECT 1 FROM assets WHERE id=? AND state='ready'", (asset_id,)).fetchone():
                    raise KeyError(asset_id)
            db.execute("INSERT INTO runs VALUES(?,?,?,?,?)", (run_id, relative.as_posix(), "publishing", json.dumps(records, sort_keys=True), work.name))
            for asset_id in set(required_assets) | set(provenance_assets):
                db.execute("INSERT INTO refs VALUES(?,?,?)", (run_id, asset_id, int(asset_id in required_assets)))
        os.replace(work, destination)
        self._owned_work.discard(work)
        with self._transaction() as db:
            db.execute("UPDATE runs SET state='ready' WHERE id=? AND state='publishing'", (run_id,))
            db.execute("UPDATE run_execution SET status=? WHERE id=? AND status='running'", (execution_status, run_id))
        return run_id, destination

    def inspect_run(self, run_id: str) -> Path:
        with self._db() as db:
            row = db.execute("SELECT path,records FROM runs WHERE id=? AND state='ready'", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        path = self.root / row[0]
        records = _records(path)
        if records != json.loads(row[1]):
            raise ValueError("published run is incomplete or modified")
        manifest = json.loads((path / "run_manifest.json").read_text(encoding="utf-8"))
        if (manifest.get("schema_version") != 1 or manifest.get("run_id") != run_id
                or manifest.get("files") != {k: v for k, v in records.items() if k != "run_manifest.json"}):
            raise ValueError("run manifest does not close over the published payload")
        return path

    @contextmanager
    def _gc_guard(self) -> Iterator[None]:
        """Hold an OS lock released automatically if the GC process exits."""
        with process_file_lock(self.root / ".gc.lock", timeout_seconds=0):
            yield

    def collect(self, target_bytes: int = 0) -> dict[str, object]:
        """Delete only unprotected cache assets, retaining failures for recovery.

        target_bytes is the number of bytes sought, not a guarantee. Passing zero
        processes previously pending deletes only. Bytes are credited after removal.
        """
        if type(target_bytes) is not int or target_bytes < 0:
            raise ValueError("target_bytes must be a nonnegative integer")
        released = 0
        failures = []
        with self._gc_guard():
            # Freeze candidate identities for this pass: a failed pending delete
            # is reported once, while other eligible objects can still be tried.
            with self._db() as db:
                candidates = db.execute("""SELECT id,state FROM assets
                    WHERE state IN ('delete_pending','ready')
                    ORDER BY CASE state WHEN 'delete_pending' THEN 0 ELSE 1 END,created,id""").fetchall()
            for asset_id, initial_state in candidates:
                if initial_state == "ready" and released >= target_bytes:
                    break
                with self._transaction() as db:
                    if initial_state == "ready":
                        db.execute("""UPDATE assets SET state='delete_pending' WHERE id=?
                            AND state='ready' AND retention='cache' AND pinned=0
                            AND NOT EXISTS(SELECT 1 FROM claims c WHERE c.asset_id=assets.id)
                            AND NOT EXISTS(SELECT 1 FROM refs r WHERE r.asset_id=assets.id AND r.required=1)""",
                            (asset_id,))
                    row = db.execute("SELECT path FROM assets WHERE id=? AND state='delete_pending'", (asset_id,)).fetchone()
                if row is None:
                    continue
                relative = row[0]
                path = self.root / relative
                try:
                    removed_bytes = 0
                    try:
                        _check_entry(path)
                        exists = True
                    except FileNotFoundError:
                        exists = False
                    if exists:
                        for child, info in _entries(path):
                            if stat.S_ISREG(info.st_mode):
                                removed_bytes += info.st_size
                        shutil.rmtree(path)
                    with self._transaction() as db:
                        db.execute("UPDATE assets SET state='deleted',failure=NULL WHERE id=? AND state='delete_pending'", (asset_id,))
                    released += removed_bytes
                except (OSError, ValueError) as exc:
                    with self._transaction() as db:
                        db.execute("UPDATE assets SET failure=? WHERE id=?", (str(exc), asset_id))
                    failures.append({"asset_id": asset_id, "reason": str(exc)})
        return {"released_bytes": released, "failures": failures}

    @contextmanager
    def reserve(self, peak_bytes: int) -> Iterator[str]:
        """Reserve unwritten capacity; soft watermark pressure never blocks alone."""
        if type(peak_bytes) is not int or peak_bytes < 0:
            raise ValueError("peak_bytes must be a nonnegative integer")
        with self._db() as db:
            used = db.execute("SELECT COALESCE(SUM(size),0) FROM assets WHERE state IN ('ready','delete_pending')").fetchone()[0]
            used += db.execute("""SELECT COALESCE(SUM(json_extract(item.value, '$.bytes')),0)
                FROM runs, json_each(runs.records) AS item WHERE runs.state IN ('ready','publishing')""").fetchone()[0]
        if self.high is not None and used > self.high:
            try:
                self.collect(max(0, used - self.low))
            except TimeoutError:
                pass
        free = shutil.disk_usage(self.root).free
        with self._db() as db:
            remaining = db.execute("SELECT COALESCE(SUM(remaining),0) FROM reservations").fetchone()[0]
        needed = self.safety + remaining + peak_bytes
        if free < needed:
            self.collect(needed - free)
        reservation = uuid4().hex
        with self._control_lock(reservation):
            with self._transaction() as db:
                remaining = db.execute("SELECT COALESCE(SUM(remaining),0) FROM reservations").fetchone()[0]
                if shutil.disk_usage(self.root).free < self.safety + remaining + peak_bytes:
                    raise OSError("insufficient physical capacity after cache collection")
                db.execute("INSERT INTO reservations VALUES(?,?)", (reservation, peak_bytes))
                db.execute("INSERT INTO controls VALUES(?,?,?)", (reservation, "reservation", os.getpid()))
            self._active_control_ids.add(reservation)
            try:
                yield reservation
            finally:
                self._active_control_ids.discard(reservation)
                with self._transaction() as db:
                    bound = db.execute("""SELECT 1 FROM native_binding_controls c JOIN native_bindings b
                        ON b.id=c.binding_id WHERE c.control_id=? AND b.state='active'""", (reservation,)).fetchone()
                    if not bound:
                        db.execute("DELETE FROM reservations WHERE id=?", (reservation,))
                        db.execute("DELETE FROM controls WHERE id=?", (reservation,))

    def recover_controls(self) -> list[str]:
        """Release dead token holders; every external consumer must hold its own claim.

        No TTL or process ancestry inference is used. Rows without a matching
        control token remain protected for manual investigation.
        """
        self._reconcile_native_receipts()
        return self._recover_controls(None)

    def native_recovery_issues(self) -> list[dict[str, str]]:
        """Return exact native receipt failures retained during automatic recovery."""
        with self._db() as db:
            rows = db.execute("SELECT binding_id,receipt_path,reason FROM native_recovery_issues ORDER BY binding_id,receipt_path").fetchall()
        return [dict(binding_id=row[0], receipt_path=row[1], reason=row[2]) for row in rows]

    def _reconcile_native_receipts(self) -> None:
        """Inspect only each active binding's registered private work directory."""
        from msplatform.execution.native_artifact_controls import reconcile_native_receipt
        with self._db() as db:
            rows = db.execute("""SELECT b.id,e.work FROM native_bindings b
                JOIN run_execution e ON e.id=b.run_id WHERE b.state='active'""").fetchall()
        for binding_id, work_name in rows:
            directory = self.root / "work" / work_name
            if directory.parent != self.root / "work":
                continue
            try:
                _check_entry(directory)
                receipts = sorted(directory.glob("native-control-*.receipt.json"))
            except (OSError, ValueError):
                continue
            for receipt in receipts:
                try:
                    _check_entry(receipt)
                    content = json.loads(receipt.read_text(encoding="utf-8"))
                    if not isinstance(content, dict) or not isinstance(content.get("binding_id"), str):
                        raise ValueError("native receipt lacks its binding identity")
                    if content.get("binding_id") != binding_id:
                        continue
                    reconcile_native_receipt(self, receipt)
                except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
                    with self._transaction() as db:
                        if db.execute("SELECT 1 FROM native_bindings WHERE id=? AND state='active'", (binding_id,)).fetchone():
                            db.execute("""INSERT INTO native_recovery_issues VALUES(?,?,?)
                                ON CONFLICT(binding_id,receipt_path) DO UPDATE SET reason=excluded.reason""",
                                (binding_id, str(receipt.relative_to(self.root)), str(error)))
                    continue
                with self._transaction() as db:
                    db.execute("DELETE FROM native_recovery_issues WHERE binding_id=? AND receipt_path=?",
                               (binding_id, str(receipt.relative_to(self.root))))

    def _recover_controls(self, selected: tuple[str, ...] | None) -> list[str]:
        with self._db() as db:
            controls = db.execute("SELECT id,kind FROM controls").fetchall()
        recovered = []
        for identity, kind in controls:
            if selected is not None and identity not in selected:
                continue
            token = self.root / "control" / (identity + ".lock")
            if not token.is_file() or kind not in {"claim", "reservation"}:
                continue
            try:
                with self._control_lock(identity):
                    with self._transaction() as db:
                        bound = db.execute("""SELECT 1 FROM native_binding_controls c JOIN native_bindings b
                            ON b.id=c.binding_id WHERE c.control_id=? AND b.state='active'""", (identity,)).fetchone()
                        if bound:
                            continue
                        if kind == "claim":
                            db.execute("DELETE FROM claims WHERE id=?", (identity,))
                        else:
                            db.execute("DELETE FROM reservations WHERE id=?", (identity,))
                        db.execute("DELETE FROM controls WHERE id=? AND kind=?", (identity, kind))
                    recovered.append(identity)
            except TimeoutError:
                continue
        return recovered

    def reservation_written(self, reservation: str, remaining_bytes: int) -> None:
        """Replace a reservation by its still-unwritten amount after payload growth."""
        if type(remaining_bytes) is not int or remaining_bytes < 0:
            raise ValueError("remaining_bytes must be a nonnegative integer")
        with self._transaction() as db:
            changed = db.execute("UPDATE reservations SET remaining=? WHERE id=? AND remaining>=?",
                                 (remaining_bytes, reservation, remaining_bytes)).rowcount
            if not changed:
                raise ValueError("unknown reservation or growth beyond original reservation")

    def recover_publications(self) -> list[str]:
        """Resume interrupted publications after confirming their writers stopped.

        Caller must establish exclusive administrative access before recovery;
        elapsed time alone is not evidence that a writer or native child stopped.
        """
        recovered = []
        with self._gc_guard():
            with self._db() as db:
                assets = db.execute("SELECT id,path,records,work FROM assets WHERE state='publishing'").fetchall()
                runs = db.execute("SELECT id,path,records,work FROM runs WHERE state='publishing'").fetchall()
            for table, rows in (("assets", assets), ("runs", runs)):
                for identity, relative, expected, work_name in rows:
                    destination = self.root / relative
                    source = self.root / "work" / work_name
                    if destination.exists() and source.exists():
                        raise ValueError("ambiguous interrupted publication")
                    payload = destination if destination.exists() else source
                    if _records(payload) != json.loads(expected):
                        raise ValueError("interrupted publication payload is missing or modified")
                    if payload == source:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(source, destination)
                    status = None
                    if table == "runs":
                        manifest = json.loads((destination / "run_manifest.json").read_text(encoding="utf-8"))
                        status = manifest.get("execution_status")
                    with self._transaction() as db:
                        changed = db.execute(f"UPDATE {table} SET state='ready' WHERE id=? AND state='publishing'", (identity,)).rowcount
                        if changed and status in {"succeeded", "failed", "cancelled"}:
                            db.execute("UPDATE run_execution SET status=?,reason=NULL WHERE id=?", (status, identity))
                    recovered.append(identity)
        return recovered

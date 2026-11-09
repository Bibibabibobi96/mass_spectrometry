"""The unique replayable summary/manifest journal; no capacity or science policy."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from msplatform.execution.file_lock import process_file_lock
from msplatform.execution.recorded_file_removal import write_json_atomic

from msplatform.io.manifest_records import TERMINAL_JOURNAL_NAME
TERMINAL_LOCK_NAME = ".run_terminal_publication.lock"
TERMINAL_STATUSES = {"success", "failed", "interrupted", "superseded"}


def _can_replace_provisional(existing: dict[str, Any], target: dict[str, Any], allowed: bool) -> bool:
    return bool(allowed and existing.get("status") == "interrupted"
                and existing.get("lifecycle_state") == "provisional"
                and existing.get("run_id") == target.get("run_id")
                and existing.get("project") == target.get("project")
                and existing.get("mode") == target.get("mode"))


def _replay_terminal_publication_locked(run_root: Path, *, allow_provisional: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    root = run_root.resolve()
    journal_path = root / TERMINAL_JOURNAL_NAME
    journal = json.loads(journal_path.read_text(encoding="utf-8-sig"))
    documents = journal.get("documents") if isinstance(journal, dict) else None
    if (
        journal.get("schema_version") != 1
        or journal.get("role") != "run_terminal_publication_journal"
        or not isinstance(documents, dict)
        or set(documents) != {"summary.json", "run_manifest.json"}
        or not all(isinstance(value, dict) for value in documents.values())
        or documents["summary.json"].get("status")
        != documents["run_manifest.json"].get("status")
        or documents["run_manifest.json"].get("run_id") != journal.get("run_id")
    ):
        raise ValueError("terminal publication journal is invalid")
    summary = documents["summary.json"]
    manifest = documents["run_manifest.json"]
    existing_path = root / "run_manifest.json"
    if existing_path.is_file():
        existing = json.loads(existing_path.read_text(encoding="utf-8-sig"))
        if (existing.get("status") in TERMINAL_STATUSES and existing != manifest
                and not _can_replace_provisional(existing, manifest, allow_provisional)):
            raise ValueError("terminal publication conflicts with the already published manifest")
    write_json_atomic(root / "summary.json", summary)
    write_json_atomic(root / "run_manifest.json", manifest)
    journal_path.unlink()
    return summary, manifest


def replay_terminal_publication(run_root: Path, *, allow_provisional: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """Idempotently replay the sole durable terminal-publication journal."""
    root = run_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"terminal run directory is missing: {root}")
    with process_file_lock(root / TERMINAL_LOCK_NAME):
        return _replay_terminal_publication_locked(root, allow_provisional=allow_provisional)


def publish_terminal_state(
    run_root: Path,
    summary: dict[str, Any],
    manifest: dict[str, Any],
    *, allow_provisional: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Journal and publish summary plus manifest as one replayable intent."""

    root = run_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"terminal run directory is missing: {root}")
    journal_path = root / TERMINAL_JOURNAL_NAME
    journal = {
        "schema_version": 1,
        "role": "run_terminal_publication_journal",
        "run_id": manifest.get("run_id"),
        "documents": {"summary.json": summary, "run_manifest.json": manifest},
    }
    with process_file_lock(root / TERMINAL_LOCK_NAME):
        existing_manifest_path = root / "run_manifest.json"
        if existing_manifest_path.is_file():
            existing_manifest = json.loads(existing_manifest_path.read_text(encoding="utf-8-sig"))
            if existing_manifest.get("status") in TERMINAL_STATUSES:
                if existing_manifest != manifest and not _can_replace_provisional(existing_manifest, manifest, allow_provisional):
                    raise ValueError("terminal publication conflicts with the already published manifest")
                if existing_manifest == manifest and not journal_path.exists():
                    existing_summary = json.loads((root / "summary.json").read_text(encoding="utf-8-sig"))
                    if existing_summary != summary:
                        raise ValueError("terminal publication conflicts with the already published summary")
                    return summary, manifest
        if journal_path.exists():
            existing = json.loads(journal_path.read_text(encoding="utf-8-sig"))
            if existing != journal:
                raise ValueError("another terminal publication is already pending")
        else:
            write_json_atomic(journal_path, journal)
        return _replay_terminal_publication_locked(root, allow_provisional=allow_provisional)

"""The existing workflow terminal publisher, shared by installed and legacy owners."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Callable, Sequence
from msplatform.execution.manifest_publication import build_run_manifest
from msplatform.execution.terminal_publication import publish_terminal_state, replay_terminal_publication
from msplatform.io.manifest_records import TERMINAL_JOURNAL_NAME


def publish_workflow_terminal(completion_path: Path, session_path: Path, wait_path: Path | None, *,
        retention_api: Callable[[], tuple[Any, Any, Any, Any]], ceiling: int | None = None,
        additional_output_paths: Sequence[Path] = ()) -> dict[str, Any]:
    """Publish the original frozen completion with its original aggregate ceiling."""
    completion = json.loads(completion_path.read_text(encoding="utf-8-sig"))
    config_path = Path(completion["run_config"]["path"])
    root = config_path.parent
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    request = json.loads(Path(config["inputs"]["execution_request"]).read_text(encoding="utf-8-sig"))
    retention_path = root / "retention_actions.json"
    retention = json.loads(retention_path.read_text(encoding="utf-8-sig"))
    removed = {(root / item["path"]).resolve() for item in retention["removed"]}
    required = [Path(value) for value in completion["required_output_paths"]]
    if any(not path.is_file() for path in required): raise ValueError("retention removed required workflow evidence")
    outputs = []
    for value in completion["output_paths"]:
        path = Path(value)
        if path.is_file(): outputs.append(path)
        elif path.resolve() not in removed: raise ValueError(f"workflow output disappeared without retention evidence: {path}")
    summary = dict(completion["summary"], writers_stopped=True)
    summary_path = root / "summary.json"
    logs = [] if request["prepared"].get("owner_kind") in {"powershell", "managed_action"} else [root / "logs/prepared_stdout.log", root / "logs/prepared_stderr.log"]
    outputs = list(dict.fromkeys([*outputs, summary_path, completion_path, session_path, *([] if wait_path is None else [wait_path]), retention_path, *logs, *additional_output_paths]))
    manifest = build_run_manifest(config_path, completion["status"], software=request["package"]["software"],
        retention_api=retention_api, output_paths=outputs, virtual_documents={summary_path: summary}, extra_fields=completion["manifest_extra_fields"])
    if any(not item["exists"] for item in manifest["outputs"]): raise ValueError("workflow terminal output is missing")
    journal_path = root / TERMINAL_JOURNAL_NAME
    journal = json.loads(journal_path.read_text(encoding="utf-8-sig")) if journal_path.exists() else None
    existing = (journal["documents"] if journal is not None else
                {"summary.json": json.loads(summary_path.read_text(encoding="utf-8-sig")),
                 "run_manifest.json": json.loads((root / "run_manifest.json").read_text(encoding="utf-8-sig"))})
    terminal_exists = existing["run_manifest.json"].get("status") in {"success", "failed", "interrupted"}
    if journal is not None or terminal_exists:
        old = existing["run_manifest.json"]
        for field in ("recorded_at_utc", "host", "python"):
            if not isinstance(old.get(field), str): raise ValueError("terminal metadata identity differs")
            manifest[field] = old[field]
        if existing != {"summary.json": summary, "run_manifest.json": manifest}:
            raise ValueError("existing terminal publication differs from frozen workflow completion")
        if journal is None:
            return manifest
    def size(value): return len((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    if ceiling is not None:
        current = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        intent = journal or {"schema_version": 1, "role": "run_terminal_publication_journal", "run_id": manifest["run_id"],
                             "documents": {"summary.json": summary, "run_manifest.json": manifest}}
        # Conservatively retain all old targets, all new targets, and the largest
        # atomic temporary at once. This bounds the aggregate, not each JSON alone.
        sizes = [size(summary), size(manifest)] + ([] if journal is not None else [size(intent)])
        if current + sum(sizes) + max(sizes) > ceiling:
            raise ValueError("workflow terminal metadata exceeds admitted run byte ceiling")
    if journal is not None: replay_terminal_publication(root)
    else: publish_terminal_state(root, summary, manifest)
    return manifest

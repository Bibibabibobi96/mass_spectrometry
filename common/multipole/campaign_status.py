"""Report conservative per-row status for a multipole transport campaign."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.verify_run_manifest import verify_record
from common.multipole.runtime_profile import resolve_runtime_selection


TERMINAL_STATUSES = {"success", "failed", "interrupted", "superseded"}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("campaign must be a JSON object")
    return value


def _verify_manifest(
    path: Path, *, project_id: str, run_id: str
) -> tuple[str, str]:
    manifest = _load(path)
    status = manifest.get("status")
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"unsupported manifest status for {run_id}: {status!r}")
    if manifest.get("project") != project_id or manifest.get("run_id") != run_id:
        raise ValueError(f"manifest identity differs for {run_id}")
    verify_record("run_config", manifest["run_config"])
    run_config_path = Path(manifest["run_config"]["path"]).resolve()
    if run_config_path.parent != path.resolve().parent:
        raise ValueError(f"run_config escapes the run directory for {run_id}")
    run_config = _load(run_config_path)
    if (
        run_config.get("project") != project_id
        or run_config.get("run_id") != run_id
    ):
        raise ValueError(f"run_config identity differs for {run_id}")
    for name, record in manifest.get("inputs", {}).items():
        verify_record(f"input {name}", record)
    for index, record in enumerate(manifest.get("outputs", []), start=1):
        verify_record(f"output {index}", record)
    return str(status).upper(), str(path.resolve())


def campaign_status(
    repo_root: Path, campaign_path: Path
) -> dict[str, Any]:
    """Resolve every row and report only verified terminal states as terminal."""

    repo_root = repo_root.resolve()
    workspace_root = repo_root.parent
    campaign = _load(campaign_path.resolve())
    rows: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for experiment in campaign.get("experiments", []):
        project_id = str(experiment["project_id"])
        experiment_id = str(experiment["experiment_id"])
        run_id = str(experiment["authorized_run_id"])
        resolved = resolve_runtime_selection(
            repo_root,
            project_id,
            campaign_path=campaign_path,
            experiment_id=experiment_id,
        )
        authorized = resolved["engineering_budget"]["inline_contract"][
            "pilot_authorization"
        ]["scope"]["authorized_run_id"]
        if authorized != run_id:
            raise ValueError(f"authorized run identity differs for {experiment_id}")
        run_dir = (
            workspace_root
            / "artifacts"
            / "projects"
            / project_id
            / "runs"
            / run_id
        )
        manifest_path = run_dir / "run_manifest.json"
        if not run_dir.exists():
            status, manifest = "NOT_STARTED", None
        elif not manifest_path.is_file():
            status, manifest = "PRESENT_WITHOUT_MANIFEST", None
        else:
            status, manifest = _verify_manifest(
                manifest_path, project_id=project_id, run_id=run_id
            )
        counts[status] = counts.get(status, 0) + 1
        rows.append(
            {
                "sequence": len(rows) + 1,
                "experiment_id": experiment_id,
                "project_id": project_id,
                "run_id": run_id,
                "status": status,
                "manifest": manifest,
            }
        )
    return {
        "schema_version": 1,
        "role": "multipole_transport_campaign_status",
        "campaign_id": campaign["campaign_id"],
        "campaign_path": str(campaign_path.resolve()),
        "counts": counts,
        "experiments": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    document = campaign_status(args.repo_root, args.campaign)
    serialized = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

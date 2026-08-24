"""Publish and discover verified per-batch SIMION resource observations.

Only a completed single-process bootstrap run can teach the repository scheduler
about memory use.  In particular, an aggregate measurement from a parallel
wave is deliberately not divided by its process count: the processes can have
different peaks and shared memory makes that inference unsafe.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common.contracts.file_identity import file_sha256
from common.simion.resource_scheduler import RESOURCE_IDENTITY_KEYS


PROFILE_ROLE = "simion_resource_profile"
PROFILE_FILENAME = "simion_resource_profile.json"


def _load_json(path: Path, description: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {description}: {path}") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{description} must be a JSON object: {path}")
    return document


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _inside_run(run_dir: Path, relative_path: str, name: str) -> Path:
    path = (run_dir / relative_path).resolve()
    try:
        path.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError(f"{name} escapes its run directory") from exc
    return path


def publish_resource_profile(
    *, run_id: str, resource_usage_path: Path, dispatch_plan_path: Path,
    resource_usage_relative_path: str = "results/resource_usage.json",
    dispatch_plan_relative_path: str = "inputs/simion_repository_dispatch_plan.json",
) -> dict[str, Any]:
    """Build a profile from one completed, single-process bootstrap receipt."""
    usage = _load_json(resource_usage_path, "resource usage")
    plan = _load_json(dispatch_plan_path, "dispatch plan")
    if usage.get("role") != "multipole_resource_usage" or usage.get("status") != "completed":
        raise ValueError("resource usage must be a completed multipole receipt")
    wave = usage.get("execution_wave")
    if wave is not None and (
        not isinstance(wave, dict) or wave.get("process_count") != 1
    ):
        raise ValueError("resource usage must represent exactly one process")
    if plan.get("role") != "simion_repository_dispatch_plan":
        raise ValueError("dispatch plan role is not simion_repository_dispatch_plan")
    waves = plan.get("waves")
    if not isinstance(waves, list) or len(waves) != 1 or not isinstance(waves[0], dict):
        raise ValueError("dispatch plan must contain exactly one wave")
    if waves[0].get("kind") != "bootstrap" or waves[0].get("batch_count") != 1:
        raise ValueError("resource profile requires a one-batch bootstrap plan")
    identity = plan.get("resource_identity")
    if not isinstance(identity, dict) or identity.get("solver") != "SIMION":
        raise ValueError("dispatch plan has no SIMION resource identity")
    return {
        "schema_version": 1,
        "role": PROFILE_ROLE,
        "resource_identity": {key: identity.get(key) for key in RESOURCE_IDENTITY_KEYS},
        "per_batch_peak_working_set_bytes": _positive_int(
            usage.get("peak_process_tree_working_set_bytes"),
            "peak_process_tree_working_set_bytes",
        ),
        "source": {
            "run_id": run_id,
            "resource_usage": {
                "path": resource_usage_relative_path,
                "sha256": file_sha256(resource_usage_path),
            },
            "dispatch_plan": {
                "path": dispatch_plan_relative_path,
                "sha256": file_sha256(dispatch_plan_path),
            },
        },
    }


def _profile_from_verified_run(run_dir: Path) -> dict[str, Any] | None:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = _load_json(manifest_path, "run manifest")
        if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "success":
            return None
        records = manifest.get("outputs")
        if not isinstance(records, list):
            return None
        matches = [
            record for record in records
            if isinstance(record, dict) and Path(str(record.get("path", ""))).name == PROFILE_FILENAME
        ]
        if len(matches) != 1:
            return None
        record = matches[0]
        profile_path = Path(str(record["path"]))
        if not profile_path.is_absolute():
            profile_path = run_dir / profile_path
        if not profile_path.is_file() or file_sha256(profile_path) != str(record.get("sha256", "")).upper():
            return None
        profile = _load_json(profile_path, "resource profile")
        if profile.get("role") != PROFILE_ROLE or profile.get("schema_version") != 1:
            return None
        source = profile.get("source")
        if not isinstance(source, dict) or source.get("run_id") != manifest.get("run_id"):
            return None
        for name in ("resource_usage", "dispatch_plan"):
            source_record = source.get(name)
            if not isinstance(source_record, dict) or not isinstance(source_record.get("path"), str):
                return None
            source_path = _inside_run(run_dir, source_record["path"], f"profile {name}")
            if not source_path.is_file() or file_sha256(source_path) != str(source_record.get("sha256", "")).upper():
                return None
        rebuilt = publish_resource_profile(
            run_id=str(manifest["run_id"]),
            resource_usage_path=_inside_run(run_dir, source["resource_usage"]["path"], "profile resource usage"),
            dispatch_plan_path=_inside_run(run_dir, source["dispatch_plan"]["path"], "profile dispatch plan"),
            resource_usage_relative_path=source["resource_usage"]["path"],
            dispatch_plan_relative_path=source["dispatch_plan"]["path"],
        )
        return profile if rebuilt == profile else None
    except (KeyError, TypeError, ValueError):
        return None


def discover_resource_profiles(runs_root: Path) -> list[dict[str, Any]]:
    """Return only manifest-verified single-process bootstrap profiles."""
    if not runs_root.is_dir():
        return []
    profiles = [
        profile for run_dir in sorted(runs_root.iterdir()) if run_dir.is_dir()
        for profile in [_profile_from_verified_run(run_dir)] if profile is not None
    ]
    return profiles


def _profiles_from_manifest_summary(run_dir: Path) -> list[dict[str, Any]]:
    """Read case profiles only from a successful manifest-covered summary."""
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return []
    try:
        manifest = _load_json(manifest_path, "run manifest")
        if manifest.get("role") != "simulation_run_manifest" or manifest.get("status") != "success":
            return []
        records = manifest.get("outputs")
        if not isinstance(records, list):
            return []
        profiles: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                continue
            path_value = Path(record["path"])
            summary_path = path_value.resolve() if path_value.is_absolute() else _inside_run(
                run_dir, record["path"], "summary output"
            )
            try:
                summary_path.relative_to(run_dir.resolve())
            except ValueError:
                continue
            if not summary_path.is_file() or file_sha256(summary_path) != str(record.get("sha256", "")).upper():
                continue
            summary = _load_json(summary_path, "summary output")
            declarations = summary.get("simion_case_resource_profiles")
            if not isinstance(declarations, list):
                continue
            for declaration in declarations:
                if not isinstance(declaration, dict):
                    continue
                identity = declaration.get("resource_identity")
                peak = declaration.get("per_batch_peak_working_set_bytes")
                if (
                    not isinstance(identity, dict)
                    or identity.get("solver") != "SIMION"
                    or isinstance(peak, bool)
                    or not isinstance(peak, int)
                    or peak < 1
                ):
                    continue
                profiles.append({
                    "resource_identity": identity,
                    "per_batch_peak_working_set_bytes": peak,
                    "source": {"run_id": manifest.get("run_id"), "summary": str(summary_path)},
                })
        return profiles
    except (KeyError, OSError, TypeError, ValueError):
        return []


def discover_case_resource_profiles(runs_root: Path) -> list[dict[str, Any]]:
    """Discover only manifest-verified complete-case peak observations."""
    if not runs_root.is_dir():
        return []
    return [
        profile for run_dir in sorted(runs_root.iterdir()) if run_dir.is_dir()
        for profile in _profiles_from_manifest_summary(run_dir)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    publish = subparsers.add_parser("publish")
    publish.add_argument("--run-id", required=True)
    publish.add_argument("--resource-usage", type=Path, required=True)
    publish.add_argument("--dispatch-plan", type=Path, required=True)
    publish.add_argument("--resource-usage-relative-path", default="results/resource_usage.json")
    publish.add_argument("--dispatch-plan-relative-path", default="inputs/simion_repository_dispatch_plan.json")
    publish.add_argument("--output", type=Path, required=True)
    discover = subparsers.add_parser("discover")
    discover.add_argument("--runs-root", type=Path, required=True)
    discover.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "publish":
        document = publish_resource_profile(
            run_id=args.run_id, resource_usage_path=args.resource_usage,
            dispatch_plan_path=args.dispatch_plan,
            resource_usage_relative_path=args.resource_usage_relative_path,
            dispatch_plan_relative_path=args.dispatch_plan_relative_path,
        )
        message = "SIMION_RESOURCE_PROFILE=PASS"
    else:
        document = discover_resource_profiles(args.runs_root)
        message = f"SIMION_RESOURCE_PROFILES=PASS COUNT={len(document)}"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

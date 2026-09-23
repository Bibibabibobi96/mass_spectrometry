"""Bind static MR-TOF PA dependencies to a prepared native corridor runtime.

The detached native corridor bank owns the adjustable analyser response field.
This module records the three remaining standalone PA dependencies by their
already-verified run-manifest identities.  It deliberately never opens a PA
payload for hashing, copying, refinement, or SIMION execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.downstream_fixed_grid_workpoint import (
    native_bank_identity,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


_COMPONENT_ROLES = ("global_fallback", "accelerator", "detector")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise CandidateContractError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise CandidateContractError(f"{label} is not JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _component_record(
    role: str, request: Mapping[str, Any], *, project_id: str,
) -> dict[str, Any]:
    manifest_path = Path(str(request.get("manifest_path", ""))).resolve()
    manifest = _load_json(manifest_path, f"{role} source manifest")
    if manifest.get("status") != "success" or manifest.get("project") != project_id:
        raise CandidateContractError(f"{role} source manifest is not verified successful project evidence")
    pa_path = Path(str(request.get("pa_path", ""))).resolve()
    if pa_path.suffix.lower() != ".pa":
        raise CandidateContractError(f"{role} must be a standalone .pa, not a PA-family member")
    records = manifest.get("outputs")
    if not isinstance(records, list):
        raise CandidateContractError(f"{role} source manifest lacks outputs")
    matching = [record for record in records if isinstance(record, Mapping)
                and Path(str(record.get("path", ""))).resolve() == pa_path]
    if len(matching) != 1:
        raise CandidateContractError(f"{role} PA is not uniquely bound by its source manifest")
    record = matching[0]
    expected_bytes = record.get("bytes")
    expected_sha = record.get("sha256")
    if (not isinstance(expected_bytes, int) or expected_bytes < 1
            or not isinstance(expected_sha, str) or _SHA256.fullmatch(expected_sha) is None):
        raise CandidateContractError(f"{role} PA source record lacks a valid immutable identity")
    if not pa_path.is_file() or pa_path.stat().st_size != expected_bytes:
        raise CandidateContractError(f"{role} PA byte count is unavailable or differs from its source record")
    return {
        "role": role,
        "source_kind": "mrtof_manifest",
        "pa_path": str(pa_path),
        "bytes": expected_bytes,
        "sha256": expected_sha.upper(),
        "source_manifest_path": str(manifest_path),
        "source_manifest_sha256": _sha256(manifest_path),
    }


def _provider_accelerator_record(provider_receipt_path: Path) -> dict[str, Any]:
    """Bind an OA-owned controller through its published runtime receipt."""
    receipt_path = provider_receipt_path.resolve()
    receipt = _load_json(receipt_path, "accelerator provider receipt")
    controller = receipt.get("read_only_controller_pa0")
    if (receipt.get("role") != "orthogonal_accelerator_mrtof_runtime_receipt"
            or receipt.get("status") != "published_read_only"
            or not isinstance(controller, Mapping)):
        raise CandidateContractError("accelerator provider receipt is not published OA runtime evidence")
    pa_path = Path(str(controller.get("path", ""))).resolve()
    expected_bytes, expected_sha = controller.get("bytes"), controller.get("sha256")
    if (pa_path.suffix.lower() != ".pa0" or not isinstance(expected_bytes, int) or expected_bytes < 1
            or not isinstance(expected_sha, str) or _SHA256.fullmatch(expected_sha) is None
            or not pa_path.is_file() or pa_path.stat().st_size != expected_bytes):
        raise CandidateContractError("accelerator provider controller identity is unavailable")
    # The provider receipt binds the controller hash.  This projection must not
    # reread the PA payload merely to assemble MR's dependency receipt.
    return {"role": "accelerator", "source_kind": "orthogonal_accelerator_provider_receipt",
            "pa_path": str(pa_path), "bytes": expected_bytes, "sha256": expected_sha.upper(),
            "provider_receipt_path": str(receipt_path), "provider_receipt_sha256": _sha256(receipt_path),
            "provider_pa_family": receipt.get("pa_family")}


def build_native_system_runtime_bundle(
    *, native_corridor_runtime_receipt: Mapping[str, Any],
    component_requests: Mapping[str, Mapping[str, Any]],
    accelerator_provider_receipt: Path,
    project_id: str = "parallel_mirror_dual_stripe_mr_tof",
) -> dict[str, Any]:
    """Create a no-payload-copy native system dependency receipt.

    The caller must have performed the normal run-manifest consumer projection
    before construction.  This function consumes only its compact manifest and
    records the PA identity already frozen there.
    """
    if set(component_requests) != {"global_fallback", "detector"}:
        raise CandidateContractError("native system bundle requires exactly global_fallback and detector; accelerator is OA provider-owned")
    accelerator = _provider_accelerator_record(accelerator_provider_receipt)
    components = [_component_record("global_fallback", component_requests["global_fallback"], project_id=project_id), accelerator,
                  _component_record("detector", component_requests["detector"], project_id=project_id)]
    return {
        "schema_version": 1,
        "role": "mrtof_native_system_runtime_bundle",
        "status": "prepared",
        "project": project_id,
        "native_bank_identity": native_bank_identity(native_corridor_runtime_receipt),
        "components": components,
        "pa_copy_performed": False,
        "pa_refine_performed": False,
        "legacy_local_workbench_allowed": False,
    }


def resolve_native_system_runtime_bundle(
    bundle_path: Path | None,
    *, native_corridor_runtime_receipt: Mapping[str, Any],
) -> dict[str, Path]:
    """Validate a bundle and return the three static PA paths for one flight.

    A native flight must pass the bundle.
    """
    if bundle_path is None:
        raise CandidateContractError("native system runtime bundle is required for a native corridor flight")
    bundle_location = Path(bundle_path).resolve()
    bundle = _load_json(bundle_location, "native system runtime bundle")
    if (bundle.get("schema_version") != 1
            or bundle.get("role") != "mrtof_native_system_runtime_bundle"
            or bundle.get("status") != "prepared"
            or bundle.get("pa_copy_performed") is not False
            or bundle.get("pa_refine_performed") is not False
            or bundle.get("legacy_local_workbench_allowed") is not False):
        raise CandidateContractError("native system runtime bundle contract is invalid")
    if bundle.get("native_bank_identity") != native_bank_identity(native_corridor_runtime_receipt):
        raise CandidateContractError("native system runtime bundle belongs to another native bank")
    components = bundle.get("components")
    if not isinstance(components, list) or [item.get("role") for item in components if isinstance(item, Mapping)] != list(_COMPONENT_ROLES):
        raise CandidateContractError("native system runtime bundle component roles are invalid")
    resolved: dict[str, Path] = {}
    for component in components:
        if not isinstance(component, Mapping):
            raise CandidateContractError("native system runtime component is invalid")
        if component.get("source_kind") == "orthogonal_accelerator_provider_receipt":
            refreshed = _provider_accelerator_record(Path(str(component.get("provider_receipt_path", ""))))
            if (refreshed["provider_receipt_sha256"] != component.get("provider_receipt_sha256")
                    or refreshed["pa_path"] != component.get("pa_path") or refreshed["sha256"] != component.get("sha256")):
                raise CandidateContractError("accelerator provider receipt identity changed")
            resolved["accelerator"] = Path(refreshed["pa_path"])
            continue
        manifest_path = Path(str(component.get("source_manifest_path", ""))).resolve()
        if _sha256(manifest_path) != component.get("source_manifest_sha256"):
            raise CandidateContractError("native system runtime source manifest identity changed")
        pa_path = Path(str(component.get("pa_path", ""))).resolve()
        expected_bytes = component.get("bytes")
        expected_sha = component.get("sha256")
        if (pa_path.suffix.lower() != ".pa" or not isinstance(expected_bytes, int)
                or not isinstance(expected_sha, str) or _SHA256.fullmatch(expected_sha) is None
                or not pa_path.is_file() or pa_path.stat().st_size != expected_bytes):
            raise CandidateContractError(f"native system runtime {component.get('role')} PA is unavailable")
        resolved[str(component["role"])] = pa_path
    return resolved


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    """Persist a newly prepared receipt without replacing another receipt."""
    location = Path(path).resolve()
    if location.exists():
        raise CandidateContractError(f"native system runtime bundle output already exists: {location}")
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def rebind_accelerator_provider(*, base_bundle_path: Path, native_corridor_runtime_receipt: Mapping[str, Any],
                                accelerator_provider_receipt: Path) -> dict[str, Any]:
    """Retain MR's static records and replace only its accelerator binding."""
    base = _load_json(base_bundle_path.resolve(), "base native system runtime bundle")
    components = base.get("components")
    if (base.get("role") != "mrtof_native_system_runtime_bundle" or not isinstance(components, list)
            or [item.get("role") for item in components if isinstance(item, Mapping)] != list(_COMPONENT_ROLES)):
        raise CandidateContractError("base native system runtime bundle contract is invalid")
    resolve_native_system_runtime_bundle(
        base_bundle_path, native_corridor_runtime_receipt=native_corridor_runtime_receipt,
    )
    retained = {str(item["role"]): dict(item) for item in components if isinstance(item, Mapping)}
    accelerator = _provider_accelerator_record(accelerator_provider_receipt)
    return {
        "schema_version": 1,
        "role": "mrtof_native_system_runtime_bundle",
        "status": "prepared",
        "project": base.get("project"),
        "native_bank_identity": native_bank_identity(native_corridor_runtime_receipt),
        "components": [retained["global_fallback"], accelerator, retained["detector"]],
        "pa_copy_performed": False,
        "pa_refine_performed": False,
        "legacy_local_workbench_allowed": False,
    }


def _read_receipt_argument(path: str) -> dict[str, Any]:
    return _load_json(Path(path).resolve(), "native corridor runtime receipt")


def _component_request_arguments(arguments: argparse.Namespace) -> dict[str, dict[str, str]]:
    return {
        role: {
            "manifest_path": str(getattr(arguments, f"{role}_manifest")),
            "pa_path": str(getattr(arguments, f"{role}_pa")),
        }
        for role in ("global_fallback", "detector")
    }


def _add_component_arguments(parser: argparse.ArgumentParser) -> None:
    for role in ("global_fallback", "detector"):
        option = role.replace("_", "-")
        parser.add_argument(f"--{option}-manifest", required=True, metavar="PATH")
        parser.add_argument(f"--{option}-pa", required=True, metavar="PATH")


def build_argument_parser() -> argparse.ArgumentParser:
    """Return the transport-only CLI for the native system dependency receipt."""
    parser = argparse.ArgumentParser(description="Prepare or resolve an MR-TOF native system runtime bundle.")
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="Bind existing static PA identities without opening PA payloads.")
    build.add_argument("--native-corridor-runtime-receipt", required=True, metavar="PATH")
    build.add_argument("--bundle-output", required=True, metavar="PATH")
    _add_component_arguments(build)
    build.add_argument("--accelerator-provider-receipt", required=True, metavar="PATH")

    resolve = commands.add_parser("resolve", help="Resolve a prepared bundle for a native flight.")
    resolve.add_argument("--native-corridor-runtime-receipt", required=True, metavar="PATH")
    resolve.add_argument("--bundle", required=True, metavar="PATH")
    rebind = commands.add_parser("rebind-accelerator", help="Replace only the accelerator with an OA receipt.")
    rebind.add_argument("--native-corridor-runtime-receipt", required=True, metavar="PATH")
    rebind.add_argument("--base-bundle", required=True, metavar="PATH")
    rebind.add_argument("--accelerator-provider-receipt", required=True, metavar="PATH")
    rebind.add_argument("--bundle-output", required=True, metavar="PATH")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute a compact manifest-only bundle command and print JSON to stdout."""
    arguments = build_argument_parser().parse_args(argv)
    receipt = _read_receipt_argument(arguments.native_corridor_runtime_receipt)
    try:
        if arguments.command == "build":
            bundle = build_native_system_runtime_bundle(
                native_corridor_runtime_receipt=receipt,
                component_requests=_component_request_arguments(arguments),
                accelerator_provider_receipt=Path(arguments.accelerator_provider_receipt),
            )
            _write_new_json(Path(arguments.bundle_output), bundle)
            output: Mapping[str, Any] = bundle
        elif arguments.command == "rebind-accelerator":
            bundle = rebind_accelerator_provider(base_bundle_path=Path(arguments.base_bundle),
                                                 native_corridor_runtime_receipt=receipt,
                                                 accelerator_provider_receipt=Path(arguments.accelerator_provider_receipt))
            _write_new_json(Path(arguments.bundle_output), bundle)
            output = bundle
        else:
            resolved = resolve_native_system_runtime_bundle(
                Path(arguments.bundle), native_corridor_runtime_receipt=receipt,
            )
            output = {role: str(path) for role, path in resolved.items()}
    except CandidateContractError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Define the detached-runtime response bank for the full MR-TOF corridor.

The native C4 family is an immutable build artifact.  Its ``.paN`` members
must never be reopened by SIMION after publication.  This module derives a
separate content-addressed bank which is built once from the same frozen
corridor inputs.  The bank retains the raw geometry, private-build native
responses and their freshly exported standalone counterparts; runtime
consumers select only the latter through ``standalone_pa_response_set``.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from common.contracts.file_identity import file_sha256
from common.simion.pa_family_cache import canonical_pa_family_cache_key
from common.simion.standalone_pa_response_set import (
    ResponseExport,
    select_standalone_pa_records,
    validate_standalone_pa_response_set,
    write_standalone_pa_response_set,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError,
)


FROZEN_NAMES = (
    "native_corridor_identity.json",
    "native_corridor_plan.json",
    "native_corridor_response_recipe.json",
    "native_corridor_freeze_manifest.json",
)
RECEIPT_NAME = "mrtof_analyzer_corridor.standalone_responses.json"
RAW_NAME = "mrtof_analyzer_corridor.pa#"
NATIVE_RESPONSE_NAMES = tuple(f"mrtof_analyzer_corridor.pa{identifier}" for identifier in range(1, 9))
STANDALONE_RESPONSE_NAMES = tuple(
    f"mrtof_analyzer_corridor.response{identifier}.pa" for identifier in range(1, 9)
)


def response_bank_filenames() -> tuple[str, ...]:
    """Return the exact immutable payload covered by the response-set receipt."""

    return (RAW_NAME, *NATIVE_RESPONSE_NAMES, *STANDALONE_RESPONSE_NAMES, RECEIPT_NAME)


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CandidateContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CandidateContractError(f"{label} must be a JSON object")
    return value


def _sha256(value: object, *, label: str) -> str:
    text = str(value).upper()
    if len(text) != 64 or any(character not in "0123456789ABCDEF" for character in text):
        raise CandidateContractError(f"{label} must be one SHA-256")
    return text


def _frozen_documents(directory: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate the small frozen package without reading any PA payload."""

    root = directory.resolve()
    if not root.is_dir() or root.is_symlink():
        raise CandidateContractError("native corridor frozen input directory is invalid")
    if {path.name for path in root.iterdir()} != set(FROZEN_NAMES):
        raise CandidateContractError("native corridor frozen input inventory differs")
    manifest = _load_json(root / FROZEN_NAMES[3], label="native corridor freeze manifest")
    if manifest.get("role") != "mrtof_native_corridor_frozen_inputs" or manifest.get("status") != "frozen":
        raise CandidateContractError("native corridor freeze manifest identity differs")
    records = manifest.get("files")
    if not isinstance(records, list) or {record.get("name") for record in records if isinstance(record, dict)} != set(FROZEN_NAMES[:3]):
        raise CandidateContractError("native corridor freeze manifest inventory differs")
    for record in records:
        if not isinstance(record, dict) or set(record) != {"name", "bytes", "sha256"}:
            raise CandidateContractError("native corridor freeze file record differs")
        path = root / str(record["name"])
        if not path.is_file() or path.stat().st_size != record["bytes"] or file_sha256(path).upper() != _sha256(record["sha256"], label="freeze file hash"):
            raise CandidateContractError(f"native corridor frozen input identity differs: {path.name}")
    identity = _load_json(root / FROZEN_NAMES[0], label="native corridor identity")
    plan = _load_json(root / FROZEN_NAMES[1], label="native corridor plan")
    recipe = _load_json(root / FROZEN_NAMES[2], label="native corridor response recipe")
    if plan.get("role") != "mrtof_analyzer_full_flight_native_corridor":
        raise CandidateContractError("native corridor plan identity differs")
    recipes = recipe.get("response_recipes")
    if recipe.get("role") != "mrtof_native_corridor_response_recipe" or not isinstance(recipes, list) or [entry.get("local_id") for entry in recipes if isinstance(entry, dict)] != list(range(1, 9)):
        raise CandidateContractError("native corridor response recipe differs")
    return identity, plan, recipe


def derive_response_bank_identity(
    frozen_input_directory: Path,
    *,
    simion_executable: Path,
    simion_release: str,
) -> dict[str, Any]:
    """Derive one bank identity from frozen C4 inputs and current build helpers."""

    if not simion_executable.is_file() or not simion_release.strip():
        raise CandidateContractError("response bank requires SIMION executable and release")
    native_identity, plan, recipe = _frozen_documents(frozen_input_directory)
    required = {
        "geometry", "gem", "basis_namespace", "mesh", "grid_phase", "surface",
        "simion_identity", "refine_policy", "builder_identity",
    }
    if set(native_identity) != required:
        raise CandidateContractError("native corridor identity fields differ")
    project_root = Path(__file__).resolve().parents[1]
    repository_root = project_root.parents[1]
    simion_root = repository_root / "common" / "simion"
    frozen_root = frozen_input_directory.resolve()
    identity = {
        "geometry": {
            "component_role": "mrtof_native_corridor_detached_response_bank",
            "frozen_package_sha256": {
                name: file_sha256(frozen_root / name).upper()
                for name in FROZEN_NAMES
            },
            "source_corridor_geometry": native_identity["geometry"],
        },
        "gem": native_identity["gem"],
        "basis_namespace": {
            "response_ids": list(range(1, 9)),
            "native_response_names": list(NATIVE_RESPONSE_NAMES),
            "standalone_response_names": list(STANDALONE_RESPONSE_NAMES),
            "response_recipe": recipe,
        },
        "mesh": native_identity["mesh"],
        "grid_phase": native_identity["grid_phase"],
        "surface": native_identity["surface"],
        "simion_identity": {
            "release": simion_release,
            "executable_sha256": file_sha256(simion_executable).upper(),
        },
        "refine_policy": {
            "mode": "full_corridor_direct_dirichlet_response_build",
            "solutions": "one_10000_v_response_per_local_id",
            "runtime_input": "detached_standalone_responses_only",
            "published_native_member_opening": "forbidden",
        },
        "builder_identity": {
            "response_bank_adapter_sha256": file_sha256(Path(__file__)).upper(),
            "geometry_generator_sha256": file_sha256(project_root / "analysis" / "native_corridor_geometry.py").upper(),
            "legacy_private_worker_sha256": file_sha256(project_root / "simion" / "run_native_corridor_qualification.ps1").upper(),
            "standalone_exporter_sha256": file_sha256(simion_root / "export_standalone_pa.lua").upper(),
            "response_set_contract_sha256": file_sha256(simion_root / "standalone_pa_response_set.py").upper(),
        },
    }
    # Touch these explicitly so malformed frozen plans cannot silently become
    # a valid identity through an unused field.
    if plan.get("response_ids") != list(range(1, 9)):
        raise CandidateContractError("native corridor plan response IDs differ")
    canonical_pa_family_cache_key(identity)
    return identity


def select_runtime_response_bank(generation_directory: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Select manifest-bound detached responses; native members are never returned."""

    records = select_standalone_pa_records(
        generation_directory,
        manifest,
        RECEIPT_NAME,
        expected_response_ids=range(1, 9),
    )
    return [
        {"response_id": record.response_id, "name": record.name, "bytes": record.bytes, "sha256": record.sha256}
        for record in records
    ]


def write_response_bank_receipt(directory: Path) -> dict[str, Any]:
    """Bind all eight private-build native members to detached response files."""

    project_root = Path(__file__).resolve().parents[1]
    return write_standalone_pa_response_set(
        directory,
        project_root.parents[1] / "common" / "simion" / "export_standalone_pa.lua",
        [
            ResponseExport(identifier, NATIVE_RESPONSE_NAMES[identifier - 1], STANDALONE_RESPONSE_NAMES[identifier - 1])
            for identifier in range(1, 9)
        ],
        directory / RECEIPT_NAME,
    )


def verify_response_bank_staging(directory: Path) -> dict[str, Any]:
    """Verify the complete private bank inventory before cache publication."""

    root = directory.resolve()
    names = response_bank_filenames()
    if not root.is_dir() or {path.name for path in root.iterdir() if path.is_file()} != set(names):
        raise CandidateContractError("native corridor response-bank staging inventory differs")
    records = [
        {"name": name, "bytes": (root / name).stat().st_size, "sha256": file_sha256(root / name).upper()}
        for name in names
    ]
    manifest = {"schema_version": 3, "files": records}
    selected = validate_standalone_pa_response_set(
        root, manifest, RECEIPT_NAME, expected_response_ids=range(1, 9)
    )
    if tuple(item.name for item in selected) != STANDALONE_RESPONSE_NAMES:
        raise CandidateContractError("native corridor response-bank runtime selection differs")
    return {"role": "mrtof_native_corridor_response_bank_staging", "status": "pass", "responses": len(selected)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-input-directory", type=Path)
    parser.add_argument("--simion-executable", type=Path)
    parser.add_argument("--simion-release")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write-receipt-directory", type=Path)
    parser.add_argument("--verify-staging-directory", type=Path)
    arguments = parser.parse_args()
    if arguments.write_receipt_directory is not None:
        if any(value is not None for value in (arguments.frozen_input_directory, arguments.simion_executable, arguments.simion_release, arguments.output, arguments.verify_staging_directory)):
            parser.error("--write-receipt-directory cannot be combined with identity arguments")
        print(json.dumps(write_response_bank_receipt(arguments.write_receipt_directory), ensure_ascii=False, sort_keys=True))
        return 0
    if arguments.verify_staging_directory is not None:
        if any(value is not None for value in (arguments.frozen_input_directory, arguments.simion_executable, arguments.simion_release, arguments.output)):
            parser.error("--verify-staging-directory cannot be combined with identity arguments")
        print(json.dumps(verify_response_bank_staging(arguments.verify_staging_directory), ensure_ascii=False, sort_keys=True))
        return 0
    if arguments.frozen_input_directory is None or arguments.simion_executable is None or arguments.simion_release is None:
        parser.error("identity requires --frozen-input-directory, --simion-executable and --simion-release")
    identity = derive_response_bank_identity(
        arguments.frozen_input_directory,
        simion_executable=arguments.simion_executable,
        simion_release=arguments.simion_release,
    )
    text = json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.output is None:
        print(text, end="")
    else:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

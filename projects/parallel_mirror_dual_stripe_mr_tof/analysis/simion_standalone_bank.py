"""Validate the detached accelerator response bank without opening native PA members."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Sequence

from common.simion.pa_family_cache import (
    POINTER_NAME,
    PAFamilyCacheError,
    validate_pa_family_cache_subset,
)


SHA256 = re.compile(r"^[0-9A-F]{64}$")


def _direct_name(value: Any, label: str, *, suffix: str | None = None) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise PAFamilyCacheError(f"{label} must be one direct filename")
    if suffix is not None and Path(value).suffix.casefold() != suffix.casefold():
        raise PAFamilyCacheError(f"{label} must end in {suffix}")
    return value


def _load_document(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PAFamilyCacheError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise PAFamilyCacheError(f"{label} must be a JSON object")
    return value


def validate_accelerator_standalone_bank(
    cache_root: Path,
    publication_path: Path,
) -> dict[str, Any]:
    """Return a receipt for the exact detached bank declared by one family run.

    The native family remains a build-stage provenance object.  This validator
    hashes only the base, export receipt, response PAs and normalization receipts
    that the operating-point composer will actually consume.
    """

    publication = _load_document(publication_path, "accelerator family publication")
    cache_key = publication.get("cache_key")
    generation_sha256 = publication.get("generation_sha256")
    if not isinstance(cache_key, str) or SHA256.fullmatch(cache_key) is None:
        raise PAFamilyCacheError("accelerator family publication cache key is invalid")
    if not isinstance(generation_sha256, str) or SHA256.fullmatch(generation_sha256) is None:
        raise PAFamilyCacheError("accelerator family publication generation is invalid")
    key_root = cache_root.resolve() / cache_key
    pointer = _load_document(key_root / POINTER_NAME, "accelerator family cache pointer")
    if set(pointer) != {"cache_key", "generation_sha256"} or pointer != {
        "cache_key": cache_key,
        "generation_sha256": generation_sha256,
    }:
        raise PAFamilyCacheError("accelerator family cache pointer differs from publication")
    generation = (key_root / "generations" / generation_sha256).resolve()
    declared_generation = publication.get("generation_directory")
    if not isinstance(declared_generation, str) or Path(declared_generation).resolve() != generation:
        raise PAFamilyCacheError("accelerator family generation path differs from publication")

    contract = publication.get("standalone_response_contract")
    if (
        not isinstance(contract, dict)
        or contract.get("schema_version") != 1
        or contract.get("role") != "mrtof_accelerator_standalone_response_bank"
    ):
        raise PAFamilyCacheError("accelerator standalone response contract identity differs")
    base = _direct_name(contract.get("base_filename"), "standalone base", suffix=".pa")
    base_receipt = _direct_name(
        contract.get("base_export_receipt_filename"), "standalone base receipt", suffix=".json"
    )
    responses = contract.get("responses")
    if not isinstance(responses, list) or len(responses) != 9:
        raise PAFamilyCacheError("accelerator standalone response inventory must contain nine responses")
    filenames = [base, base_receipt]
    electrode_ids: list[int] = []
    for response in responses:
        if not isinstance(response, dict):
            raise PAFamilyCacheError("accelerator standalone response entry must be an object")
        electrode_id = response.get("electrode_id")
        if not isinstance(electrode_id, int) or isinstance(electrode_id, bool):
            raise PAFamilyCacheError("accelerator standalone response electrode ID is invalid")
        electrode_ids.append(electrode_id)
        filenames.extend(
            (
                _direct_name(
                    response.get("standalone_response_filename"),
                    f"standalone response {electrode_id}",
                    suffix=".pa",
                ),
                _direct_name(
                    response.get("normalization_receipt_filename"),
                    f"standalone response {electrode_id} normalization",
                    suffix=".csv",
                ),
            )
        )
    if sorted(electrode_ids) != list(range(1, 10)) or len(set(filenames)) != len(filenames):
        raise PAFamilyCacheError("accelerator standalone response IDs or filenames differ")
    manifest = validate_pa_family_cache_subset(
        generation,
        filenames,
        expected_cache_key=cache_key,
    )
    if manifest["generation_sha256"] != generation_sha256:
        raise PAFamilyCacheError("accelerator standalone manifest generation differs")
    return {
        "schema_version": 1,
        "role": "mrtof_accelerator_standalone_bank_validation",
        "disposition": "hit",
        "cache_key": cache_key,
        "generation_sha256": generation_sha256,
        "generation_directory": str(generation),
        "validated_filenames": sorted(filenames),
        "standalone_response_contract": contract,
        "native_family_members_opened": False,
        "complete_native_generation_qualified": False,
    }


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--publication", type=Path, required=True)
    args = parser.parse_args(arguments)
    print(
        json.dumps(
            validate_accelerator_standalone_bank(args.cache_root, args.publication),
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

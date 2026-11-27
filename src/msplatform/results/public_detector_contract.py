"""Read the immutable detector declaration frozen with one public SCI run."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from msplatform.io.file_identity import file_sha256
from msplatform.io.manifest_records import validate_file_record


def read_public_detector_contract(run_path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a single-cohort public run's frozen source plan and detector binding.

    The caller must first authenticate the Store run and hold its files against
    concurrent modification throughout this read. The original native source
    reference records identity at capture; its cache may since be reclaimed.
    Multi-batch contracts are deliberately unsupported until every batch's
    detector binding is checked.
    """
    root = Path(run_path).resolve(strict=True)
    if (root / "detector_contracts").exists():
        raise ValueError("multi-batch detector contracts are not supported")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("public run manifest has no file inventory")
    payloads = {}
    for name in ("detector_contract.json", "detector_plan.json", "detector_native_facts.json"):
        record = files.get(name)
        path = root / name
        if (not isinstance(record, dict) or set(record) != {"bytes", "sha256"}
                or type(record["bytes"]) is not int or record["bytes"] < 0
                or not isinstance(record["sha256"], str) or not path.is_file()
                or path.stat().st_size != record["bytes"]
                or file_sha256(path).lower() != record["sha256"].lower()):
            raise ValueError("public detector snapshot does not match the run manifest")
        payloads[name] = json.loads(path.read_text(encoding="utf-8-sig"))
    contract, plan, facts = (payloads["detector_contract.json"], payloads["detector_plan.json"],
                             payloads["detector_native_facts.json"])
    required = {"schema_version", "role", "backend", "source_reference", "source_plan_sha256",
                "source_facts_sha256", "detector_active_face"}
    if (not isinstance(contract, dict) or set(contract) != required or type(contract["schema_version"]) is not int
            or contract["schema_version"] != 1 or contract["role"] != "public_native_detector_contract"
            or contract["backend"] != "comsol" or not isinstance(plan, dict) or not isinstance(facts, dict)):
        raise ValueError("public detector contract schema differs")
    reference = contract["source_reference"]
    if not isinstance(reference, dict) or set(reference) != {"manifest", "product_id"} or reference["product_id"] != "trajectory":
        raise ValueError("public detector source reference differs")
    source_manifest = validate_file_record(reference["manifest"], "detector source manifest")
    if not Path(source_manifest["path"]).is_absolute():
        raise ValueError("public detector source manifest path must be absolute")
    if (not isinstance(contract["source_plan_sha256"], str)
            or contract["source_plan_sha256"].lower() != files["detector_plan.json"]["sha256"].lower()
            or not isinstance(contract["source_facts_sha256"], str)
            or contract["source_facts_sha256"].lower() != files["detector_native_facts.json"]["sha256"].lower()
            or contract["detector_active_face"] != plan.get("detector_active_face")):
        raise ValueError("public detector contract does not match its frozen plan")
    face = contract["detector_active_face"]
    if face is not None and (not isinstance(face, dict) or not isinstance(face.get("surface_id"), str)
                             or not face["surface_id"]):
        raise ValueError("public detector surface identity differs")
    return dict(contract, plan=plan, native_facts=facts)

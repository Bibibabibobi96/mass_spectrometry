"""Create the explicit transaction contract required by oaTOF Formal writers."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from common.contracts.machine_contracts import load_json, sha256


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = PROJECT_ROOT.parents[2] / "artifacts" / "projects" / "oa_tof"


def prepare(
    candidate_model: Path,
    acceptance_path: Path,
    output_path: Path,
    formal_root: Path = ARTIFACT_ROOT / "formal",
) -> dict[str, object]:
    candidate_model = candidate_model.resolve()
    acceptance_path = acceptance_path.resolve()
    if not candidate_model.is_file() or not acceptance_path.is_file():
        raise ValueError("promotion candidate model and acceptance evidence must exist")
    acceptance = load_json(acceptance_path)
    if (
        acceptance.get("role") != "oa_tof_candidate_acceptance"
        or acceptance.get("status") != "success"
        or acceptance.get("formal_modified") is not False
        or acceptance.get("promotion_authorized") is not False
    ):
        raise ValueError("candidate acceptance is not valid pre-promotion evidence")
    identity = sha256(candidate_model)[:16].lower()
    transaction = {
        "schema_version": 1,
        "role": "oa_tof_formal_promotion_transaction",
        "project": "oa_tof",
        "status": "authorized",
        "authorization_id": identity,
        "authorized_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "candidate_model": str(candidate_model),
            "candidate_model_sha256": sha256(candidate_model),
            "acceptance": str(acceptance_path),
            "acceptance_sha256": sha256(acceptance_path),
        },
        "destinations": {
            "comsol_model": str((formal_root / "comsol" / "oa_tof__model.mph").resolve()),
            "cad_root": str((formal_root / "cad").resolve()),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(transaction, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return transaction


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-model", type=Path, required=True)
    parser.add_argument("--acceptance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    transaction = prepare(args.candidate_model, args.acceptance, args.output)
    print(f"FORMAL_PROMOTION_TRANSACTION=AUTHORIZED ID={transaction['authorization_id']}")


if __name__ == "__main__":
    main()

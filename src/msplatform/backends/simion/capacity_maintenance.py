"""Compose governed capacity maintenance with the SIMION PA-cache owner."""
from __future__ import annotations

from pathlib import Path

from msplatform.backends.simion.pa_family_cache import (
    approve_pa_family_cache_retirement,
    audit_pa_transaction_maintenance,
)
from msplatform.execution import artifact_capacity_maintenance


def _audit_transactions(root: Path) -> dict[str, int]:
    return audit_pa_transaction_maintenance(root / "common" / "simion" / "pa_family_cache")


def main() -> None:
    artifact_capacity_maintenance.main(
        approve_retirement=approve_pa_family_cache_retirement,
        pa_transaction_audit=_audit_transactions,
    )


if __name__ == "__main__":
    main()

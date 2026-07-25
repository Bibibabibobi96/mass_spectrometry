"""History-only compatibility entry for the retired 25-particle closure.

Current cross-solver evidence must use
``workflows/interface_readiness/compare_cross_solver.ps1`` for interface readiness
or ``workflows/no_collision_transport/compare_cross_solver.ps1`` for component
regression. Keeping another comparison implementation would allow threshold
and physical-authority drift.
"""

from __future__ import annotations


def main() -> None:
    """Fail closed instead of executing the retired comparison logic."""
    raise SystemExit(
        "HISTORY_ONLY: use workflows/interface_readiness/compare_cross_solver.ps1"
    )


if __name__ == "__main__":
    main()

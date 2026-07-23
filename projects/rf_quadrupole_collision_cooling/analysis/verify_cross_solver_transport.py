"""History-only compatibility entry for the retired 25-particle closure.

Current cross-solver evidence must use
``tests/cross_solver/verify_transport_candidate.ps1`` and its governed
``compare_particle_state.py`` implementation.  Keeping a second comparison
implementation would allow threshold and physical-authority drift.
"""

from __future__ import annotations


def main() -> None:
    """Fail closed instead of executing the retired comparison logic."""
    raise SystemExit(
        "HISTORY_ONLY: use tests/cross_solver/verify_transport_candidate.ps1"
    )


if __name__ == "__main__":
    main()

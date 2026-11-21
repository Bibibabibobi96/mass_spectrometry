"""Project forwarding for installed Candidate consumer preparation."""
from __future__ import annotations

import sys
from pathlib import Path

from msplatform.workflows.oa_candidate.prepare_candidate_consumers import (
    prepare as _prepare,
    verify_routing_coverage as verify_routing_coverage,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parents[1]


def prepare(contract_path: Path, output_dir: Path, particle_source_seed: int | None = None) -> dict[str, Path]:
    return _prepare(
        contract_path, output_dir, particle_source_seed=particle_source_seed,
        science_root=REPO_ROOT,
    )


def main() -> None:
    from msplatform.workflows.oa_candidate.prepare_candidate_consumers import main as installed_main
    if "--science-root" not in sys.argv:
        sys.argv.extend(["--science-root", str(REPO_ROOT)])
    installed_main()


if __name__ == "__main__":
    main()

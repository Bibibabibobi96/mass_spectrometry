"""Ensure a multipole project artifact root has the repository-required index."""

from __future__ import annotations

import argparse
from pathlib import Path


def ensure_artifact_project(artifact_projects_root: Path, project_id: str) -> Path:
    project_root = artifact_projects_root / project_id
    project_root.mkdir(parents=True, exist_ok=True)
    readme = project_root / "00_README.txt"
    expected = (
        f"PROJECT: {project_id}\n\n"
        "formal/   absent: no current asset has passed the formal gates\n"
        "runs/     self-contained current runs, named by run_id\n"
        "archive/  frozen evidence, named by archive_id\n"
        "scratch/  disposable active work only; never a citation source\n\n"
        "Authoritative rules and project status are in simulation_repo, not this file.\n"
    )
    if readme.is_file() and not readme.read_text(encoding="utf-8-sig").startswith(f"PROJECT: {project_id}\n"):
        raise ValueError(f"artifact project index identity differs from {project_id}")
    if not readme.is_file():
        readme.write_text(expected, encoding="utf-8")
    return project_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-projects-root", required=True, type=Path)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args()
    path = ensure_artifact_project(args.artifact_projects_root.resolve(), args.project_id)
    print(f"ARTIFACT_PROJECT=PASS PROJECT={args.project_id} PATH={path}")


if __name__ == "__main__":
    main()

"""Explicit OA-TOF science-data paths for installed candidate workflows."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ID = "single_reflection_oa_tof_mass_analyzer"


@dataclass(frozen=True)
class CandidateSciencePaths:
    """Resolve named science inputs beneath one explicit, existing data root."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve(strict=True))
        if not self.root.is_dir():
            raise ValueError(f"Candidate science root is not a directory: {self.root}")

    @property
    def project_root(self) -> Path:
        return self.root / "projects" / PROJECT_ID

    @property
    def config_root(self) -> Path:
        return self.project_root / "config"

    def config(self, name: str) -> Path:
        return self.config_root / name

    @property
    def registry(self) -> Path:
        return self.root / "config/project_registry.json"

    @property
    def baseline(self) -> Path:
        return self.config("baseline.json")

    @property
    def resolved(self) -> Path:
        return self.config("resolved_geometry.json")

    @property
    def numerics(self) -> Path:
        return self.config("formal_solver_numerics.json")

    @property
    def mode(self) -> Path:
        return self.config("modes/formal.json")

    @property
    def runtime(self) -> Path:
        return self.config("candidate_runtime.json")

    @property
    def workflow(self) -> Path:
        return self.config("candidate_workflow.json")

    @property
    def analysis(self) -> Path:
        return self.config("analysis_contract.json")

    @property
    def catalog(self) -> Path:
        return self.config("design_variables.json")

    @property
    def envelope(self) -> Path:
        return self.config("optimization_envelope.json")

    @property
    def consumers(self) -> Path:
        return self.config("candidate_consumers.json")

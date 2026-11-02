"""Small isolated source/policy fixture for real RF owner admission tests."""
from __future__ import annotations

import json
import math
import shutil
import tempfile
from pathlib import Path

from common.contracts.frozen_inputs import enumerate_python_sources


def capacity_fixture_source(repository: Path, destination: Path) -> Path:
    """Copy existing code/config once, with test-only bounded disk watermarks.

    The real SQLite ledger, capacity admission and original failure propagation
    remain active. No source solver payload or production policy is modified.
    """
    if destination.exists():
        return destination
    for relative in ("common", "config", "projects/rf_multipole_ion_optics"):
        shutil.copytree(repository / relative, destination / relative,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.mph", "*.pa0", "*.pa#"))
    for relative in enumerate_python_sources(
        repository, package_roots=("src/msplatform",), provider_root="src/msplatform",
        resource_suffixes=(".schema.json",),
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / relative, target)
    registry = json.loads((repository / "config/project_registry.json").read_text(encoding="utf-8"))
    project = next(row for row in registry["projects"] if row["project_id"] == "rf_multipole_ion_optics")
    for record in project["retired_project_descriptors"]:
        target = destination / record["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / record["path"], target)
    policy = destination / "common/contracts/artifact_capacity_policy.json"
    document = json.loads(policy.read_text(encoding="utf-8"))
    document.update(target_gib=.125, minimum_free_gib=0)
    policy.write_text(json.dumps(document), encoding="utf-8")
    return destination


def install_controlled_cpu_snapshot(repository: Path, fixture: Path, *, cpu_percent: float = 0.0) -> None:
    """Control only CPU input in an isolated software fixture, never a solver run."""
    if (isinstance(cpu_percent, bool) or not isinstance(cpu_percent, (int, float))
            or not 0 <= cpu_percent <= 100 or not math.isfinite(cpu_percent)):
        raise ValueError("Fixture CPU must be a finite number in [0, 100], not bool")
    repository, fixture = repository.resolve(), fixture.resolve()
    if (fixture == repository or fixture.is_relative_to(repository)
            or not fixture.is_relative_to(Path(tempfile.gettempdir()).resolve())):
        raise ValueError("Controlled CPU snapshot requires a repository-external fixture copy")
    target = fixture / "common/host_execution_lease.ps1"
    if not target.resolve().is_relative_to(fixture):
        raise ValueError("Controlled CPU snapshot cannot follow a link outside its fixture")
    original = (repository / "common/host_execution_lease.ps1").read_bytes()
    contents = target.read_bytes()
    marker = b"    cpu_percent = $load\n"
    if contents != original or contents.count(marker) != 1:
        raise ValueError("Controlled CPU snapshot requires the exact unmodified copied entrypoint")
    # Preserve invalid/missing real CPU observations so admission still rejects
    # them. All other fields and the complete real collection path stay intact.
    replacement = b"""    cpu_percent = $(
      if($null-eq$load-or-not[double]::IsFinite([double]$load)-or[double]$load-lt0-or[double]$load-gt100){
        Write-Host 'RF_SOFTWARE_FIXTURE_CPU INVALID_REAL_OBSERVATION_PRESERVED'
        $load
      }else{
        Write-Host ("RF_SOFTWARE_FIXTURE_CPU CONTROLLED={0} OBSERVED={1}"-f$script:RFSoftwareFixtureCpuPercent,$load)
        [double]$script:RFSoftwareFixtureCpuPercent
      }
    )
"""
    target.write_bytes(b"# TEST ONLY: controlled CPU input; no native solver authorization.\n"
                       + f"$script:RFSoftwareFixtureCpuPercent={float(cpu_percent)!r}\n".encode("ascii")
                       + contents.replace(marker, replacement))

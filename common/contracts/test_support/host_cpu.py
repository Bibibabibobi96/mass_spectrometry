"""Control CPU input only in verified temporary software-test source copies."""
from __future__ import annotations

import math
from pathlib import Path
import tempfile


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
        Write-Host 'SOFTWARE_FIXTURE_CPU INVALID_REAL_OBSERVATION_PRESERVED'
        $load
      }else{
        Write-Host ("SOFTWARE_FIXTURE_CPU CONTROLLED={0} OBSERVED={1}"-f$script:SoftwareFixtureCpuPercent,$load)
        [double]$script:SoftwareFixtureCpuPercent
      }
    )
"""
    target.write_bytes(b"# TEST ONLY: controlled CPU input; no native solver authorization.\n"
                       + f"$script:SoftwareFixtureCpuPercent={float(cpu_percent)!r}\n".encode("ascii")
                       + contents.replace(marker, replacement))

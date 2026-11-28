"""Generate self-contained SIMION text inputs from ``baseline.json``.

MATLAB and PowerShell can read JSON directly. SIMION Workbench files must
remain portable, so their GUI-visible numeric declarations are generated from
the same contract and committed. ``--check`` is the stale-file gate and
``--write`` is called by the formal delivery builder.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from typing import Iterator

from msplatform.backends.simion import oatof_inputs
from msplatform.io.file_identity import file_sha256
from msplatform.workflows.oa_candidate.geometry_contract import resolve_contract, serialized


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = REPO_ROOT / "components/single_reflection_oa_tof"
RESOLVED_PATH = PROJECT_ROOT / "config/resolved_geometry.json"
CONTRACT_PATH = PROJECT_ROOT / "config" / "baseline.json"
RESOLVED_LUA_PATH = REPO_ROOT / "backends/simion/resources/oatof_resolved.lua"
PROGRAM_PATH = REPO_ROOT / "backends/simion/resources/oatof_ideal_grounded.lua"
FLY2_PATH = REPO_ROOT / "backends/simion/resources/oatof_ideal_grounded.fly2"
NUMERICS_PATH = PROJECT_ROOT / "config" / "formal_solver_numerics.json"
OPTIMIZATION_ENVELOPE_PATH = PROJECT_ROOT / "config" / "optimization_envelope.json"
AUTHORITY_DOCUMENTS = (
    PROJECT_ROOT / "config" / "experiment_campaign.json",
    PROJECT_ROOT / "config" / "radial_compaction_campaign.json",
)


@contextmanager
def package_repository_view(source_ids: tuple[str, ...]) -> Iterator[Path]:
    """Expose explicit package files through the existing repository-root APIs."""
    with tempfile.TemporaryDirectory(prefix="oatof-package-sources-") as directory:
        root = Path(directory)
        for source_id in source_ids:
            relative = Path(source_id)
            if relative.is_absolute() or relative.parts[:2] != ("src", "msplatform"):
                raise ValueError(f"invalid package source id: {source_id}")
            source = REPO_ROOT.joinpath(*relative.parts[2:])
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        yield root


def load_contract(contract_path: Path | None = None) -> dict:
    if contract_path is None:
        return oatof_inputs.validate_resolved_contract(resolve_contract())
    return oatof_inputs.validate_resolved_contract(json.loads(contract_path.read_text(encoding="utf-8")))


def render_program(contract: dict) -> str:
    return oatof_inputs.render_program(contract, PROGRAM_PATH.read_text(encoding="utf-8"))


def _replace_unique_sha(
    source: str,
    key: str,
    old_sha: str,
    new_sha: str,
    label: str,
    path: Path,
) -> str:
    marker = f'"{key}": "{old_sha}"'
    if source.count(marker) != 1:
        raise ValueError(f"{label} SHA marker is not unique in {path}")
    return source.replace(marker, f'"{key}": "{new_sha}"', 1)


def render_optimization_envelope() -> str:
    source = OPTIMIZATION_ENVELOPE_PATH.read_text(encoding="utf-8")
    document = json.loads(source)
    reference = document["reference"]
    if reference.get("baseline") != "config/baseline.json":
        raise ValueError("unexpected baseline reference in optimization envelope")
    baseline_sha = file_sha256(CONTRACT_PATH)
    return _replace_unique_sha(
        source,
        "baseline_sha256",
        reference["baseline_sha256"],
        baseline_sha,
        "baseline reference",
        OPTIMIZATION_ENVELOPE_PATH,
    )


def render_authority_document(path: Path, optimization_envelope: str) -> str:
    source = path.read_text(encoding="utf-8")
    document = json.loads(source)
    if document.get("status") == "retired":
        execution = document.get("execution_profile")
        if execution is not None and execution["authority"].get("path") != "config/execution_profiles.json":
            raise ValueError(f"unexpected execution profile authority path in {path}")
        return source
    bindings = {
        "baseline": ("config/baseline.json", CONTRACT_PATH.read_bytes()),
        "solver_numerics": (
            "config/formal_solver_numerics.json",
            NUMERICS_PATH.read_bytes(),
        ),
        "optimization_envelope": (
            "config/optimization_envelope.json",
            optimization_envelope.encode("utf-8"),
        ),
        "candidate_runtime": (
            "config/candidate_runtime.json",
            (PROJECT_ROOT / "config" / "candidate_runtime.json").read_bytes(),
        ),
    }
    for label, (expected_path, content) in bindings.items():
        authority = document["authorities"].get(label)
        if authority is None:
            continue
        if authority.get("path") != expected_path:
            raise ValueError(f"unexpected {label} authority path in {path}")
        source = _replace_unique_sha(
            source,
            "sha256",
            authority["sha256"],
            hashlib.sha256(content).hexdigest().upper(),
            f"{label} authority",
            path,
        )
    execution = document.get("execution_profile")
    if execution is not None:
        authority = execution["authority"]
        expected_path = "config/execution_profiles.json"
        if authority.get("path") != expected_path:
            raise ValueError(f"unexpected execution profile authority path in {path}")
        source = _replace_unique_sha(
            source, "sha256", authority["sha256"],
            file_sha256(PROJECT_ROOT / expected_path).upper(),
            "execution profile authority", path,
        )
    return source


def frozen_fly2_seed(path: Path = FLY2_PATH) -> int:
    """Read the one run-instance seed already frozen in a generated Fly2 source."""

    matches = re.findall(r"(?m)^seed\((-?\d+)\)\s*$", path.read_text(encoding="utf-8"))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frozen integer seed in {path}")
    return int(matches[0])


def update(path: Path, expected: str, write: bool) -> bool:
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    if current == expected:
        return False
    if write:
        path.write_text(expected, encoding="utf-8", newline="\n")
        return True
    display = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path.relative_to(path.parent.parent)
    raise SystemExit(f"STALE={display}")


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    contract = load_contract()
    source_seed = frozen_fly2_seed()
    optimization_envelope = render_optimization_envelope()
    changed = [
        path
        for path, content in (
            (RESOLVED_PATH, serialized(contract)),
            (RESOLVED_LUA_PATH, oatof_inputs.render_resolved_lua(contract)),
            (PROGRAM_PATH, render_program(contract)),
            (FLY2_PATH, oatof_inputs.render_fly2(contract, particle_source_seed=source_seed)),
            (OPTIMIZATION_ENVELOPE_PATH, optimization_envelope),
            *(
                (path, render_authority_document(path, optimization_envelope))
                for path in AUTHORITY_DOCUMENTS
            ),
        )
        if update(path, content, args.write)
    ]
    print("GEOMETRY_TEXT_SYNC=PASS")
    for path in changed:
        print(f"UPDATED={path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")


if __name__ == "__main__":
    main()

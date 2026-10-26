"""Compile current terminal-campaign and oaTOF port text bindings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from common.contracts.file_identity import repository_text_sha256

REPO_ROOT = Path(__file__).resolve().parents[2]
_PORT = "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json"
_TERMINAL_BINDING = re.compile(
    r'("downstream_terminal_profile"\s*:\s*\{.*?"registry_sha256"\s*:\s*")[A-F0-9]{64}("\s*)',
    re.DOTALL,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compile_publications(repo_root: Path) -> dict[Path, bytes]:
    """Return derived bindings without writing provider designs or history."""
    root = repo_root.resolve()
    discovery = _load(root / "integrations/registry.json")
    owners = [row for row in discovery["integrations"] if row["integration_id"] == "instrument_assembly"]
    if len(owners) != 1:
        raise ValueError("instrument assembly owner must be unique")
    catalog = (root / owners[0]["downstream_terminal_profile_registry"]).resolve()
    catalog.relative_to(root / "integrations/config")
    registry = _load(catalog)
    if registry["integration_id"] != "instrument_assembly":
        raise ValueError("terminal catalog owner differs")
    catalog_sha = repository_text_sha256(catalog)
    compiled = {}
    for path in sorted((root / "common/multipole/campaigns").glob("*.json")):
        document = _load(path)
        binding = document.get("downstream_terminal_profile")
        if binding is None:
            continue
        if binding["integration_id"] != "instrument_assembly":
            raise ValueError(f"terminal campaign owner differs: {path}")
        if not any(row["terminal_profile_id"] == binding["terminal_profile_id"] for row in registry["profiles"]):
            raise ValueError(f"terminal profile is missing: {path}")
        source = path.read_text(encoding="utf-8-sig")
        rendered, count = _TERMINAL_BINDING.subn(rf"\g<1>{catalog_sha}\g<2>", source, count=1)
        if count != 1:
            raise ValueError(f"terminal campaign binding must be unique: {path}")
        compiled[path] = rendered.encode("utf-8")

    port = root / _PORT
    document = _load(port)
    source = (root / document["authority"]["source_contract"]).resolve()
    source.relative_to(root)
    document["authority"]["source_sha256"] = repository_text_sha256(source)
    compiled[port] = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return compiled


def publication_differences(repo_root: Path) -> list[Path]:
    return [path for path, expected in compile_publications(repo_root).items() if path.read_bytes() != expected]


def write_publications(repo_root: Path) -> list[Path]:
    changed = []
    for path, expected in compile_publications(repo_root).items():
        if path.read_bytes() != expected:
            path.write_bytes(expected)
            changed.append(path)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        stale = publication_differences(args.repo_root)
        if stale:
            raise SystemExit("REPOSITORY_BINDINGS=STALE PATHS=" + ",".join(
                path.relative_to(args.repo_root.resolve()).as_posix() for path in stale))
        print("REPOSITORY_BINDINGS=PASS")
    else:
        print(f"REPOSITORY_BINDINGS=UPDATED FILES={len(write_publications(args.repo_root))}")


if __name__ == "__main__":
    main()

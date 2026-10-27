"""Compile the current oaTOF port text binding."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common.contracts.file_identity import repository_text_sha256

REPO_ROOT = Path(__file__).resolve().parents[2]
_PORT = "projects/single_reflection_oa_tof_mass_analyzer/config/interfaces/required/oatof_accelerator_entry.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compile_publications(repo_root: Path) -> dict[Path, bytes]:
    """Return derived bindings without writing provider designs or history."""
    root = repo_root.resolve()
    port = root / _PORT
    document = _load(port)
    source = (root / document["authority"]["source_contract"]).resolve()
    source.relative_to(root)
    document["authority"]["source_sha256"] = repository_text_sha256(source)
    return {port: (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")}


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

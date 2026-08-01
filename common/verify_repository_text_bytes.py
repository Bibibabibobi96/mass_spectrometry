"""Fail when a tracked file declared as LF contains carriage-return bytes."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _git(repo_root: Path, *arguments: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *arguments],
        cwd=repo_root,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed: {message}")
    return result.stdout


def lf_tracked_paths(repo_root: Path) -> list[Path]:
    """Return tracked paths whose effective Git attribute is ``eol=lf``."""
    names = [item for item in _git(repo_root, "ls-files", "-z").split(b"\0") if item]
    attributes = _git(
        repo_root,
        "check-attr",
        "-z",
        "--stdin",
        "eol",
        stdin=b"\0".join(names) + b"\0",
    ).split(b"\0")
    if attributes and attributes[-1] == b"":
        attributes.pop()
    if len(attributes) % 3:
        raise RuntimeError("git check-attr returned an incomplete record")
    return [
        Path(attributes[index].decode("utf-8", errors="surrogateescape"))
        for index in range(0, len(attributes), 3)
        if attributes[index + 1] == b"eol" and attributes[index + 2] == b"lf"
    ]


def carriage_return_paths(repo_root: Path) -> list[Path]:
    """Return LF-governed tracked files containing CR bytes in the worktree."""
    offenders: list[Path] = []
    for relative in lf_tracked_paths(repo_root):
        path = repo_root / relative
        if path.is_file() and b"\r" in path.read_bytes():
            offenders.append(relative)
    return offenders


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    offenders = carriage_return_paths(repo_root)
    if offenders:
        rendered = "\n".join(path.as_posix() for path in offenders)
        raise SystemExit(
            "REPOSITORY_TEXT_BYTES=FAIL REASON=tracked_eol_lf_contains_cr\n"
            + rendered
        )
    print(f"REPOSITORY_TEXT_BYTES=PASS FILES={len(lf_tracked_paths(repo_root))}")


if __name__ == "__main__":
    main()

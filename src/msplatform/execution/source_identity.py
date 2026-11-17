"""Bounded source-control identity for execution receipts."""
from pathlib import Path
import subprocess


def git_identity(repo_root: Path | None) -> dict:
    if repo_root is None:
        return {"commit": None, "working_tree": "unknown"}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo_root, check=True,
            capture_output=True, text=True, timeout=5,
        ).stdout
        return {"commit": commit, "working_tree": "dirty" if dirty else "clean"}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return {"commit": None, "working_tree": "unknown"}

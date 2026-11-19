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


def git_worktree_context(repo_root: Path) -> dict:
    """Capture the existing IP provenance fields through the execution boundary."""
    context = {}
    for key, arguments in (("git_sha", ["rev-parse", "HEAD"]), ("worktree_porcelain", ["status", "--porcelain"])):
        result = subprocess.run(["git", "-C", str(repo_root), *arguments], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", check=False,
                                cwd=repo_root, timeout=10)
        context[key] = result.stdout.strip() if result.returncode == 0 else "unavailable"
    context["worktree_dirty"] = bool(context["worktree_porcelain"])
    return context


def git_show(repo_root: Path, revision: str, path: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "show", f"{revision}:{path}"], cwd=repo_root,
            check=True, capture_output=True, timeout=30,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise OSError(f"cannot read source identity {revision}:{path}") from error

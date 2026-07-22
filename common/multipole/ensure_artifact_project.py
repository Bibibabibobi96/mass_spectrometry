"""Compatibility entry for the root-level artifact project helper."""

from common.contracts.artifact_project import ensure_artifact_project, main

__all__ = ["ensure_artifact_project", "main"]


if __name__ == "__main__":
    main()

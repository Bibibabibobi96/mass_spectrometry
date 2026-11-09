"""Read published scientific products without recreating their execution environment."""

from .artifacts import OpenedArtifact, open_artifact

__all__ = ["OpenedArtifact", "open_artifact"]

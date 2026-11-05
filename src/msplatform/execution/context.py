"""Explicit local execution configuration, without scientific or run state."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, kw_only=True)
class ExecutionContext:
    """Configured paths and tools; construction neither probes nor creates them.

    The host state path names the existing shared admission database. It does
    not create another scheduler. Policy names the explicit installed resource
    or caller-selected policy; construction does not read or resolve it.
    """

    workspace: Path
    python_executable: Path
    powershell_executable: Path
    tools: Mapping[str, Path]
    host_state_path: Path
    policy_path: Path
    execution_root: Path | None = None
    stage_policy_path: Path | None = None

    def __post_init__(self) -> None:
        for name in ("workspace", "python_executable", "powershell_executable",
                     "host_state_path", "policy_path"):
            value = Path(getattr(self, name))
            if not value.is_absolute():
                raise ValueError(f"execution context {name} must be absolute")
            object.__setattr__(self, name, value)
        execution_root = self.workspace / "artifacts" / "common" / "execution_aliases" if self.execution_root is None else Path(self.execution_root)
        if not execution_root.is_absolute():
            raise ValueError("execution context execution_root must be absolute")
        object.__setattr__(self, "execution_root", execution_root)
        if self.stage_policy_path is not None:
            stage_policy_path = Path(self.stage_policy_path)
            if not stage_policy_path.is_absolute():
                raise ValueError("execution context stage_policy_path must be absolute")
            object.__setattr__(self, "stage_policy_path", stage_policy_path)
        tools = dict(self.tools)
        for name, path in tools.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("execution tool names must be nonempty strings")
            path = Path(path)
            if not path.is_absolute():
                raise ValueError(f"execution tool {name} must have an absolute path")
            tools[name] = path
        object.__setattr__(self, "tools", MappingProxyType(tools))

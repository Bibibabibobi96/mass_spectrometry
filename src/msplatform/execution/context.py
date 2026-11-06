"""Explicit local execution configuration, without scientific or run state."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from msplatform.contracts.machine_contracts import ContractError
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


def load_environment(*, workspace: str | Path, tools: Mapping[str, str | Path],
                     policy: Mapping[str, str | Path]) -> ExecutionContext:
    """Load one explicit machine environment without probing or creating paths."""
    if not isinstance(tools, Mapping) or not {"python", "powershell"} <= tools.keys():
        raise ContractError("execution tools must explicitly declare python and powershell")
    required_policy = {"host_state_path"}
    if (not isinstance(policy, Mapping) or not required_policy <= policy.keys()
            or set(policy) - required_policy - {"policy_path", "execution_root", "stage_policy_path"}):
        raise ContractError("execution policy requires host_state_path; policy_path, execution_root and stage_policy_path are optional")
    from msplatform.execution.resources import resource_path
    policy_path = Path(policy["policy_path"]) if "policy_path" in policy else resource_path("host_resource_policy.json")
    return ExecutionContext(workspace=Path(workspace).absolute(), python_executable=Path(tools["python"]),
        powershell_executable=Path(tools["powershell"]), tools={key: Path(value) for key, value in tools.items()},
        host_state_path=Path(policy["host_state_path"]), policy_path=policy_path,
        execution_root=Path(policy["execution_root"]) if "execution_root" in policy else None,
        stage_policy_path=Path(policy["stage_policy_path"]) if "stage_policy_path" in policy else None)

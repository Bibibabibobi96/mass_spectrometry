"""Explicit local execution configuration, without scientific or run state."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import json
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
    capacity_policy_path: Path | None = None
    stage_policy_path: Path | None = None
    _environment_json: str | None = None

    @property
    def environment(self) -> dict | None:
        """Independent snapshot of the selected engineering deployment."""
        return json.loads(self._environment_json) if self._environment_json is not None else None

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
        if self.capacity_policy_path is not None:
            capacity_policy_path = Path(self.capacity_policy_path)
            if not capacity_policy_path.is_absolute():
                raise ValueError("execution context capacity_policy_path must be absolute")
            object.__setattr__(self, "capacity_policy_path", capacity_policy_path)
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


def load_environment(configuration: str | Path | Mapping, *, workspace: str | Path,
                     profile: str, overrides: Mapping | None = None) -> ExecutionContext:
    """Select a saved machine deployment and engineering profile without writes.

    File-relative references are anchored to that file. Mapping references must
    be absolute. Overrides affect stage engineering policy only, never science,
    tools or the shared host ledger.
    """
    from msplatform.io.manifest_records import file_record, verify_record
    source = None
    base = None
    if isinstance(configuration, Mapping):
        document = copy.deepcopy(dict(configuration))
    else:
        path = Path(configuration).absolute()
        source = file_record(path, "required_evidence")
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        verify_record("execution environment", source)
        base = path.parent
    if (not isinstance(document, dict) or set(document) != {"schema_version", "role", "tools", "policy", "profiles"}
            or type(document["schema_version"]) is not int or document["schema_version"] != 1
            or document["role"] != "execution_environment"):
        raise ContractError("Unsupported execution environment")
    tools, policy, profiles = document["tools"], document["policy"], document["profiles"]
    if not isinstance(tools, Mapping) or not {"python", "powershell"} <= tools.keys():
        raise ContractError("execution tools must explicitly declare python and powershell")
    required_policy = {"host_state_path"}
    if (not isinstance(policy, Mapping) or not required_policy <= policy.keys()
            or set(policy) - required_policy - {"policy_path", "execution_root", "capacity_policy_path"}):
        raise ContractError("execution policy requires host_state_path; policy_path, execution_root and capacity_policy_path are optional")
    if not isinstance(profiles, Mapping) or not isinstance(profile, str) or profile not in profiles:
        raise ContractError("Select an explicitly named engineering profile")
    selected = profiles[profile]
    if (not isinstance(selected, Mapping) or "stage_policy_path" not in selected
            or set(selected) - {"stage_policy_path", "overrides"}):
        raise ContractError("Engineering profile requires stage_policy_path and optional overrides")
    def reference(value):
        path = Path(value)
        if not path.is_absolute():
            if base is None:
                raise ContractError("Mapping execution references must be absolute")
            path = base / path
        return path.absolute()
    from msplatform.execution.resources import resource_path
    resolved_tools = {key: reference(value) for key, value in tools.items()}
    resolved_policy = {key: reference(value) for key, value in policy.items()}
    stage_path = reference(selected["stage_policy_path"])
    from .stage_policy import merge_overrides
    merged = merge_overrides(selected.get("overrides", {}), {} if overrides is None else overrides)
    environment = dict(profile=profile, overrides=merged, source=source,
        tools={key: str(value) for key, value in resolved_tools.items()},
        policy={key: str(value) for key, value in resolved_policy.items()}, stage_policy_path=str(stage_path))
    return ExecutionContext(workspace=Path(workspace).absolute(), python_executable=resolved_tools["python"],
        powershell_executable=resolved_tools["powershell"], tools=resolved_tools,
        host_state_path=resolved_policy["host_state_path"],
        policy_path=resolved_policy.get("policy_path", resource_path("host_resource_policy.json")),
        execution_root=resolved_policy.get("execution_root"), capacity_policy_path=resolved_policy.get("capacity_policy_path"), stage_policy_path=stage_path,
        _environment_json=json.dumps(environment))

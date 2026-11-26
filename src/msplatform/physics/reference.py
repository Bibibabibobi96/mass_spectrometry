"""Versioned data for the installed reference tracing workflow."""

from dataclasses import dataclass
from importlib.resources import files
import json
from types import MappingProxyType


def _load_data() -> dict:
    data = json.loads(files("msplatform.physics").joinpath("data/reference.json").read_text(encoding="utf-8"))
    if data["schema_version"] != 1 or data["dataset_id"] != "repository_reference_physics_v1":
        raise ValueError("unsupported reference physics dataset")
    return data


_DATA = _load_data()
_CONSTANT_VALUES = _DATA["constants"]
CONSTANTS = MappingProxyType({
    "version": _CONSTANT_VALUES["version"],
    "atomic_mass_constant_kg": float(_CONSTANT_VALUES["atomic_mass_constant_kg"]),
    "elementary_charge_c": float(_CONSTANT_VALUES["elementary_charge_c"]),
    "boltzmann_constant_j_k": float(_CONSTANT_VALUES["boltzmann_constant_j_k"]),
})


@dataclass(frozen=True)
class GasEnvironment:
    """Explicit vacuum for the collision-free reference workflow."""

    status: str

    def __post_init__(self) -> None:
        if self.status != "vacuum":
            raise ValueError("reference tracer supports explicit vacuum only")

    def to_dict(self) -> dict:
        return {"status": _DATA["gas"]["vacuum"]["status"],
                "pressure_pa": _DATA["gas"]["vacuum"]["pressure_pa"],
                "collision_model": _DATA["collision_models"]["none"]["model"],
                "data_version": _DATA["dataset_id"], "collision_model_ref": "none"}

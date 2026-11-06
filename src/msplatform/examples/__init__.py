"""Versioned, self-contained scientific examples distributed with the product."""
from importlib.resources import files
import json


def load_example_document(name: str) -> dict:
    """Read one named example document without checkout or native side effects."""
    if name != "rf_oatof_functional_v1":
        raise ValueError(f"unknown example: {name}")
    return json.loads(files(__package__).joinpath(name + ".json").read_text(encoding="utf-8"))


from .study import StudyDefinition as StudyDefinition, load_example as load_example

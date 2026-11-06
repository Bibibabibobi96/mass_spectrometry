"""Inspectable study objects over self-contained versioned package examples."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from msplatform.contracts.machine_contracts import ContractError
from . import load_example_document


@dataclass(frozen=True, init=False)
class StudyDefinition:
    """Inspectable versioned scientific input; each view returns an independent copy."""

    _document: dict[str, Any]

    def __init__(self, document: Mapping[str, Any]):
        object.__setattr__(self, "_document", copy.deepcopy(dict(document)))

    @property
    def document(self) -> dict[str, Any]:
        return copy.deepcopy(self._document)

    @property
    def component_requests(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["component_requests"])

    @property
    def recipe(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["recipe"])

    @property
    def geometry_numerics(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["numerics"]["geometry"])

    @property
    def field_numerics(self) -> dict[str, Any]:
        """Expand field stopping settings over the example's single geometry grid."""
        settings = copy.deepcopy(self._document["numerics"]["fields"])
        convergence = settings.pop("frontend_refine_convergence_v")
        domains = self.geometry_numerics["frontend_domains"]
        if set(convergence) != set(domains):
            raise ContractError("example field convergence must cover its exact geometry domains")
        for name, domain in domains.items():
            domain["refine_convergence_v"] = convergence[name]
        return dict(frontend_domains=domains, **settings)

    @property
    def cad_export(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["cad_export"])

    @property
    def drive(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["drive"])

    @property
    def physics(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["physics"])

    @property
    def release(self) -> dict[str, Any]:
        return copy.deepcopy(self._document["release"])

    def to_dict(self) -> dict[str, Any]:
        """Expand the complete example without changing its authoritative inputs."""
        return copy.deepcopy(self._document)


def load_example(example_id: str) -> StudyDefinition:
    """Read an expanded package-owned example; no native or workspace actions."""
    document = load_example_document(example_id)
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise ContractError("unsupported study example version")
    if document.get("name") != example_id:
        raise ContractError("example identity differs from the requested example")
    return StudyDefinition(document)

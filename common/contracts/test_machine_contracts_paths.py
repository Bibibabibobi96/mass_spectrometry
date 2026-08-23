"""Tests for explicitly owned JSON Schema validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from common.contracts.machine_contracts import ContractError, validate_schema


class MachineContractPathTests(unittest.TestCase):
    def test_validates_explicit_schema_path_with_shared_references(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owned.schema.json"
            path.write_text(json.dumps({
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "https://mass-spectrometry.local/test/owned.schema.json",
                "type": "object",
                "required": ["selection"],
                "properties": {
                    "selection": {
                        "$ref": "https://mass-spectrometry.local/schemas/"
                        "resolved_connection.schema.json#/properties/selection"
                    }
                },
            }), encoding="utf-8")
            validate_schema({"selection": {
                "upstream_project_id": "a",
                "upstream_port_id": "b",
                "downstream_project_id": "c",
                "downstream_port_id": "d",
                "connection_profile_id": "e",
            }}, path)
            with self.assertRaises(ContractError):
                validate_schema({}, path)


if __name__ == "__main__":
    unittest.main()

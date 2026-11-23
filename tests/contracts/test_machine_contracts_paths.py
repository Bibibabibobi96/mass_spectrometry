"""Tests for explicitly owned JSON Schema validation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from msplatform.contracts.machine_contracts import ContractError, schema_registry, validate_schema


class MachineContractPathTests(unittest.TestCase):
    def test_missing_schema_engine_does_not_bypass_validation(self) -> None:
        source_root = Path(__file__).resolve().parents[2] / "src"
        probe = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from msplatform.contracts.machine_contracts import ContractError, load_json, validate_schema; "
            "assert issubclass(ContractError, ValueError); "
            "validate_schema({}, 'project.schema.json')"
        )
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", probe, str(source_root)],
                cwd=directory, capture_output=True, text=True, encoding="utf-8", timeout=15,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ModuleNotFoundError: No module named 'jsonschema'", result.stderr)

    def test_shared_schema_metadata_is_valid(self) -> None:
        # The production loader checks every schema before registering it.
        # Dedicated schema changes need this metacheck and their consumers,
        # rather than the unrelated lifecycle/process fault matrix.
        self.assertIsNotNone(schema_registry())

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

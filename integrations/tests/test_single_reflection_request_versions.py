"""Explicit legacy/current request schemas and their real frozen resources."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from integrations.tests.test_single_reflection_preparation import fixture
from integrations.workflows.single_reflection_flight.prepare import (
    SCHEMA, SCHEMA_V10, validate_preparation_request,
)

ROOT = Path(__file__).resolve().parents[2]


class SingleReflectionRequestVersionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="request versions ")
        cls.addClassCleanup(cls.directory.cleanup)
        _, _, cls.legacy = fixture(Path(cls.directory.name))

    def current(self):
        request = copy.deepcopy(self.legacy)
        request["schema_version"] = 10
        request["providers"]["instances"]["multipole"]["electrode_bindings"] = {
            "rod_group_1": 17, "rod_group_2": 23,
        }
        request["providers"]["instances"]["oatof"]["electrode_bindings"] = {
            "grounded_shield": 31, "repeller": 47, "intermediate_grid_1": 53,
            "intermediate_grid_2": 59, "exit_grid": 61, "ring_0001": 67,
        }
        return request

    def test_declared_versions_preserve_inputs_and_old_schema_bytes(self):
        for request, version in ((self.legacy, 9), (self.current(), 10)):
            before = copy.deepcopy(request)
            self.assertEqual(validate_preparation_request(request), version)
            self.assertEqual(validate_preparation_request(json.loads(json.dumps(request))), version)
            self.assertEqual(request, before)
        self.assertNotEqual(json.loads(SCHEMA.read_text())["$id"], json.loads(SCHEMA_V10.read_text())["$id"])
        # Legacy9 accepts its existing two-zone declaration; current native10
        # does not claim a two-zone field/drive implementation.
        two_zone = copy.deepcopy(self.legacy)
        two_zone["providers"]["instances"]["oatof"]["geometry"]["accelerator_variant"] = "two_zone_square"
        self.assertEqual(validate_preparation_request(two_zone), 9)
        with self.assertRaises(ValueError):
            validate_preparation_request(dict(self.current(), schema_version=9, unknown_alias=True))

    def test_version_ten_rejects_native_alias_keys_and_noninteger_targets(self):
        for key in ("1", "scientific_id", "component_electrode_id", "electrical_group_id",
                    "accelerator_grid1_id", "accelerator_grid2_id", "grounded_shield_id"):
            request = self.current()
            request["providers"]["instances"]["multipole"]["electrode_bindings"][key] = 71
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_preparation_request(request)
        for target in (True, False, 0, -1, 1001, 1.0, 1.25, "17", None, {"native_electrode_id": 17}):
            request = self.current()
            request["providers"]["instances"]["multipole"]["electrode_bindings"]["rod_group_1"] = target
            with self.subTest(target=target), self.assertRaises(ValueError):
                validate_preparation_request(request)
        for target in (1, 1000):
            request = self.current()
            request["providers"]["instances"]["multipole"]["electrode_bindings"]["rod_group_1"] = target
            self.assertEqual(validate_preparation_request(request), 10)

    def test_dispatch_rejects_unknown_versions_and_current_invalid_structure(self):
        for version in (True, False, 9.0, 10.0, None, "10", 8, 11):
            with self.subTest(version=version), self.assertRaises(ValueError):
                validate_preparation_request(dict(self.current(), schema_version=version))
        for mutation in ("empty_map", "old_provider_alias", "two_zone", "missing_numerics"):
            request = self.current()
            provider = request["providers"]["instances"]["oatof"]
            if mutation == "empty_map":
                provider["electrode_bindings"] = {}
            elif mutation == "old_provider_alias":
                provider["scientific_id"] = "repeller"
            elif mutation == "two_zone":
                provider["geometry"]["accelerator_variant"] = "two_zone_square"
            else:
                del request["numerics"]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_preparation_request(request)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is unavailable")
    def test_actual_freezer_carries_both_independent_request_schema_resources(self):
        with tempfile.TemporaryDirectory(prefix="request schema 冻结 ") as directory:
            output = Path(directory) / "inputs"
            script = """
param($Python,$Repo,$Output)
. (Join-Path $Repo 'integrations/runtime/dependencies.ps1')
$null=Freeze-ConsumerDependencies -Python $Python -RepoRoot $Repo `
 -ContractPath (Join-Path $Repo 'integrations/config/runtime_dependencies.json') `
 -InputDir $Output -OwnerId instrument_assembly -ConsumerId single_reflection_flight
"""
            entry = Path(directory) / "freeze.ps1"
            entry.write_text(script, encoding="utf-8")
            process = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(entry),
                                      sys.executable, str(ROOT), str(output)], cwd=directory,
                                     capture_output=True, text=True, encoding="utf-8", timeout=120)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            inventory = json.loads((output / "code_inventory.json").read_text(encoding="utf-8-sig"))["dependencies"]
            for schema in (SCHEMA, SCHEMA_V10):
                relative = schema.relative_to(ROOT).as_posix()
                rows = [row for row in inventory if row["source_repo_path"] == relative]
                self.assertEqual(len(rows), 1, relative)
                frozen = output / rows[0]["frozen_filename"]
                self.assertEqual(frozen.read_bytes(), schema.read_bytes())
                self.assertEqual(json.loads(frozen.read_text())["properties"]["schema_version"]["const"],
                                 9 if schema == SCHEMA else 10)


if __name__ == "__main__":
    unittest.main()

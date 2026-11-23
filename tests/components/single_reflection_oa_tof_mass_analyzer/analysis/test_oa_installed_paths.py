from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from msplatform.workflows.oa_candidate import sync_geometry_contract


class OaInstalledPathTests(unittest.TestCase):
    def test_modules_and_resources_use_the_installed_package_without_checkout_fallback(self) -> None:
        package_root = Path(sync_geometry_contract.__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install_root = root / "site-packages"
            installed_package = install_root / "msplatform"
            shutil.copytree(package_root, installed_package)
            outside = root / "outside"
            outside.mkdir()
            probe = r'''
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

install_root = Path(sys.argv[1])
sys.path.insert(0, str(install_root))
from msplatform.workflows.oa_candidate import candidate_run_lifecycle as lifecycle
from msplatform.workflows.oa_candidate import radial_compaction as radial
from msplatform.workflows.oa_candidate import reference_analysis_core as reference
from msplatform.workflows.oa_candidate import run_compensation as compensation
from msplatform.workflows.oa_candidate import sync_geometry_contract as sync

modules = (lifecycle, radial, reference, compensation, sync)
for module in modules:
    assert Path(module.__file__).resolve().is_relative_to(install_root)
    assert module.REPO_ROOT == install_root / "msplatform"
assert sync.load_contract()["role"] == "oa_tof_resolved_contract_do_not_edit"
assert reference.load_contract()[0]["schema_version"] == 3
assert lifecycle.FORMAL_BASELINE_PATH.is_file()
assert compensation.PROGRAM_PATH.is_file()
assert (compensation.REPO_ROOT / compensation.AXIS_EXPORTER_SOURCE.removeprefix("src/msplatform/")).is_file()
assert radial.CONFIG_PATH.is_file()
assert radial.PYTHON == Path(sys.executable).resolve()

run_id = "20261123_120000__test__python__installed-paths"
request = {"package": {"run_id": run_id}, "payload": {"pa_handoff_output": None}}
def owner(command, **kwargs):
    assert Path(command[command.index("-File") + 1]) == (
        install_root / "msplatform/workflows/resources/run_artifact_workflow.ps1"
    )
    result_path = Path(command[command.index("-ResultPath") + 1])
    result_path.write_text("{}", encoding="utf-8")
    return subprocess.CompletedProcess(command, 0), None
with patch.object(radial, "run_observed_process", side_effect=owner):
    radial._invoke_workflow_owner(request)

sync.CONTRACT_PATH.unlink()
try:
    sync.load_contract()
except FileNotFoundError as error:
    assert Path(error.filename) == sync.CONTRACT_PATH
else:
    raise AssertionError("missing installed baseline fell back to another source")
print(json.dumps({"modules": len(modules), "installed_root": str(install_root)}))
'''
            completed = subprocess.run(
                [sys.executable, "-I", "-B", "-c", probe, str(install_root)],
                cwd=outside,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["modules"], 5)


if __name__ == "__main__":
    unittest.main()

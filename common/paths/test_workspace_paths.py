"""One canonical root selection and bounded execution-view projection."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from common.paths.workspace_paths import project_native_run_path, project_run_path, resolve_workspace_paths

PWSH = shutil.which("pwsh")


class WorkspacePathsTests(unittest.TestCase):
    def test_default_and_payload_override_keep_the_host_identity(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            root = Path(temporary)
            source = root / "checkout"
            source.mkdir()
            default = resolve_workspace_paths(source)
            self.assertEqual(default["artifact_root"], str(root / "artifacts"))
            self.assertEqual(default["execution_root"], str(root / "artifacts/common/execution_aliases"))
            overridden = resolve_workspace_paths(source, artifact_root=root / "short")
            self.assertEqual(overridden["execution_root"], str(root / "short/common/execution_aliases"))
            self.assertEqual(default["host_resource_state_path"], overridden["host_resource_state_path"])

    def test_explicit_environment_and_frozen_precedence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "checkout").mkdir()
            settings = {"MASS_SPECTROMETRY_ARTIFACT_ROOT": str(root / "payload"),
                        "MASS_SPECTROMETRY_EXECUTION_ROOT": str(root / "exec"),
                        "MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH": str(root / "host.sqlite3")}
            with patch.dict(os.environ, settings):
                selected = resolve_workspace_paths(root / "checkout")
                self.assertEqual(selected["artifact_root"], settings["MASS_SPECTROMETRY_ARTIFACT_ROOT"])
                self.assertEqual(selected["execution_root"], settings["MASS_SPECTROMETRY_EXECUTION_ROOT"])
                self.assertEqual(selected["host_resource_state_path"], settings["MASS_SPECTROMETRY_HOST_RESOURCE_STATE_PATH"])
                explicit = resolve_workspace_paths(root / "checkout", artifact_root=root / "explicit")
                self.assertEqual(explicit["artifact_root"], str(root / "explicit"))
            with patch.dict(os.environ, {key: "invalid-relative" for key in settings}):
                restored = resolve_workspace_paths(root / "snapshot/code", frozen_context=selected)
            self.assertEqual(restored, selected)

    def test_invalid_or_incomplete_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for arguments in ({"source_root": root / "missing_checkout"}, {"source_root": "relative"}, {"source_root": root, "artifact_root": ""},
                              {"source_root": root, "execution_root": "relative"},
                              {"source_root": root, "frozen_context": {}},
                              {"source_root": root, "frozen_context": {"source_root": str(root)}}):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    resolve_workspace_paths(**arguments)

    def test_deep_run_projection_keeps_alias_spelling_and_external_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            persistent = root.joinpath(*(["deep-directory"] * 24), "run")
            execution = root / "short/run_alias"
            source = persistent / "simion/field.pa0"
            self.assertGreater(len(str(source)), 259)
            self.assertEqual(project_run_path(source, persistent, execution), str(execution / "simion/field.pa0"))
            external = root / "readonly/source.ion"
            self.assertEqual(project_run_path(external, persistent, execution), str(external))
            self.assertEqual(project_run_path(execution / "simion/field.pa0", persistent, execution), str(execution / "simion/field.pa0"))
            with self.assertRaises(ValueError):
                project_run_path(persistent / "../escape", persistent, execution)

    def test_powershell_bridge_batches_projection_and_preserves_failure(self):
        bridge = Path(__file__).with_name("workspace_paths.ps1")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / "probe.ps1"
            script.write_text(r"""
. $args[0]
$python=$args[1];$root=$args[2]
New-Item -ItemType Directory -Path (Join-Path $root 'source') | Out-Null
$context=Resolve-WorkspacePaths -SourceRoot (Join-Path $root 'source') -ArtifactRoot (Join-Path $root 'payload') -Python $python
$env:MASS_SPECTROMETRY_ARTIFACT_ROOT='relative-invalid'
$frozen=Resolve-WorkspacePaths -SourceRoot (Join-Path $root 'snapshot') -FrozenContext $context -Python $python
if($frozen.artifact_root-ne$context.artifact_root){throw 'frozen roots drifted'}
$canonical=Join-Path $root 'run';$alias=Join-Path $root 'alias'
$paths=Project-RunPath -Paths @((Join-Path $canonical 'one.pa0'),(Join-Path $root 'external.ion')) -ArtifactRunDir $canonical -RunDir $alias -Python $python
if($paths.Count-ne2-or$paths[0]-ne(Join-Path $alias 'one.pa0')-or$paths[1]-ne(Join-Path $root 'external.ion')){throw 'batch projection differs'}
$empty=Project-RunPath -Paths @() -ArtifactRunDir $canonical -RunDir $alias -Python $python
if($empty.Count-ne0){throw 'empty projection differs'}
$one=Project-RunPath -Path (Join-Path $canonical 'two.pa0') -ArtifactRunDir $canonical -RunDir $alias -Python $python
if($one-ne(Join-Path $alias 'two.pa0')){throw 'single projection differs'}
try{Resolve-WorkspacePaths -SourceRoot relative -Python $python;throw 'missing rejection'}catch{if($_-notmatch'absolute path'){throw}}
$frozen|ConvertTo-Json -Compress
""", encoding="utf-8", newline="\n")
            result = subprocess.run([PWSH, "-NoProfile", "-File", str(script), str(bridge), sys.executable, temporary],
                                    cwd=root, timeout=30, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["artifact_root"], str(root / "payload"))

    def test_native_process_environment_is_not_cached_or_used_for_identity(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            root = Path(temporary)
            source = root / "run/input.ion"
            self.assertEqual(project_native_run_path(source), str(source))
            os.environ["MASS_SPECTROMETRY_RUN_DIRECTORY"] = str(root / "run")
            with self.assertRaises(ValueError):
                project_native_run_path(source)
            os.environ["MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY"] = ""
            with self.assertRaises(ValueError):
                project_native_run_path(source)
            os.environ["MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY"] = str(root / "alias")
            self.assertEqual(project_native_run_path(source), str(root / "alias/input.ion"))
            os.environ["MASS_SPECTROMETRY_RUN_EXECUTION_DIRECTORY"] = str(root / "other_alias")
            self.assertEqual(project_native_run_path(source), str(root / "other_alias/input.ion"))
            self.assertEqual(project_native_run_path(root / "external.ion"), str(root / "external.ion"))

    def test_equivalent_roots_and_real_execution_junction(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {}, clear=True):
            root = Path(temporary)
            source = root / "checkout"
            source.mkdir()
            alias = root / "checkout_alias"
            junction = root / "junction.ps1"
            junction.write_text("New-Item -ItemType Junction -Path $args[0] -Target $args[1] | Out-Null", encoding="utf-8")
            result = subprocess.run([PWSH, "-NoProfile", "-File", str(junction), str(alias), str(source)],
                                    cwd=root, timeout=30, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            context = resolve_workspace_paths(source)
            self.assertEqual(resolve_workspace_paths(alias), context)
            with self.assertRaisesRegex(ValueError, "not canonical"):
                resolve_workspace_paths(source, frozen_context={**context, "source_root": str(alias)})
            child = source / "inputs/source.ion"
            projected = project_run_path(child, source, alias)
            self.assertEqual(projected, str(alias / "inputs/source.ion"))
            self.assertNotEqual(projected, str(child))


if __name__ == "__main__":
    unittest.main()

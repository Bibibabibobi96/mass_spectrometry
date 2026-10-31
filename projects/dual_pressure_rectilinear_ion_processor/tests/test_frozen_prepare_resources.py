"""Real pure prepare from its generated frozen package, without live-tree fallback."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import (
    HS1_SOURCE_FIXTURE,
)

ROOT = Path(__file__).resolve().parents[3]
PROJECT_RELATIVE = Path("projects/dual_pressure_rectilinear_ion_processor")
FUNCTIONAL_SOURCE = ROOT / PROJECT_RELATIVE / "analysis/functional.py"

CHILD = r"""
import json, sys
from pathlib import Path
root, run, vendor = map(Path, sys.argv[1:4])
sys.path.insert(0, str(root))
from projects.dual_pressure_rectilinear_ion_processor.analysis.functional import prepare
run.mkdir(); (run/'inputs').mkdir()
(run/'run_config.json').write_text('{"schema_version":1}', encoding='utf-8')
prepare(run, root/'projects/dual_pressure_rectilinear_ion_processor', vendor)
assert all(not str(getattr(module, '__file__', '')).startswith(sys.argv[4])
           for name, module in sys.modules.items() if name.split('.')[0] in {'common', 'projects'})
print('FROZEN_PREPARE=PASS')
"""


class FrozenPrepareResourceTests(unittest.TestCase):
    def make_author(self, root: Path) -> tuple[Path, Path]:
        # Derive the Python set from the same imports used by production prepare.
        for name in (
            "projects.dual_pressure_rectilinear_ion_processor.analysis.functional",
            "projects.dual_pressure_rectilinear_ion_processor.analysis.diagnostics",
            "projects.dual_pressure_rectilinear_ion_processor.analysis.field_diagnostics",
            "projects.dual_pressure_rectilinear_ion_processor.analysis.batching",
            "projects.dual_pressure_rectilinear_ion_processor.analysis.extraction_force_budget",
            "common.contracts.artifact_retention",
            "common.analysis.population_moments",
            "common.analysis.beam_focus_diagnostics",
            "common.analysis.figure_export",
            "common.analysis.plane_crossings",
            "common.analysis.particle_census",
        ):
            importlib.import_module(name)
        author = root / "author"
        for module in tuple(sys.modules.values()):
            source = getattr(module, "__file__", None)
            if not source:
                continue
            source = Path(source).resolve()
            if source.suffix != ".py" or ROOT not in source.parents:
                continue
            relative = source.relative_to(ROOT)
            if (
                relative.parts[0] not in {"common", "projects"}
                or "tests" in relative.parts
                or source.name.startswith("test_")
            ):
                continue
            target = author / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        shutil.copyfile(
            FUNCTIONAL_SOURCE, author / PROJECT_RELATIVE / "analysis/functional.py"
        )
        project = author / PROJECT_RELATIVE
        resources = [
            *[
                (PROJECT_RELATIVE / "simion" / name)
                for name in (
                    "runtime.lua",
                    "native_drive.lua",
                    "build_workbench.lua",
                    "probe_native_field.lua",
                    "extraction_force_audit.lua",
                )
            ],
            Path("common/simion/rf_drive.lua"),
            Path("common/simion/voltage_waveforms.lua"),
            Path("common/simion/scientific_event_csv.lua"),
            Path("common/paths/native_run_path.lua"),
            Path("common/simion/assets/iob_instance_seeds/1_instance_seed.iob"),
            Path("common/simion/assets/iob_instance_seeds/iob_seed_placeholder_01.pa0"),
            Path("common/contracts/artifact_retention.json"),
            Path("common/contracts/schemas/canonical_clock_authority.schema.json"),
            Path("common/contracts/particle_count_policy.json"),
            Path("common/host_resource_policy.json"),
            Path("common/contracts/schemas/simion_batch_continuation.schema.json"),
        ]
        resources.extend(
            (PROJECT_RELATIVE / "config" / name)
            for name in (
                "baseline.json",
                "numerics.json",
                "source.json",
                "acceptance.json",
                "native_operating_point.json",
                "diagnostics.json",
                "field_diagnostics.json",
                "coordinate_transform.json",
                "geometry_sources.json",
                "source_parameter_sources.json",
                "component_matching_derivation.json",
            )
            if (ROOT / PROJECT_RELATIVE / "config" / name).is_file()
        )
        for relative in resources:
            target = author / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative.parts[:4] == (
                "common",
                "simion",
                "assets",
                "iob_instance_seeds",
            ):
                # Prepare only copies/binds this opaque pair; no IOB/PA parser or vendor runs.
                target.write_bytes(b"INERT_COPY_BINDING_FIXTURE_NOT_NATIVE_SEED\n")
            else:
                shutil.copyfile(ROOT / relative, target)
        vendor = root / "inert-vendor"
        hs1 = vendor / "examples/collision_hs1/collision_hs1.lua"
        hs1.parent.mkdir(parents=True)
        hs1.write_text(HS1_SOURCE_FIXTURE, encoding="utf-8")
        self.assertTrue(project.is_dir())
        return author, vendor

    def invoke(
        self, code_root: Path, run: Path, vendor: Path
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                CHILD,
                str(code_root),
                str(run),
                str(vendor),
                str(ROOT),
            ],
            cwd=run.parent,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )

    def test_generated_package_prepares_again_after_author_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            author, vendor = self.make_author(root)
            first = root / "first"
            result = self.invoke(author, first, vendor)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            frozen = first / "inputs/code"
            author.rename(root / "author-moved-away")
            second = root / "second"
            result = self.invoke(frozen, second, vendor)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for relative in (
                "inputs/release.csv",
                "inputs/source.json",
                "inputs/native_timing.json",
                "inputs/instrument_epoch.json",
                "inputs/clock_authority.json",
                "simion/source_states.lua",
                "simion/processor.fly2",
            ):
                self.assertEqual(
                    (first / relative).read_bytes(),
                    (second / relative).read_bytes(),
                    relative,
                )
            # Every dynamic resource and selected config survives generation unchanged.
            for source in (first / "inputs/code").rglob("*"):
                if source.is_file() and source.suffix != ".py":
                    relative = source.relative_to(first / "inputs/code")
                    self.assertEqual(
                        source.read_bytes(),
                        (second / "inputs/code" / relative).read_bytes(),
                        str(relative),
                    )
            for run in (first, second):
                manifest = json.loads((run / "run_config.json").read_text())
                for relative in (
                    "common/paths/native_run_path.lua",
                    "common/simion/scientific_event_csv.lua",
                    "projects/dual_pressure_rectilinear_ion_processor/config/source.json",
                ):
                    target = run / "inputs/code" / relative
                    self.assertTrue(target.is_file(), relative)
                    self.assertIn(str(target), manifest["inputs"].values())

    def test_missing_dynamic_resource_fails_before_materialization(self):
        for relative in (
            PROJECT_RELATIVE / "simion/runtime.lua",
            Path("common/simion/assets/iob_instance_seeds/iob_seed_placeholder_01.pa0"),
        ):
            with (
                self.subTest(resource=str(relative)),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                author, vendor = self.make_author(root)
                (author / relative).unlink()
                run = root / "missing"
                result = self.invoke(author, run, vendor)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("IP prepare required resource is missing", result.stderr)
                self.assertFalse((run / "simion").exists())
                self.assertFalse((run / "inputs/release.csv").exists())
                self.assertFalse((run / "inputs/native_timing.json").exists())

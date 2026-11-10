"""Explicit IP input compilation; all native-looking unit data are inert."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from msplatform.workflows.ion_processor import preparation
from msplatform.backends.simion.resources import native_resource_path
from msplatform.backends.simion.collision_hs1 import adapt_hs1_for_repeat_fly
from msplatform.backends.simion.ip_geometry import render_gem
from msplatform.ion_release.release import generate_release_states
from projects.dual_pressure_rectilinear_ion_processor.tests.test_functional import load_config, HS1_SOURCE_FIXTURE


class IpPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="ip_scientific_inputs_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.config = load_config()
        self.authorities = {}
        for name in ("baseline", "numerics", "source", "acceptance", "native_operating_point"):
            path = self.root / (name + ".json")
            path.write_text(json.dumps(self.config[name]), encoding="utf-8")
            self.authorities[name] = path
        self.vendor = self.root / "official_shape_inert_unit_fixture.lua"
        self.vendor.write_text(HS1_SOURCE_FIXTURE, encoding="utf-8")

    def materialize(self) -> dict:
        return preparation.materialize_inputs(self.run, self.config,
            configuration_files=self.authorities, hs1_source=self.vendor)

    def test_source_compilation_needs_no_vendor_seed_field_or_file_writes(self) -> None:
        before = copy.deepcopy(self.config)
        with patch.object(preparation, "native_resource_path", side_effect=AssertionError("unexpected native lookup")):
            compiled = preparation.compile_source(self.config)
        self.assertEqual(self.config, before)
        self.assertEqual(compiled["states"], generate_release_states(self.config["source"]))
        self.assertEqual(compiled["clock_epoch_id"], "ion_processor_epoch_zero_v1")
        self.assertEqual(list(self.run.iterdir()), [])
        self.assertNotIn("workbench_seed_path", compiled["config"])
        self.assertNotIn("native_field", compiled["config"])
        self.assertEqual(render_gem(compiled["config"]["native_projection"]), render_gem(preparation.native_projection(self.config["baseline"], self.config["numerics"])))

    def test_materialization_binds_explicit_authorities_and_unsolved_resources(self) -> None:
        compiled = self.materialize()
        self.assertEqual((self.run / "simion/processor.fly2").read_text(), compiled["fly2"])
        self.assertEqual((self.run / "simion/source_states.lua").read_text(), compiled["source_states"])
        self.assertEqual((self.run / "inputs/collision_hs1_original.lua").read_bytes(), self.vendor.read_bytes())
        self.assertEqual((self.run / "simion/collision_hs1.lua").read_text(), adapt_hs1_for_repeat_fly(HS1_SOURCE_FIXTURE))
        for name in ("runtime.lua", "build_workbench.lua", "probe_native_field.lua", "extraction_force_audit.lua"):
            self.assertEqual((self.run / "simion" / name).read_bytes(), native_resource_path("ip_" + name).read_bytes())
        for name, source in self.authorities.items():
            self.assertEqual((self.run / "inputs" / (name + ".json")).read_bytes(), source.read_bytes())
        self.assertFalse((self.run / "simion/processor.iob").exists())
        self.assertFalse(any((self.run / "simion").glob("*.pa*")))
        self.assertFalse((self.run / "simion/iob_seed").exists())
        self.assertEqual(json.loads((self.run / "inputs/clock_validation.json").read_text())["status"], "PASS")
        gas = compiled["config"]["gas_runtime"]
        self.assertEqual(gas["sampling_policy"], "legacy_callback_sampling_v1")
        self.assertEqual(gas["source_kind"], "prescribed_proxy")
        self.assertEqual(Path(gas["runtime"]["path"]).read_bytes(), (self.run / "simion/gas_field.lua").read_bytes())
        self.assertEqual((self.run / "simion/collision_hs1_gas.lua").read_bytes(), native_resource_path("collision_hs1_gas.lua").read_bytes())

    def test_missing_vendor_or_resource_refuses_before_outputs(self) -> None:
        self.vendor.unlink()
        with self.assertRaisesRegex(ValueError, "required resource is missing"):
            self.materialize()
        self.assertEqual(list(self.run.iterdir()), [])
        self.vendor.write_text(HS1_SOURCE_FIXTURE, encoding="utf-8")
        with patch.object(preparation, "native_resource_path", side_effect=FileNotFoundError("ip_runtime.lua")):
            with self.assertRaisesRegex(FileNotFoundError, "ip_runtime.lua"):
                self.materialize()
        self.assertEqual(list(self.run.iterdir()), [])

    def test_invalid_hs1_and_missing_or_different_research_authority_refuse_before_outputs(self) -> None:
        self.vendor.write_text("-- INERT NOT A SUPPORTED OFFICIAL MODULE", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "official HS1 reset contract missing"):
            self.materialize()
        self.assertEqual(list(self.run.iterdir()), [])
        self.vendor.write_text(HS1_SOURCE_FIXTURE, encoding="utf-8")
        source = self.authorities.pop("source")
        with self.assertRaisesRegex(ValueError, "missing explicit research authorities.*source"):
            self.materialize()
        self.assertEqual(list(self.run.iterdir()), [])
        self.authorities["source"] = source
        source.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "research authority differs.*source"):
            self.materialize()
        self.assertEqual(list(self.run.iterdir()), [])

    def test_supplied_diagnostic_controls_are_validated_before_output(self) -> None:
        for key in ("diagnostics", "field_diagnostics"):
            with self.subTest(control=key):
                self.config[key] = {"schema_version": 1}
                try:
                    with self.assertRaisesRegex(ValueError, "unsupported .*diagnostics"):
                        self.materialize()
                    self.assertEqual(list(self.run.iterdir()), [])
                finally:
                    del self.config[key]

    def test_explicit_research_edit_is_applied_when_authority_and_request_agree(self) -> None:
        original = self.config["source"]["species"]["mass_amu"]
        self.config["source"]["species"]["mass_amu"] = original + 17
        self.authorities["source"].write_text(json.dumps(self.config["source"]), encoding="utf-8")
        compiled = self.materialize()
        self.assertEqual(compiled["config"]["source"]["species"]["mass_amu"], original + 17)
        self.assertEqual(json.loads((self.run / "inputs/resolved_model.json").read_text())["source"], self.config["source"])
        self.assertEqual(compiled["states"], generate_release_states(self.config["source"]))
        self.assertEqual({row["mass_amu"] for row in compiled["states"]}, {original + 17})

    def test_empty_upstream_keeps_original_clock_and_zero_native_source(self) -> None:
        admission = dict(rows=[], contract=dict(frame_id=self.config["source"]["frame_id"]),
                         census=dict(mother_count=100), clock=dict(clock_epoch_id="original_upstream_epoch"))
        compiled = preparation.compile_source(self.config, admission=admission)
        self.assertEqual(compiled["states"], [])
        self.assertEqual(compiled["clock_epoch_id"], "original_upstream_epoch")
        self.assertEqual(compiled["config"]["source"]["particle_count"], 0)
        self.assertEqual(compiled["config"]["source"]["mother_particle_count"], 100)
        self.assertEqual(list(self.run.iterdir()), [])

    def test_explicit_zero_pressure_materializes_without_relaxing_other_gas_constraints(self) -> None:
        self.config["baseline"]["gas"]["hp_pressure_pa"] = 0
        self.authorities["baseline"].write_text(json.dumps(self.config["baseline"]), encoding="utf-8")
        compiled = self.materialize()
        self.assertEqual(compiled["config"]["baseline"]["gas"]["hp_pressure_pa"], 0)
        for key in ("temperature_k", "mass_amu", "cross_section_m2"):
            broken = copy.deepcopy(self.config)
            broken["baseline"]["gas"][key] = 0
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "nonpositive"):
                preparation.validate_configs(broken)
        for pressure in (-1, float("nan"), float("inf")):
            broken = copy.deepcopy(self.config)
            broken["baseline"]["gas"]["lp_pressure_pa"] = pressure
            with self.subTest(pressure=pressure), self.assertRaises(ValueError):
                preparation.validate_configs(broken)

    def test_missing_hs1_gas_binding_refuses_before_any_output(self) -> None:
        real = preparation.native_resource_path
        def selected(name):
            if name == "collision_hs1_gas.lua":
                raise FileNotFoundError(name)
            return real(name)
        with patch.object(preparation, "native_resource_path", side_effect=selected):
            with self.assertRaisesRegex(FileNotFoundError, "collision_hs1_gas"):
                self.materialize()
        self.assertEqual(list(self.run.iterdir()), [])

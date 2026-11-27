"""Native preflight derives typed species and rejects unsupported electrons."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from msplatform.physics import CONSTANTS, ELECTRON_CONSTANTS
from msplatform.particle_release import sample_release
from msplatform.recipes import load_recipe
from msplatform.recipes.native import _study, native_species_registry
from msplatform.results.particle_data import read_particle_data, write_particle_data
from msplatform.tracing import trace_particles
from tests.particle_release.test_cylinder import halton_spec


class NativeSpeciesTests(unittest.TestCase):
    def test_simion_public_planner_rejects_explicit_electron_before_native(self):
        from msplatform.backends.simion.tracking_execution import plan_tracking_execution
        release = halton_spec(3)
        release["species"] = {"species_kind": "electron", "mass_amu": ELECTRON_CONSTANTS["mass_u"], "charge_state": -1}
        packet = sample_release({"schema_version": 1, "role": "canonical_birth_source_request",
            "release_spec": release, "clock": {"clock_epoch_id": "epoch", "authority_sha256": "a" * 64},
            "instrument_origin_us": 0., "species_id": "electron", "source_component_id": "source",
            "relative_weights": None}).to_dict()
        with patch("msplatform.backends.simion.tracking_execution.require_prepared_model", return_value={}), \
             patch("msplatform.backends.simion.tracking_execution.model_geometry", return_value=SimpleNamespace(frontend_geometry={})):
            with self.assertRaisesRegex(ValueError, "SIMION native electron tracing is not yet validated"):
                plan_tracking_execution(None, particles=packet, clock_records={}, propagation={}, observations={}, numerics={})

    def test_synthetic_native_v2_data_retains_species_and_rejects_mass_mismatch(self):
        recipe = load_recipe(Path("recipes/reference/uniform_e.toml")).to_dict()
        result = trace_particles(recipe)
        result.initial_states[0]["lineage_status"] = "primary_birth"
        metadata = {"schema_version": 2, "initial_state_basis": "native_birth_verified",
                    "frame_id": recipe["frame_id"], "clock": recipe["clock"], "species": recipe["species"]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_particle_data(root, result, metadata=metadata)
            self.assertEqual(read_particle_data(root)["metadata"]["species"], recipe["species"])
        wrong = copy.deepcopy(metadata)
        wrong["species"][0]["mass_kg"] *= 2
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "initial state disagrees with its species"):
                write_particle_data(root, result, metadata=wrong)
            self.assertEqual(list(root.iterdir()), [])

    def test_negative_ion_in_vacuum_retains_explicit_species(self):
        study = json.loads(files("msplatform.examples").joinpath("oa_split_tof_native_small_v1.json").read_text(encoding="utf-8"))
        study["release"]["release_spec"]["species"]["charge_state"] = -1
        _study(study, "simion")
        result = native_species_registry(study)
        self.assertEqual(result[0]["species_kind"], "ion")
        self.assertEqual(result[0]["charge_c"], -CONSTANTS["elementary_charge_c"])
        self.assertEqual(result[0]["mass_kg"], 100 * CONSTANTS["atomic_mass_constant_kg"])

    def test_native_electron_is_not_accepted_as_negative_ion(self):
        study = json.loads(files("msplatform.examples").joinpath("oa_split_tof_native_small_v1.json").read_text(encoding="utf-8"))
        electron = {"species_kind": "electron", "mass_amu": ELECTRON_CONSTANTS["mass_u"], "charge_state": -1}
        for tracer in ("simion", "comsol"):
            request = copy.deepcopy(study)
            request["release"]["release_spec"] = halton_spec(3)
            request["release"]["release_spec"]["species"] = electron
            if tracer == "comsol":
                # Use the actual COMSOL example's numerical contract.
                base = json.loads(files("msplatform.examples").joinpath("oa_split_tof_comsol_small_v1.json").read_text(encoding="utf-8"))
                request["numerics"]["tracing"] = base["numerics"]["tracing"]
            with self.subTest(tracer=tracer), self.assertRaisesRegex(ValueError, "native electron tracing is not yet validated"):
                _study(request, tracer)

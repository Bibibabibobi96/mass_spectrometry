"""Explicit release species and immutable receipt round trips."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from msplatform.physics import ELECTRON_CONSTANTS
from msplatform.particle_release import sample_release
from msplatform.particle_release.release import generate_release_states, materialize_release, validate_materialized_release
from tests.particle_release.test_cylinder import halton_spec


class ParticleReleaseSpeciesTests(unittest.TestCase):
    def test_three_kinds_preserve_mass_charge_and_receipt(self):
        cases = (("ion", 100.0, 1), ("ion", 100.0, -1), ("electron", ELECTRON_CONSTANTS["mass_u"], -1))
        for kind, mass, charge in cases:
            with self.subTest(kind=kind, charge=charge), tempfile.TemporaryDirectory() as temporary:
                request = halton_spec(3)
                request["species"] = {"species_kind": kind, "mass_amu": mass, "charge_state": charge}
                states = generate_release_states(request)
                self.assertTrue(all(row["mass_amu"] == mass and row["charge_state"] == charge for row in states))
                root = Path(temporary)
                receipt = materialize_release(request, root / "source.csv", root / "receipt.json")
                self.assertEqual(validate_materialized_release(root / "receipt.json"), receipt)
                self.assertEqual(receipt["release_spec"]["species"], request["species"])
                authored = sample_release({"schema_version": 1, "role": "canonical_birth_source_request",
                    "release_spec": request, "clock": {"clock_epoch_id": "epoch", "authority_sha256": "a" * 64},
                    "instrument_origin_us": 12.5, "species_id": "declared_species", "source_component_id": "source",
                    "relative_weights": {"1": 0.5, "2": 2.0, "3": 4.0}})
                self.assertEqual([row["particle_weight"] for row in authored.rows], [0.5, 2.0, 4.0])
                self.assertTrue(all(row["mass_amu"] == mass and row["charge_state"] == charge
                                    and row["instrument_time_us"] == 12.5 for row in authored.rows))
                self.assertEqual(authored.to_dict()["realization"]["spec"]["species"], request["species"])

    def test_missing_kind_wrong_electron_and_legacy_new_execution_rejected(self):
        request = halton_spec(3)
        bad_species = ({"mass_amu": 100., "charge_state": -1},
                       {"species_kind": "electron", "mass_amu": 100., "charge_state": -1},
                       {"species_kind": "electron", "mass_amu": ELECTRON_CONSTANTS["mass_u"], "charge_state": -2})
        for species in bad_species:
            with self.subTest(species=species), self.assertRaises(ValueError):
                generate_release_states({**request, "species": species})
        old = copy.deepcopy(request)
        old.update(schema_version=1, role="repository_ion_release")
        old["species"].pop("species_kind")
        with self.assertRaises(ValueError):
            generate_release_states(old)

    def test_ion11_precision_rejects_electron_before_materialization(self):
        from msplatform.particle_release.dotnet_box import validate_dotnet_box_spec
        request = {"schema_version": 2, "role": "repository_particle_release", "frame_id": "laboratory",
                   "particle_count": 1, "mother_particle_count": 1, "common_time_of_birth_s": 0.,
                   "geometry": {"shape": "box", "center_mm": [0., 0., 0.], "half_width_mm": [1., 1., 1.]},
                   "species": {"species_kind": "electron", "mass_amu": ELECTRON_CONSTANTS["mass_u"], "charge_state": -1},
                   "sampling": {"strategy": "dotnet_gaussian_box_ion11_v1", "seed": 1,
                                "energy_mean_ev": 1., "energy_std_ev": 0., "constants_id": "repository_particle_physics_v1"}}
        with self.assertRaisesRegex(ValueError, "ION11 box precision"):
            validate_dotnet_box_spec(request)

    def test_recorded_birth_needs_declared_kind_and_preserves_weight_clock(self):
        from msplatform.contracts.clock import ClockIdentity
        from msplatform.io.manifest_records import file_record
        from msplatform.particle_release.authoring import load_recorded_release
        request = halton_spec(3)
        request["species"] = {"species_kind": "electron", "mass_amu": ELECTRON_CONSTANTS["mass_u"], "charge_state": -1}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            materialize_release(request, root / "source.csv", root / "receipt.json")
            args = dict(clock=ClockIdentity("epoch", "a" * 64), frame_id=request["frame_id"],
                        source_component_id="source", species_id="electron", species_kind="electron",
                        relative_weights={1: 0.5, 2: 2., 3: 4.}, instrument_origin_us=12.5,
                        expected_particle_ids=[1, 2, 3])
            source = file_record(root / "source.csv")
            packet = load_recorded_release(source, **args)
            self.assertEqual(packet["recorded_source"]["species_kind"], "electron")
            self.assertEqual([row["particle_weight"] for row in packet["rows"]], [0.5, 2., 4.])
            self.assertTrue(all(row["instrument_time_us"] == 12.5 for row in packet["rows"]))
            with self.assertRaises(TypeError):
                load_recorded_release(source, **{k: v for k, v in args.items() if k != "species_kind"})
            with self.assertRaises(ValueError):
                load_recorded_release(source, **{**args, "species_kind": "unrecognized"})

    def test_legacy_receipt_is_read_only_without_guessing_kind(self):
        request = halton_spec(3)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            receipt = materialize_release(request, root / "source.csv", root / "receipt.json")
            old = copy.deepcopy(request)
            old.update(schema_version=1, role="repository_ion_release")
            old["species"].pop("species_kind")
            receipt.update(schema_version=1, role="repository_ion_release", release_spec=old,
                           release_spec_sha256=hashlib.sha256(
                               json.dumps(old, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest().upper())
            path = root / "legacy.json"
            path.write_text(json.dumps(receipt), encoding="utf-8")
            before = path.read_bytes()
            with patch("msplatform.particle_release.cylinder.generate_cylinder_release_states",
                       side_effect=AssertionError("historical reader invoked a producer")):
                result = validate_materialized_release(path)
            self.assertEqual(path.read_bytes(), before)
            self.assertNotIn("species_kind", result["release_spec"]["species"])
            with self.assertRaises(ValueError):
                generate_release_states(old)
            with (root / "source.csv").open("ab") as stream:
                stream.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "historical release table identity changed"):
                validate_materialized_release(path)

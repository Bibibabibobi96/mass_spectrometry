from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from collections.abc import Callable

from common.contracts.particle_physics import (
    AMU_KG,
    ELEMENTARY_CHARGE_C as E_CHARGE_C,
)
from projects.rf_multipole_ion_optics.core.compile_design_request import compile_design_request
from projects.rf_multipole_ion_optics.core.interface_geometry import transport_observations
from projects.rf_multipole_ion_optics.runtime.particle_source_preflight import (
    COLUMNS,
    load_validated_source,
    load_release_spec,
    materialize_source_release,
    validate_source,
)
from projects.rf_multipole_ion_optics.runtime.simion_particle_source import render_canonical_source
from common.ion_release import mt19937_disk_cone_rf_phase as release_sampler
from projects.rf_multipole_ion_optics.runtime.runtime_profile import resolve_runtime_profile
from projects.rf_multipole_ion_optics.runtime.resource_budget import validate_pilot_budget
from common.ion_release.release import materialize_release_from_file as materialize
from projects.rf_multipole_ion_optics.tests.domain.test_compile_design_request import design_request


REPO_ROOT = Path(__file__).resolve().parents[4]

def planar_release_spec(resolved: dict, *, count: int = 100) -> dict:
    """A new authored source, sharing the established family sampler only."""
    return dict(
        schema_version=1,
        role="repository_ion_release",
        frame_id=resolved["coordinate"]["coordinate_id"],
        particle_count=count,
        mother_particle_count=count,
        geometry=dict(
            shape="disk",
            center_mm=[0.0, 0.0, transport_observations(resolved)["release_plane_z_mm"]],
            radius_mm=0.5,
        ),
        species=dict(mass_amu=524.0, charge_state=resolved["particle_source"]["charge_state"]),
        sampling=dict(
            strategy="mt19937_uniform_disk_filled_cone_rf_phase_v1",
            seed=2026072801,
            rf_frequency_hz=resolved["drive"]["frequency_Hz"],
            kinetic_energy_ev=2.0,
            cone_half_angle_deg=5.0,
        ),
    )


class ParticleSourcePreflightTest(unittest.TestCase):
    def test_registered_524da_bare_source_resolves_without_sampling_or_authorization(self) -> None:
        with patch.object(
            release_sampler,
            "generate_mt19937_disk_cone_rf_phase_states",
            side_effect=AssertionError("preflight must not sample"),
        ):
            runtime = resolve_runtime_profile(
                REPO_ROOT, "rf_multipole_ion_optics", "octupole_bare_no_acceleration_524da_n100"
            )
            baseline = resolve_runtime_profile(
                REPO_ROOT, "rf_multipole_ion_optics", "octupole_no_acceleration_full_length"
            )
            self.assertEqual(runtime["design_profile_resolution"], baseline["design_profile_resolution"])
            self.assertEqual(runtime["particle_source"]["particle_count"], 100)
            self.assertNotIn("path", runtime["particle_source"])
            self.assertEqual(
                runtime["design_profile_resolution"]["resolved_design"]["geometry_mm"]["enclosure"]["model"],
                "bare",
            )
            with self.assertRaisesRegex(ValueError, "multipole commercial solver pilot is not authorized"):
                validate_pilot_budget(
                    repo_root=REPO_ROOT,
                    budget_path=Path(runtime["engineering_budget"]["path"]),
                    project_id="rf_multipole_ion_optics",
                    solver="simion",
                    runtime_profile_id=runtime["runtime_profile_id"],
                    design_profile_id=runtime["design_profile_id"],
                    retention_class="compact",
                )

    def test_524da_release_changes_speed_without_replacing_the_original_mother(self) -> None:
        runtime = resolve_runtime_profile(
            REPO_ROOT, "rf_multipole_ion_optics", 'octupole_bare_no_acceleration_524da_n100'
        )
        resolved = runtime["design_profile_resolution"]["resolved_design"]
        old_runtime = resolve_runtime_profile(REPO_ROOT, "rf_multipole_ion_optics", 'octupole_no_acceleration_full_length')
        with Path(old_runtime["particle_source"]["path"]).open(encoding="utf-8", newline="") as stream:
            original = list(csv.DictReader(stream))
        with tempfile.TemporaryDirectory(prefix="octupole-524da-release-") as directory:
            root = Path(directory)
            frozen = root / "release_spec.json"
            shutil.copyfile(runtime["particle_source"]["release_spec"]["path"], frozen)
            source, receipt = root / "source.csv", root / "receipt.json"
            with patch.object(
                release_sampler,
                "generate_mt19937_disk_cone_rf_phase_states",
                wraps=release_sampler.generate_mt19937_disk_cone_rf_phase_states,
            ) as sample:
                materialize_source_release(frozen, source, receipt, resolved)
                metadata, states = load_validated_source(
                    source, resolved, release_spec_path=frozen, release_receipt_path=receipt
                )
                self.assertEqual(sample.call_count, 1)
            self.assertEqual(
                (metadata["particle_count"], metadata["mass_amu"], metadata["charge_state"]), (100, 524.0, 1)
            )
            self.assertEqual(len(states), len(original))
            speed_scale = math.sqrt(100.0 / 524.0)
            # Binary64 roundoff from speed, unit-vector and CSV repr operations.
            roundoff = 8 * sys.float_info.epsilon
            for before, after in zip(original, states, strict=True):
                for field in ("particle_id", "birth_time_s", "x_mm", "y_mm", "z_mm", "charge_state"):
                    self.assertEqual(float(after[field]), float(before[field]), field)
                old_velocity = [float(before[axis]) for axis in ("vx_m_s", "vy_m_s", "vz_m_s")]
                new_velocity = [float(after[axis]) for axis in ("vx_m_s", "vy_m_s", "vz_m_s")]
                for old, new in zip(old_velocity, new_velocity, strict=True):
                    self.assertTrue(math.isclose(new, old * speed_scale, rel_tol=roundoff))
                    self.assertTrue(
                        math.isclose(new / math.hypot(*new_velocity), old / math.hypot(*old_velocity), rel_tol=roundoff)
                    )
                self.assertEqual(float(after["mass_amu"]), 524.0)
            self.assertEqual(metadata["energy_model"]["kinetic_energy_eV"], 2.0)

    def setUp(self) -> None:
        request = design_request(segmentation={"strategy": "off"})
        self.resolved = compile_design_request(request, expected_identity=request["identity"])
        self.mass = 100.0
        energy = self.resolved["particle_source"]["energy_model"]["kinetic_energy_eV"]
        self.speed = math.sqrt(2 * energy * E_CHARGE_C / (self.mass * AMU_KG))

    def write_source(
        self,
        directory: str,
        *,
        count: int = 100,
        mutate: Callable[[list[dict[str, object]]], None] | None = None,
    ) -> Path:
        path = Path(directory) / "particles.csv"
        rows = []
        source_z = transport_observations(self.resolved)["release_plane_z_mm"]
        for particle_id in range(1, count + 1):
            row = {
                "particle_id": particle_id,
                "birth_time_s": 0.0,
                "x_mm": 0.0,
                "y_mm": 0.0,
                "z_mm": source_z,
                "vx_m_s": 0.0,
                "vy_m_s": 0.0,
                "vz_m_s": self.speed,
                "mass_amu": self.mass,
                "charge_state": self.resolved["particle_source"]["charge_state"],
            }
            rows.append(row)
        if mutate:
            mutate(rows)
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_release_materializes_once_and_full_and_batch_projection_keep_frozen_states(self) -> None:
        from common.ion_release import mt19937_disk_cone_rf_phase as sampler

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            spec = directory / "release.json"
            spec.write_text(json.dumps(planar_release_spec(self.resolved)), encoding="utf-8")
            source, receipt = directory / "source.csv", directory / "receipt.json"
            resolved_path = directory / "resolved.json"
            resolved_path.write_text(json.dumps(self.resolved), encoding="utf-8")
            with patch.object(
                sampler,
                "generate_mt19937_disk_cone_rf_phase_states",
                wraps=sampler.generate_mt19937_disk_cone_rf_phase_states,
            ) as generate:
                load_release_spec(spec, self.resolved)
                self.assertEqual(generate.call_count, 0)
                materialize_source_release(spec, source, receipt, self.resolved)
                original = source.read_bytes()
                options = dict(release_spec_path=spec, release_receipt_path=receipt)
                metadata, rows = load_validated_source(source, self.resolved, **options)
                self.assertEqual((metadata["mass_amu"], metadata["particle_count"]), (524.0, 100))
                fly, states, count = render_canonical_source(source, resolved_path, **options)
                self.assertEqual(count, 100)
                self.assertIn("mass=524", fly)
                for first, last in [(1, 40), (41, 100)]:
                    part, _, n = render_canonical_source(
                        source, resolved_path, **options, particle_id_min=first, particle_id_max=last
                    )
                    self.assertEqual(n, last - first + 1)
                    self.assertEqual(part.count("standard_beam"), n)
                self.assertIn(format(float(rows[0]["birth_time_s"]) * 1e6, ".12g"), states)
                self.assertEqual(generate.call_count, 1)
                self.assertEqual(source.read_bytes(), original)
                with self.assertRaisesRegex(ValueError, "overwrite"):
                    materialize_source_release(spec, source, receipt, self.resolved)
                with self.assertRaisesRegex(ValueError, "another source"):
                    load_validated_source(source, self.resolved, **options, expected_kinetic_energy_ev=2.0)
                for field in ("frame_id", "species", "sampling"):
                    changed = planar_release_spec(self.resolved)
                    if field == "frame_id":
                        changed[field] = "another_frame"
                    elif field == "species":
                        changed[field]["charge_state"] = 2
                    else:
                        changed[field]["rf_frequency_hz"] *= 2
                    spec.write_text(json.dumps(changed), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_validated_source(source, self.resolved, **options)
                spec.write_text(json.dumps(planar_release_spec(self.resolved)), encoding="utf-8")
                source.write_bytes(original.replace(b"524.0", b"100.0", 1))
                with self.assertRaisesRegex(ValueError, "receipt"):
                    load_validated_source(source, self.resolved, **options)

    def test_release_cli_and_projection_execute_from_detached_frozen_code(self) -> None:
        repo = Path(__file__).resolve().parents[4]
        with tempfile.TemporaryDirectory() as temporary:
            frozen = Path(temporary) / "snapshot"
            for relative in (
                "common/contracts", "common/simion", "common/ion_release",
                "projects/rf_multipole_ion_optics/runtime",
            ):
                shutil.copytree(
                    repo / relative,
                    frozen / relative,
                    ignore=lambda directory, names: [
                        name
                        for name in names
                        if name == "__pycache__"
                        or ((Path(directory) / name).is_file() and Path(name).suffix not in {".py", ".json"})
                    ],
                )
            interface = Path("projects/rf_multipole_ion_optics/core/interface_geometry.py")
            (frozen / interface).parent.mkdir(parents=True)
            shutil.copyfile(repo / interface, frozen / interface)
            inputs = frozen / "inputs"
            inputs.mkdir()
            (inputs / "spec.json").write_text(json.dumps(planar_release_spec(self.resolved)), encoding="utf-8")
            (inputs / "resolved.json").write_text(json.dumps(self.resolved), encoding="utf-8")
            code = r"""
import sys
from pathlib import Path
from unittest.mock import patch
from projects.rf_multipole_ion_optics.runtime import particle_source_preflight as preflight
from projects.rf_multipole_ion_optics.runtime.simion_particle_source import render_canonical_source
from common.ion_release import mt19937_disk_cone_rf_phase as sampler
assert Path(preflight.__file__).resolve().is_relative_to(Path.cwd().resolve())
source,receipt,spec,resolved=[Path('inputs')/n for n in ('source.csv','receipt.json','spec.json','resolved.json')]
sys.argv=['preflight','--source',str(source),'--resolved-design',str(resolved),'--output','inputs/metadata.json',
          '--release-spec',str(spec),'--release-receipt',str(receipt),'--materialize-release']
with patch.object(sampler,'generate_mt19937_disk_cone_rf_phase_states',wraps=sampler.generate_mt19937_disk_cone_rf_phase_states) as generate:
 preflight.main()
 for first,last in [(None,None),(1,40),(41,100)]:
  fly,states,count=render_canonical_source(source,resolved,release_spec_path=spec,release_receipt_path=receipt,
                                        particle_id_min=first,particle_id_max=last)
  assert 'mass=524' in fly
  assert count==(100 if first is None else last-first+1)
 assert generate.call_count==1
print('DETACHED_RELEASE=PASS SAMPLES=1')
"""
            result = subprocess.run(
                [sys.executable, "-B", "-c", code],
                cwd=frozen,
                env={**os.environ, "PYTHONPATH": str(frozen)},
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("DETACHED_RELEASE=PASS SAMPLES=1", result.stdout)

    def test_shell_choice_does_not_change_source_projection(self) -> None:
        request = design_request(segmentation={"strategy": "off"})
        request["geometry_mm"]["enclosure"] = dict(
            model="cylindrical_grounded_shell", inner_radius_mm=10.0,
            wall_thickness_mm=1.0, z_min_mm=2.0, z_max_mm=90.0,
        )
        request["static_electrodes_V"] = dict(role="grounded_shell_static_electrodes", ground_V=0.0)
        shell = compile_design_request(request, expected_identity=request["identity"])
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            original = source.read_bytes()
            rendered = []
            for name, resolved in (("bare", self.resolved), ("shell", shell)):
                path = Path(directory) / f"{name}.json"
                path.write_text(json.dumps(resolved), encoding="utf-8")
                rendered.append(render_canonical_source(source, path))
            self.assertEqual(rendered[0], rendered[1])
            self.assertEqual(source.read_bytes(), original)

    def test_valid_source_binds_hash_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_source(self.write_source(directory), self.resolved)
        self.assertEqual(result["particle_count"], 100)
        self.assertEqual(result["mass_amu"], self.mass)
        self.assertEqual(result["parent_resolved_design_sha256"], self.resolved["resolved_sha256"])

    def test_projection_reuses_the_exact_validated_csv_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            source.write_bytes(b"\xef\xbb\xbf" + source.read_bytes())
            resolved_path = Path(directory) / "resolved.json"
            resolved_path.write_text(json.dumps(self.resolved), encoding="utf-8")
            original_open = Path.open
            reads = []

            def opened(path, *args, **options):
                if path == source:
                    reads.append(path)
                return original_open(path, *args, **options)

            with patch.object(Path, "open", opened):
                fly, states, count = render_canonical_source(source, resolved_path)
            self.assertEqual(reads, [source])
            self.assertEqual(count, 100)
            metadata, rows = load_validated_source(source, self.resolved)
            self.assertEqual(metadata, validate_source(source, self.resolved))
            self.assertEqual(metadata["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest().upper())
            self.assertEqual(len(rows), count)
            self.assertEqual(fly.count("standard_beam {"), count)
            self.assertIn("[100]", states)

    def test_source_attacks_fail_closed(self) -> None:
        attacks = {
            "duplicate": lambda rows: rows[1].update(particle_id=1),
            "nan": lambda rows: rows[0].update(x_mm="nan"),
            "plane": lambda rows: rows[0].update(z_mm=float(rows[0]["z_mm"]) + 1e-6),
            "velocity": lambda rows: rows[0].update(vz_m_s=float(rows[0]["vz_m_s"]) * 1.01),
            "mass": lambda rows: rows[0].update(mass_amu=101.0),
            "clock": lambda rows: rows[0].update(birth_time_s=-1e-9),
        }
        for label, mutation in attacks.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    validate_source(
                        self.write_source(directory, mutate=mutation),
                        copy.deepcopy(self.resolved),
                    )
                resolved = Path(directory) / "resolved.json"
                resolved.write_text(json.dumps(self.resolved), encoding="utf-8")
                with self.assertRaises(ValueError):
                    render_canonical_source(
                        self.write_source(directory, mutate=mutation),
                        resolved,
                    )

    def test_nonstandard_positive_count_remains_a_valid_canonical_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = validate_source(self.write_source(directory, count=99), self.resolved)
        self.assertEqual(result["particle_count"], 99)

    def test_hash_bound_volume_snapshot_is_the_only_nonplanar_source_exception(self) -> None:
        spec = {
            "schema_version": 1,
            "role": "continuous_axial_volume_ion_beam_source",
            "method": "independent_spatial_velocity_ion_source_snapshot_v1",
            "source_region_model": "ion_source_volume_cylinder_v1",
            "source_frame_id": "multipole_cartesian_z_axis_v1",
            "particle_count": 20,
            "seed": 7,
            "snapshot_time_s": 0.0,
            "geometry_mm": {
                "center_x_mm": 0.0,
                "center_y_mm": 0.0,
                "center_z_mm": -1.5,
                "radius_mm": 0.5,
                "axial_length_mm": 2.2,
            },
            "velocity_distribution": {
                "mean_vx_m_s": 0.0,
                "mean_vy_m_s": 0.0,
                "mean_vz_m_s": 1964.668136,
                "sigma_vx_m_s": 35.0,
                "sigma_vy_m_s": 35.0,
                "sigma_vz_m_s": 50.0,
                "minimum_vz_m_s": 1500.0,
            },
            "ion": {"mass_amu": 100.0, "charge_state": 1},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / "spec.json"
            source_path = root / "source.csv"
            receipt_path = root / "receipt.json"
            resolved_path = root / "resolved.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            resolved_path.write_text(json.dumps(self.resolved), encoding="utf-8")
            materialize(spec_path, source_path, receipt_path)
            with self.assertRaisesRegex(ValueError, "source plane"):
                validate_source(source_path, self.resolved)
            result = validate_source(
                source_path,
                self.resolved,
                volume_snapshot_receipt_path=receipt_path,
            )
            self.assertTrue(result["source_volume_snapshot"])
            self.assertEqual(
                result["energy_model_authority"],
                "continuous_axial_volume_source_receipt",
            )
            _, states, count = render_canonical_source(
                source_path,
                resolved_path,
                volume_snapshot_receipt_path=receipt_path,
            )
            self.assertEqual(count, 20)
            self.assertIn("[1]", states)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["particle_source"]["sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not bind"):
                validate_source(
                    source_path,
                    self.resolved,
                    volume_snapshot_receipt_path=receipt_path,
                )

    def test_bounded_distribution_records_actual_statistics_and_rejects_outlier(self) -> None:
        bounded = copy.deepcopy(self.resolved)
        bounded["particle_source"]["energy_model"] = {
            "kind": "bounded_distribution",
            "minimum_energy_eV": 1.8,
            "maximum_energy_eV": 2.2,
            "nominal_energy_eV": 2.0,
            "authority": "fixture.json",
        }
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            result = validate_source(source, bounded)
        statistics = result["sample_energy_statistics_eV"]
        self.assertAlmostEqual(statistics["minimum"], 2.0)
        self.assertAlmostEqual(statistics["maximum"], 2.0)
        self.assertAlmostEqual(statistics["mean"], 2.0)

        def outside(rows: list[dict[str, object]]) -> None:
            rows[0]["vz_m_s"] = self.speed * math.sqrt(2.21 / 2.0)

        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(ValueError, "outside the resolved closed interval"),
        ):
            validate_source(self.write_source(directory, mutate=outside), bounded)

    def test_explicit_operating_point_allows_5ev_without_relaxing_default(self) -> None:
        def five_ev(rows: list[dict[str, object]]) -> None:
            for row in rows:
                row["vz_m_s"] = self.speed * math.sqrt(5.0 / 2.0)

        family = {
            "schema_version": 1,
            "operating_points": {
                "five_ev": {
                    "mass_amu": 100.0,
                    "charge_state": 1,
                    "kinetic_energy_eV": {"distribution": "fixed", "value": 5.0},
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory, mutate=five_ev)
            family_path = Path(directory) / "family.json"
            family_path.write_text(json.dumps(family), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "resolved design|resolved closed interval"):
                validate_source(source, self.resolved)
            result = validate_source(
                source,
                self.resolved,
                source_family_path=family_path,
                operating_point_id="five_ev",
            )
        self.assertEqual(result["operating_point_binding"]["operating_point_id"], "five_ev")

    def test_campaign_energy_override_validates_derived_5ev_source(self) -> None:
        def five_ev(rows: list[dict[str, object]]) -> None:
            for row in rows:
                row["vz_m_s"] = self.speed * math.sqrt(5.0 / 2.0)

        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory, mutate=five_ev)
            result = validate_source(
                source,
                self.resolved,
                expected_kinetic_energy_ev=5.0,
            )
        self.assertEqual(result["energy_model"]["kinetic_energy_eV"], 5.0)
        self.assertEqual(
            result["energy_model_authority"],
            "campaign_particle_source_derivation",
        )

    def test_operating_point_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            family_path = Path(directory) / "family.json"
            family_path.write_text(
                json.dumps({"schema_version": 1, "operating_points": {}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "requires both"):
                validate_source(
                    source,
                    self.resolved,
                    source_family_path=family_path,
                )
            with self.assertRaisesRegex(ValueError, "binding is invalid"):
                validate_source(
                    source,
                    self.resolved,
                    source_family_path=family_path,
                    operating_point_id="missing",
                )

    def test_operating_point_rejects_invalid_energy_domains(self) -> None:
        invalid_models = {
            "fixed_nan": {"distribution": "fixed", "value": math.nan},
            "fixed_positive_inf": {"distribution": "fixed", "value": math.inf},
            "fixed_negative_inf": {"distribution": "fixed", "value": -math.inf},
            "fixed_negative": {"distribution": "fixed", "value": -1.0},
            "uniform_nan_min": {
                "distribution": "uniform",
                "min": math.nan,
                "max": 2.2,
            },
            "uniform_positive_inf_max": {
                "distribution": "uniform",
                "min": 1.8,
                "max": math.inf,
            },
            "uniform_negative_inf_min": {
                "distribution": "uniform",
                "min": -math.inf,
                "max": 2.2,
            },
            "uniform_negative": {
                "distribution": "uniform",
                "min": -0.1,
                "max": 2.2,
            },
            "uniform_reversed": {
                "distribution": "uniform",
                "min": 2.2,
                "max": 1.8,
            },
        }
        for label, energy_model in invalid_models.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                source = self.write_source(directory)
                family = {
                    "schema_version": 1,
                    "operating_points": {
                        "invalid": {
                            "mass_amu": 100.0,
                            "charge_state": 1,
                            "kinetic_energy_eV": energy_model,
                        }
                    },
                }
                family_path = Path(directory) / "family.json"
                family_path.write_text(json.dumps(family), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "must be finite|bounds must be finite"):
                    validate_source(
                        source,
                        self.resolved,
                        source_family_path=family_path,
                        operating_point_id="invalid",
                    )

    def test_operating_point_parsing_and_sha_share_one_frozen_read(self) -> None:
        family = {
            "schema_version": 1,
            "operating_points": {
                "two_ev": {
                    "mass_amu": 100.0,
                    "charge_state": 1,
                    "kinetic_energy_eV": {"distribution": "fixed", "value": 2.0},
                }
            },
        }
        first_bytes = json.dumps(family).encode("utf-8")
        drifted_bytes = json.dumps(
            {
                **family,
                "operating_points": {
                    "two_ev": {
                        **family["operating_points"]["two_ev"],
                        "kinetic_energy_eV": {
                            "distribution": "fixed",
                            "value": 5.0,
                        },
                    }
                },
            }
        ).encode("utf-8")

        class DriftingSourceFamily:
            def __init__(self) -> None:
                self.read_count = 0

            def read_bytes(self) -> bytes:
                self.read_count += 1
                return first_bytes if self.read_count == 1 else drifted_bytes

        with tempfile.TemporaryDirectory() as directory:
            source = self.write_source(directory)
            drifting_family = DriftingSourceFamily()
            result = validate_source(
                source,
                self.resolved,
                source_family_path=drifting_family,  # type: ignore[arg-type]
                operating_point_id="two_ev",
                expected_source_family_sha256=hashlib.sha256(first_bytes).hexdigest(),
            )
        self.assertEqual(drifting_family.read_count, 1)
        self.assertEqual(
            result["operating_point_binding"]["source_family_sha256"],
            hashlib.sha256(first_bytes).hexdigest().upper(),
        )


if __name__ == "__main__":
    unittest.main()

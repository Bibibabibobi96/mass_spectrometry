from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.multipole import runtime_profile
from common.multipole.runtime_profile import (
    resolve_campaign_experiment,
    resolve_runtime_profile,
)
from common.multipole.simion_numerics import normalize_simion_solver_numerics


REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_IDS = (
    "rf_quadrupole_ion_optics",
    "rf_hexapole_ion_optics",
    "rf_octupole_ion_optics",
)
HIGH_ORDER_PROJECT_IDS = PROJECT_IDS[1:]


class RuntimeProfileTests(unittest.TestCase):
    def _v3_campaign(self) -> dict[str, object]:
        campaign = json.loads(
            (REPO_ROOT / "common/multipole/campaigns/20260731__oatof_shield_terminal_h15_n100.json").read_text(
                encoding="utf-8-sig"
            )
        )
        experiment = next(
            item for item in campaign["experiments"] if item["experiment_id"] == "hex_segmented_oatof_terminal_h15_n100"
        )
        campaign["schema_version"] = 3
        campaign["campaign_id"] = "test_drive_variation_v3"
        campaign["design_variable_authorization"] = {
            "allowed_variable_ids": ["rf_amplitude", "rf_frequency"],
            "variable_limits": [
                {
                    "variable_id": "rf_amplitude",
                    "unit": "V",
                    "minimum": 139.81792,
                    "maximum": 169.179683,
                },
                {
                    "variable_id": "rf_frequency",
                    "unit": "Hz",
                    "minimum": 1_100_000.0,
                    "maximum": 1_210_000.0,
                },
            ],
        }
        campaign["particle_source_phase_policy"] = {
            "kind": "match_baseline_rf_phase",
            "baseline_frequency_Hz": 1_100_000.0,
            "frequency_variable_id": "rf_frequency",
            "n1000_reference_profile_id": "family_mother_sample_v1_n1000",
        }
        experiment["execution_profile_id"] = "simion_transport_campaign_engineering"
        experiment["design_variable_values"] = {
            "rf_amplitude": 153.799712,
            "rf_frequency": 1_210_000.0,
        }
        campaign["experiments"] = [experiment]
        return campaign

    def _resolve_campaign_document(self, campaign: dict[str, object]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            path.write_text(json.dumps(campaign), encoding="utf-8")
            with patch.object(runtime_profile, "_campaign_file", return_value=path):
                return resolve_campaign_experiment(
                    REPO_ROOT,
                    "rf_hexapole_ion_optics",
                    path,
                    "hex_segmented_oatof_terminal_h15_n100",
                )

    def test_campaign_v3_compiles_governed_drive_candidate(self) -> None:
        resolved = self._resolve_campaign_document(self._v3_campaign())
        design = resolved["design_profile_resolution"]
        self.assertEqual(design["profile"]["design_profile_id"], "segmented_rod_axial_acceleration")
        self.assertEqual(
            design["resolved_design"]["drive"]["rf_amplitude_V_zero_to_peak_per_group"],
            153.799712,
        )
        self.assertEqual(design["resolved_design"]["drive"]["frequency_Hz"], 1_210_000.0)
        self.assertEqual(
            set(design["campaign_design_variables"]["applied_values"]),
            {"rf_amplitude", "rf_frequency"},
        )
        self.assertEqual(
            design["candidate_request_sha256"],
            design["resolved_design"]["request"]["sha256"],
        )
        self.assertIn(
            "base_design_request",
            {item["label"] for item in design["resolved_design"]["sources"]},
        )
        self.assertNotIn(
            "design_request",
            {item["label"] for item in design["resolved_design"]["sources"]},
        )
        self.assertIn("downstream_terminal_profile", resolved)
        self.assertIn("downstream_terminal", design["resolved_design"])
        self.assertRegex(resolved["campaign"]["experiment_row_sha256"], r"^[A-F0-9]{64}$")
        self.assertRegex(
            resolved["campaign"]["design_variable_authorization_sha256"],
            r"^[A-F0-9]{64}$",
        )

    def test_phase_matched_n5000_requires_and_accepts_its_n1000_prefix(self) -> None:
        campaign = self._v3_campaign()
        campaign["particle_source_phase_policy"]["n1000_reference_profile_id"] = (
            "paper1_prospective_mother_sample_v1_n1000"
        )
        experiment = campaign["experiments"][0]
        experiment["particle_source_profile_id"] = "paper1_prospective_mother_sample_v1_n5000"
        resolved = self._resolve_campaign_document(campaign)
        derivation = resolved["particle_source_phase_derivation"]
        self.assertEqual(derivation["authority_particle_count"], 5000)
        self.assertEqual(
            derivation["n1000_reference_source"]["sha256"],
            "03DCEB7CCD763075696145CD370E9D14CA2FADAE86BA83370BAF7B171E13126D",
        )
        self.assertEqual(
            resolved["particle_source_phase_derivation"]["candidate_frequency_Hz"],
            1_210_000.0,
        )

    def test_source_model_campaign_allows_distinct_authority_only_with_same_cohort(self) -> None:
        campaign = REPO_ROOT / "common/multipole/campaigns/20260829__oct_planar_vs_volume_source_n1000.json"
        resolved = resolve_campaign_experiment(REPO_ROOT, "rf_octupole_ion_optics", campaign, "oct_volume_source_n1000")
        derivation = resolved["particle_source_phase_derivation"]
        self.assertEqual(
            derivation["n1000_authority_relationship"],
            "source_model_comparison_with_same_particle_ids",
        )
        self.assertEqual(derivation["authority_particle_count"], 1000)

    def test_prospective_paper1_s1_and_s2_campaigns_bind_independent_n5000_source(self) -> None:
        cases = (
            (
                "rf_octupole_ion_optics",
                "20260826__paper1_s1_prospective_octupole_source_n5000.json",
                "paper1_s1_prospective_octupole_source_n5000",
                "particle_source_derivation",
            ),
            (
                "rf_hexapole_ion_optics",
                "20260826__paper1_s2_prospective_segmented_source_n5000.json",
                "paper1_s2_prospective_segmented_source_n5000",
                "particle_source_phase_derivation",
            ),
        )
        for project_id, campaign_name, experiment_id, derivation_key in cases:
            with self.subTest(project_id=project_id):
                resolved = resolve_campaign_experiment(
                    REPO_ROOT,
                    project_id,
                    Path(campaign_name),
                    experiment_id,
                )
                self.assertEqual(
                    resolved["particle_source"]["profile_id"],
                    "paper1_prospective_mother_sample_v1_n5000",
                )
                self.assertEqual(resolved[derivation_key]["authority_particle_count"], 5000)
                self.assertEqual(resolved["case_set"], "primary_only")

    def test_campaign_v4_accepts_n1000_phase_matched_primary_only_row(self) -> None:
        resolved = resolve_campaign_experiment(
            REPO_ROOT,
            "rf_hexapole_ion_optics",
            Path("20260803__hex_rf_drive_phase_matched_h15_n1000.json"),
            "hex_rf_p0_n1000",
        )
        self.assertEqual(
            resolved["engineering_budget"]["inline_contract"]["pilot_authorization"]["scope"]["particle_count"],
            1000,
        )
        self.assertEqual(
            resolved["particle_source_phase_derivation"]["authority_particle_count"],
            1000,
        )
        self.assertEqual(
            resolved["simion_pa_basis_policy"]["kind"],
            "content_addressed_geometry_basis",
        )

    def test_campaign_binds_volume_snapshot_receipt_for_solver_preflight(self) -> None:
        resolved = resolve_campaign_experiment(
            REPO_ROOT,
            "rf_octupole_ion_optics",
            Path("20260829__oct_planar_vs_volume_source_n1000.json"),
            "oct_volume_source_n1000",
        )
        binding = resolved["particle_source"]["volume_snapshot_receipt"]
        self.assertEqual(
            resolved["particle_source"]["profile_id"],
            "continuous_axial_volume_snapshot_v1_n1000",
        )
        self.assertTrue(Path(binding["path"]).is_file())
        self.assertRegex(binding["sha256"], r"^[A-F0-9]{64}$")
        # The frozen planar arm is permitted to publish the one missing
        # geometry/basis seed; the volume-source arm must reuse it.
        self.assertFalse(resolved["simion_pa_basis_policy"].get("require_existing", False))

    def test_campaign_v5_binds_governed_n100_energy_transform_for_each_family(self) -> None:
        cases = (
            ("rf_quadrupole_ion_optics", "quad_noacc_5ev_h15_n100"),
            ("rf_hexapole_ion_optics", "hex_noacc_5ev_h15_n100"),
            ("rf_octupole_ion_optics", "oct_noacc_5ev_h15_n100"),
        )
        for project_id, experiment_id in cases:
            with self.subTest(project_id=project_id):
                resolved = resolve_campaign_experiment(
                    REPO_ROOT,
                    project_id,
                    Path("20260803__multipole_noacc_5ev_h15_n100.json"),
                    experiment_id,
                )
                derivation = resolved["particle_source_derivation"]
                self.assertEqual(derivation["target_kinetic_energy_eV"], 5.0)
                self.assertEqual(derivation["authority_particle_count"], 100)
                scope = resolved["engineering_budget"]["inline_contract"]["pilot_authorization"]["scope"]
                self.assertEqual(scope["particle_count"], 100)
                self.assertNotIn(
                    "campaign_design_variables",
                    resolved["design_profile_resolution"],
                )

    def test_campaign_v6_combines_source_transform_and_segment_voltage_variables(self) -> None:
        resolved = resolve_campaign_experiment(
            REPO_ROOT,
            "rf_octupole_ion_optics",
            Path("20260805__oct_segmented_10ev_h15.json"),
            "oct_segmented_10ev_h15_n100",
        )
        applied = resolved["design_profile_resolution"]["campaign_design_variables"]["applied_values"]
        self.assertEqual(
            {key: value["value"] for key, value in applied.items()},
            {
                "segment_entrance_common_mode": 8.0,
                "segment_exit_common_mode": 0.0,
                "segment_output_reference": 0.0,
            },
        )
        self.assertEqual(resolved["particle_source_derivation"]["target_kinetic_energy_eV"], 2.0)
        self.assertRegex(
            resolved["campaign"]["design_variable_authorization_sha256"],
            r"^[A-F0-9]{64}$",
        )
        self.assertRegex(
            resolved["campaign"]["particle_source_transform_policy_sha256"],
            r"^[A-F0-9]{64}$",
        )

    def test_campaign_v6_accepts_governed_rf_phase(self) -> None:
        resolved = resolve_campaign_experiment(
            REPO_ROOT,
            "rf_octupole_ion_optics",
            Path("20260811__oct_rf_phase_p90_h15_n1000.json"),
            "oct_rf_phase_p90_h15_n1000",
        )
        applied = resolved["design_profile_resolution"]["campaign_design_variables"]["applied_values"]
        self.assertEqual(applied["rf_phase"]["unit"], "rad")
        self.assertAlmostEqual(applied["rf_phase"]["value"], 1.5707963267948966)
        self.assertAlmostEqual(
            resolved["design_profile_resolution"]["resolved_design"]["drive"]["phase_rad"],
            1.5707963267948966,
        )

    def test_terminal_10ev_campaign_keeps_all_rods_at_eight_volts(self) -> None:
        resolved = resolve_campaign_experiment(
            REPO_ROOT,
            "rf_octupole_ion_optics",
            Path("20260805__oct_terminal_10ev_h15.json"),
            "oct_terminal_10ev_h15_n100",
        )
        design = resolved["design_profile_resolution"]["resolved_design"]
        segments = design["segmentation"]["axial_acceleration"]["derived"]["segments"]
        self.assertEqual(
            design["axial_drive"],
            {
                "topology": "exit_aperture_plate_potential_step",
                "source_reference_V": 8.0,
                "output_reference_V": 0.0,
                "predicted_energy_gain_eV": 8.0,
                "predicted_output_energy_eV": 10.0,
            },
        )
        self.assertEqual([segment["common_mode_V"] for segment in segments], [8.0] * 4)
        self.assertEqual(design["axial_dc"]["terminal_electrode_potential_V"], 0.0)

    def test_historical_campaign_v1_and_v2_remain_resolvable(self) -> None:
        cases = (
            (
                "20260731__noacc_vs_segmented_h15_n100.json",
                "rf_hexapole_ion_optics",
                "hex_segmented_h15_n100",
            ),
            (
                "20260731__oatof_shield_terminal_h15_n100.json",
                "rf_hexapole_ion_optics",
                "hex_segmented_oatof_terminal_h15_n100",
            ),
        )
        for filename, project_id, experiment_id in cases:
            with self.subTest(filename=filename):
                resolved = resolve_campaign_experiment(
                    REPO_ROOT,
                    project_id,
                    Path(filename),
                    experiment_id,
                )
                self.assertNotIn("campaign_design_variables", resolved["design_profile_resolution"])

    def test_campaign_v3_rejects_unauthorized_derived_and_out_of_range_values(self) -> None:
        derived = self._v3_campaign()
        derived["experiments"][0]["design_variable_values"] = {"rod_radius": 2.0}
        with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign"):
            self._resolve_campaign_document(derived)

        out_of_range = self._v3_campaign()
        out_of_range["experiments"][0]["design_variable_values"]["rf_frequency"] = 1_300_000.0
        with self.assertRaisesRegex(ValueError, "outside its narrow range"):
            self._resolve_campaign_document(out_of_range)

        missing_axis = self._v3_campaign()
        del missing_axis["experiments"][0]["design_variable_values"]["rf_frequency"]
        with self.assertRaisesRegex(ValueError, "keys differ from its authorization"):
            self._resolve_campaign_document(missing_axis)

    def test_campaign_v3_rejects_execution_profile_and_authority_mismatches(self) -> None:
        unsupported = self._v3_campaign()
        unsupported["experiments"][0]["execution_profile_id"] = "transport_no_collision_candidate"
        with self.assertRaisesRegex(ValueError, "execution profile is not unique"):
            self._resolve_campaign_document(unsupported)

        campaign = self._v3_campaign()
        design = runtime_profile.resolve_design_profile(
            REPO_ROOT,
            "rf_hexapole_ion_optics",
            "segmented_rod_axial_acceleration",
        )
        execution = runtime_profile._resolve_execution_profile(
            REPO_ROOT / "projects/rf_hexapole_ion_optics",
            "rf_hexapole_ion_optics",
            "simion_transport_campaign_engineering",
        )
        unsupported_execution = copy.deepcopy(execution)
        unsupported_execution["profile"]["supported_design_variables"].remove("rf_frequency")
        with patch.object(
            runtime_profile,
            "_resolve_execution_profile",
            return_value=unsupported_execution,
        ):
            with self.assertRaisesRegex(ValueError, "does not support design variable"):
                runtime_profile._compile_campaign_design_candidate(
                    REPO_ROOT,
                    "rf_hexapole_ion_optics",
                    campaign,
                    campaign["experiments"][0],
                    design,
                )

        wide_campaign = copy.deepcopy(campaign)
        wide_campaign["design_variable_authorization"]["variable_limits"][0]["maximum"] = 501.0
        with self.assertRaisesRegex(ValueError, "range exceeds catalog bounds"):
            runtime_profile._compile_campaign_design_candidate(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                wide_campaign,
                wide_campaign["experiments"][0],
                design,
            )

        original_load = runtime_profile._load

        def stale_envelope(path: Path) -> dict[str, object]:
            document = original_load(path)
            if Path(path) == design["paths"]["optimization_envelope"]:
                document = copy.deepcopy(document)
                document["reference"]["design_request_sha256"] = "0" * 64
            return document

        with patch.object(runtime_profile, "_load", side_effect=stale_envelope):
            with self.assertRaisesRegex(ValueError, "base request SHA-256 differs"):
                runtime_profile._compile_campaign_design_candidate(
                    REPO_ROOT,
                    "rf_hexapole_ion_optics",
                    campaign,
                    campaign["experiments"][0],
                    design,
                )

        wrong_identity = copy.deepcopy(design)
        wrong_identity["profile"] = copy.deepcopy(design["profile"])
        wrong_identity["profile"]["identity"] = copy.deepcopy(design["profile"]["identity"])
        wrong_identity["profile"]["identity"]["radial_order_n"] = 4
        with self.assertRaisesRegex(ValueError, "base design identity differs"):
            runtime_profile._compile_campaign_design_candidate(
                REPO_ROOT,
                "rf_hexapole_ion_optics",
                campaign,
                campaign["experiments"][0],
                wrong_identity,
            )

    def test_legacy_scalar_simion_cells_normalize_to_canonical_xyz(self) -> None:
        resolved = resolve_runtime_profile(
            REPO_ROOT,
            "rf_hexapole_ion_optics",
            "no_acceleration_full_length",
        )
        numerics = resolved["solver_numerics"]["simion"]["values"]
        self.assertNotIn("cell_mm", numerics)
        self.assertEqual(
            numerics["cell_mm_xyz"],
            {"x": 0.4, "y": 0.4, "z": 0.4},
        )

    def test_simion_cell_forms_are_mutually_exclusive_and_fail_closed(self) -> None:
        canonical = normalize_simion_solver_numerics(
            {
                "cell_mm_xyz": {"x": 0.2, "y": 0.3, "z": 0.4},
                "trajectory_quality": 10,
            }
        )
        self.assertEqual(
            canonical["cell_mm_xyz"],
            {"x": 0.2, "y": 0.3, "z": 0.4},
        )
        with self.assertRaisesRegex(ValueError, "exactly one"):
            normalize_simion_solver_numerics(
                {
                    "cell_mm": 0.4,
                    "cell_mm_xyz": {"x": 0.4, "y": 0.4, "z": 0.4},
                }
            )
        for invalid in (
            {"cell_mm_xyz": {"x": 0.2, "y": 0.3}},
            {"cell_mm_xyz": {"x": 0.2, "y": 0.3, "z": 0.0}},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_simion_solver_numerics(invalid)

    def test_release_source_profile_resolves_authority_without_sampling(self) -> None:
        from common.multipole.test_particle_source_preflight import planar_release_spec

        design = runtime_profile.resolve_design_profile(
            REPO_ROOT, "rf_octupole_ion_optics", "through_exit_no_acceleration"
        )["resolved_design"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "projects/rf_octupole_ion_optics"
            (project / "config").mkdir(parents=True)
            spec = project / "config/release.json"
            spec.write_text(json.dumps(planar_release_spec(design)), encoding="utf-8")
            registry = project / "config/particle_source_profiles.json"
            document = dict(
                schema_version=1,
                role="multipole_particle_source_profiles",
                project_id="rf_octupole_ion_optics",
                profiles={"new_source": {"release_spec": "config/release.json"}},
            )
            registry.write_text(json.dumps(document), encoding="utf-8")
            with patch(
                "common.ion_release.mt19937_disk_cone_rf_phase.generate_mt19937_disk_cone_rf_phase_states",
                side_effect=AssertionError("resolution sampled"),
            ):
                value = runtime_profile._resolve_particle_source(
                    root, project, "rf_octupole_ion_optics", "new_source", resolved=design
                )
            self.assertEqual(value["particle_count"], 100)
            self.assertNotIn("path", value)
            self.assertEqual(value["release_spec"]["path"], str(spec.resolve()))
            self.assertFalse((project / "config/release.csv").exists())
            with self.assertRaisesRegex(ValueError, "campaign transforms"):
                runtime_profile._resolve_particle_source(root, project, "rf_octupole_ion_optics", "new_source")
            document["profiles"]["new_source"]["path"] = "unused.csv"
            registry.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "keys differ"):
                runtime_profile._resolve_particle_source(
                    root, project, "rf_octupole_ion_optics", "new_source", resolved=design
                )

    def test_multipole_family_profiles_freeze_one_shared_source(self) -> None:
        resolved = [
            resolve_runtime_profile(
                REPO_ROOT,
                project_id,
                "no_acceleration_full_length",
            )
            for project_id in PROJECT_IDS
        ]
        self.assertEqual(
            {item["particle_source"]["sha256"] for item in resolved},
            {"0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F"},
        )
        self.assertEqual(
            {item["particle_source"]["path"] for item in resolved},
            {str((REPO_ROOT / "common/multipole/sources/rf_multipole_family_mother_sample_v1_100.csv").resolve())},
        )

    def test_project_wrappers_expose_profile_identity_not_free_parameters(self) -> None:
        forbidden = (
            "[string]$ParticleSourcePath",
            "[int]$MeshAutoLevel",
            "[double]$CellMm",
            "[int]$RfStepsPerPeriod",
            "[int]$TrajectoryQuality",
            "[double]$MaximumTimeUs",
            "[string]$TemplateIob",
        )
        for project_id in HIGH_ORDER_PROJECT_IDS:
            for name in (
                "run_finite_3d_transport.ps1",
                "run_simion_finite_3d_transport.ps1",
            ):
                source = (REPO_ROOT / "projects" / project_id / "analysis" / name).read_text(encoding="utf-8-sig")
                self.assertIn("[string]$RuntimeProfileId", source)
                for token in forbidden:
                    self.assertNotIn(token, source)

    def test_registration_identity_comes_from_all_design_profiles(self) -> None:
        for project_id in PROJECT_IDS:
            project_root = REPO_ROOT / "projects" / project_id
            descriptor = json.loads((project_root / "config/project.json").read_text(encoding="utf-8-sig"))
            self.assertIsNone(descriptor["contracts"]["baseline"])
            profiles = json.loads(
                (project_root / descriptor["contracts"]["design_profiles"]).read_text(encoding="utf-8-sig")
            )
            identities = {json.dumps(profile["identity"], sort_keys=True) for profile in profiles["profiles"]}
            self.assertEqual(len(identities), 1)
            identity = json.loads(next(iter(identities)))
            self.assertEqual(identity["project_id"], descriptor["project_id"])
            self.assertEqual(identity["family_id"], descriptor["family_id"])
            self.assertEqual(
                identity["electrode_count"],
                2 * identity["radial_order_n"],
            )
        for project_id in HIGH_ORDER_PROJECT_IDS:
            for wrapper in (
                "run_finite_3d_transport.ps1",
                "run_simion_finite_3d_transport.ps1",
            ):
                source = (REPO_ROOT / "projects" / project_id / "analysis" / wrapper).read_text(encoding="utf-8-sig")
                self.assertNotIn("config\\baseline.json", source)

    def test_runtime_registry_is_read_once_and_rejects_nontext_paths(self) -> None:
        project = "rf_hexapole_ion_optics"
        path = REPO_ROOT / "projects" / project / "config/runtime_profiles.json"
        original_load = runtime_profile._load
        for value in (None, 123, [], True, "config/comsol_solver_numerics.json"):
            calls = []

            def load(selected: Path) -> dict:
                document = original_load(selected)
                if selected == path:
                    calls.append(selected)
                    document["solver_numerics_registry_paths"] = {"comsol": value}
                return document

            with self.subTest(value=value), patch.object(runtime_profile, "_load", side_effect=load):
                if isinstance(value, str):
                    resolve_runtime_profile(REPO_ROOT, project, "no_acceleration_full_length")
                else:
                    with self.assertRaisesRegex(ValueError, "registry path is invalid"):
                        resolve_runtime_profile(REPO_ROOT, project, "no_acceleration_full_length")
                self.assertEqual(len(calls), 1)

    def test_particle_source_hash_is_read_once_and_stale_identity_is_rejected(self) -> None:
        source = REPO_ROOT / "common/multipole/sources/rf_multipole_family_mother_sample_v1_100.csv"
        original = runtime_profile._sha256
        with patch.object(runtime_profile, "_sha256", wraps=original) as hashed:
            resolved = resolve_runtime_profile(REPO_ROOT, "rf_hexapole_ion_optics", "no_acceleration_full_length")
        self.assertEqual(sum(call.args[0] == source for call in hashed.call_args_list), 1)
        self.assertEqual(resolved["particle_source"]["sha256"], original(source))
        with patch.object(
            runtime_profile, "_sha256", side_effect=lambda path: "0" * 64 if path == source else original(path)
        ):
            with self.assertRaisesRegex(ValueError, "particle-source SHA-256 differs"):
                resolve_runtime_profile(REPO_ROOT, "rf_hexapole_ion_optics", "no_acceleration_full_length")

    def test_unknown_runtime_profile_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
            resolve_runtime_profile(REPO_ROOT, "rf_hexapole_ion_optics", "not-a-profile")

    def test_runtime_stop_stage_is_explicit_or_normalized_to_transport(self) -> None:
        normal = resolve_runtime_profile(
            REPO_ROOT,
            "rf_hexapole_ion_optics",
            "no_acceleration_full_length",
        )
        self.assertEqual(normal["stop_stage"], "transport")
        registry_path = REPO_ROOT / "projects/rf_hexapole_ion_optics/config/runtime_profiles.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
        special_profiles = [
            profile
            for profile in registry["profiles"].values()
            if profile.get("stop_stage", "transport") != "transport"
        ]
        for profile in special_profiles:
            self.assertIn(profile["stop_stage"], {"mesh_build", "field_solve"})

    def test_quadrupole_uses_the_same_governed_runtime_chain(self) -> None:
        resolved = resolve_runtime_profile(
            REPO_ROOT,
            "rf_quadrupole_ion_optics",
            "no_acceleration_full_length",
        )
        self.assertEqual(
            resolved["design_profile_id"],
            "no_acceleration_full_length",
        )
        self.assertEqual(
            resolved["particle_source"]["sha256"],
            "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
        )
        for name in ("run_comsol.ps1", "run_simion.ps1"):
            source = (
                REPO_ROOT / "projects/rf_quadrupole_ion_optics/workflows/no_collision_transport" / name
            ).read_text(encoding="utf-8-sig")
            self.assertIn("[string]$RuntimeProfileId", source)
            self.assertNotIn("[string]$ParticleSourcePath", source)

    def test_hybrid_profiles_bind_their_separate_campaign_budget(self) -> None:
        for project_id in (
            "rf_quadrupole_ion_optics",
            "rf_octupole_ion_optics",
        ):
            baseline = resolve_runtime_profile(
                REPO_ROOT,
                project_id,
                "no_acceleration_full_length",
            )
            hybrid = resolve_runtime_profile(
                REPO_ROOT,
                project_id,
                ("no_acceleration_full_length_n100_hybrid_exit025_temporal_refined"),
            )
            self.assertTrue(baseline["engineering_budget"]["path"].endswith("engineering_budget.json"))
            self.assertIn(
                "comsol_hybrid_no_acceleration_particle_convergence_budget",
                hybrid["engineering_budget"]["path"],
            )
            self.assertNotEqual(
                baseline["engineering_budget"]["path"],
                hybrid["engineering_budget"]["path"],
            )


class DownstreamTerminalRegistryTests(unittest.TestCase):
    """Exercise discovery paths and explicit owner identity without solver assets."""

    def _write_registry(self, repo: Path, root: str) -> tuple[dict, dict, Path]:
        profile = {
            "terminal_profile_id": "test_terminal",
            "owner": "downstream",
            "surface_role": "aperture_outer_tangent_plane",
            "rod_end_clearance_mm": 1,
            "upstream_enclosure_end_plane_binding": "interfaces_mm.exit.aperture_plate_upstream_face_z_mm",
            "electrode_thickness_mm": 1,
            "outer_envelope": {"shape": "rectangular", "width_mm": 10, "height_mm": 10},
            "aperture": {"shape": "circular", "radius_mm": 2},
            "upstream_entrance_reference_sleeve": {
                "profile_id": "source_reference_sleeve_v1",
                "potential_binding": "segmentation.entrance_common_mode_V",
                "inner_radius_mm": 2,
                "outer_radius_mm": 3,
                "minimum_insulation_gap_mm": 1,
                "downstream_rod_clearance_mm": 0,
            },
            "terminal_potential_V": 0,
        }
        registry = {
            "schema_version": 1,
            "role": "multipole_downstream_terminal_profile_registry",
            "integration_id": "instrument_assembly",
            "compatible_upstream_family_id": "rf_multipole_ion_optics",
            "allowed_upstream_project_ids": ["rf_hexapole_ion_optics"],
            "profiles": [profile],
        }
        relative = f"{root}/config/terminals.json"
        path = repo / relative
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(registry), encoding="utf-8")
        discovery = {
            "schema_version": 1,
            "role": "integration_registry",
            "integrations": [
                {
                    "integration_id": registry["integration_id"],
                    "root": root,
                    "profile_registry": f"{root}/config/connections.json",
                    "downstream_terminal_profile_registry": relative,
                }
            ],
        }
        (repo / "integrations/registry.json").write_text(json.dumps(discovery), encoding="utf-8")
        binding = {
            "integration_id": registry["integration_id"],
            "terminal_profile_id": profile["terminal_profile_id"],
            "registry_sha256": runtime_profile._sha256(path),
        }
        return discovery, binding, path

    def test_repository_terminal_campaigns_resolve_without_legacy_family_registration(self) -> None:
        discovery_path = REPO_ROOT / "integrations/registry.json"
        discovery = runtime_profile._load(discovery_path)
        direct = [row for row in discovery["integrations"] if row["integration_id"] == "instrument_assembly"]
        self.assertEqual(len(direct), 1)
        catalog = REPO_ROOT / "integrations/config/downstream_terminal_profiles.json"
        self.assertEqual(direct[0]["downstream_terminal_profile_registry"], catalog.relative_to(REPO_ROOT).as_posix())
        legacy = REPO_ROOT / "integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/downstream_terminal_profiles.json"
        self.assertFalse(legacy.exists())
        discovery["integrations"] = direct
        load = runtime_profile._load

        def current_only(path):
            return discovery if path == discovery_path else load(path)

        bindings = [runtime_profile._load(path)["downstream_terminal_profile"]
                    for path in sorted((REPO_ROOT / "common/multipole/campaigns").glob("*.json"))
                    if "downstream_terminal_profile" in runtime_profile._load(path)]
        self.assertTrue(bindings)
        with patch.object(runtime_profile, "_load", side_effect=current_only):
            for binding in bindings:
                with self.subTest(binding=binding):
                    resolved = runtime_profile._resolve_downstream_terminal_profile(REPO_ROOT, binding)
                    self.assertEqual(resolved["integration_id"], "instrument_assembly")
                    self.assertEqual(Path(resolved["registry_path"]), catalog)
                    self.assertEqual(resolved["profile"]["terminal_profile_id"], "oatof_shield_terminal")

    def test_retired_family_is_not_a_terminal_discovery_fallback(self) -> None:
        binding = dict(integration_id="rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer",
            terminal_profile_id="oatof_shield_terminal", registry_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "integration identity is not unique"):
            runtime_profile._resolve_downstream_terminal_profile(REPO_ROOT, binding)


    def test_direct_and_family_roots_resolve_owner_from_explicit_identity(self) -> None:
        for root in ("integrations", "integrations/active_family"):
            with self.subTest(root=root), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory).resolve()
                _, binding, path = self._write_registry(repo, root)
                resolved = runtime_profile._resolve_downstream_terminal_profile(repo, binding)
                self.assertEqual(resolved["integration_id"], "instrument_assembly")
                self.assertEqual(Path(resolved["registry_path"]), path)
                self.assertEqual(resolved["profile"]["terminal_profile_id"], "test_terminal")

    def test_terminal_registry_path_must_match_the_declared_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            discovery, binding, _ = self._write_registry(repo, "integrations/active_family")
            discovery["integrations"][0]["downstream_terminal_profile_registry"] = (
                "integrations/another_family/config/profiles.json"
            )
            (repo / "integrations/registry.json").write_text(json.dumps(discovery), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from its declared root"):
                runtime_profile._resolve_downstream_terminal_profile(repo, binding)

    def test_terminal_consumer_requires_only_its_own_registered_capability(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            discovery, binding, path = self._write_registry(repo, "integrations")
            del discovery["integrations"][0]["profile_registry"]
            (repo / "integrations/registry.json").write_text(json.dumps(discovery), encoding="utf-8")
            resolved = runtime_profile._resolve_downstream_terminal_profile(repo, binding)
            self.assertEqual(Path(resolved["registry_path"]), path)

    def test_resolved_registry_path_cannot_escape_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            _, binding, path = self._write_registry(repo, "integrations")
            original_resolve = Path.resolve

            def resolve(candidate: Path, *args, **kwargs) -> Path:
                if candidate == path:
                    return repo / "outside/terminals.json"
                return original_resolve(candidate, *args, **kwargs)

            with patch.object(Path, "resolve", resolve):
                with self.assertRaisesRegex(ValueError, "escapes its declared root"):
                    runtime_profile._resolve_downstream_terminal_profile(repo, binding)

    def test_terminal_registry_still_rejects_wrong_owner_and_frozen_hash(self) -> None:
        for change in ("owner", "hash"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory).resolve()
                _, binding, path = self._write_registry(repo, "integrations")
                if change == "owner":
                    registry = json.loads(path.read_text(encoding="utf-8"))
                    registry["integration_id"] = "different_owner"
                    path.write_text(json.dumps(registry), encoding="utf-8")
                    binding["registry_sha256"] = runtime_profile._sha256(path)
                    message = "registry identity differs"
                else:
                    binding["registry_sha256"] = "0" * 64
                    message = "SHA-256 differs"
                with self.assertRaisesRegex(ValueError, message):
                    runtime_profile._resolve_downstream_terminal_profile(repo, binding)


if __name__ == "__main__":
    unittest.main()

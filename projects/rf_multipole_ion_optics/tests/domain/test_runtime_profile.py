from __future__ import annotations

import copy
import json
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from projects.rf_multipole_ion_optics.runtime import runtime_profile
from projects.rf_multipole_ion_optics.runtime.runtime_profile import (
    resolve_campaign_experiment,
    resolve_execution_binding,
    resolve_runtime_profile,
)
from projects.rf_multipole_ion_optics.runtime.simion_numerics import normalize_simion_solver_numerics


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT_ID = "rf_multipole_ion_optics"
VARIANTS = ("quadrupole", "hexapole", "octupole")


class RuntimeProfileTests(unittest.TestCase):
    def test_comsol_minimum_size_is_authorized_numeric_and_selected_region_only(self):
        from projects.rf_multipole_ion_optics.runtime.runtime_profile import _resolve_solver_profile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"numerics.json"
            registry = dict(schema_version=1, role="multipole_comsol_solver_numerics_profiles", project_id="fixture",
                            profiles=dict(inert=dict(mesh=dict(global_auto_level=9, working_region_maximum_element_size_mm=2,
                                                              minimum_element_size_mm=.2))))
            path.write_text(json.dumps(registry), encoding="utf-8")
            self.assertEqual(_resolve_solver_profile(path, "fixture", "comsol", "inert")["values"], registry["profiles"]["inert"])
            for value in (True, 0, -1, 3, float("inf"), float("nan"), ".2"):
                with self.subTest(minimum=value):
                    registry["profiles"]["inert"]["mesh"]["minimum_element_size_mm"] = value
                    path.write_text(json.dumps(registry), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "minimum_element_size_mm"):
                        _resolve_solver_profile(path, "fixture", "comsol", "inert")
            registry["profiles"]["inert"]["mesh"].update(minimum_element_size_mm=.2, strategy="physical_segment_hybrid_swept_tetra_v1")
            path.write_text(json.dumps(registry), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "minimum_element_size_mm"):
                _resolve_solver_profile(path, "fixture", "comsol", "inert")

    def test_comsol_prepare_consumes_resolved_design_without_resolving_live_profiles(self) -> None:
        runtime = resolve_runtime_profile(REPO_ROOT, PROJECT_ID, "quadrupole_no_acceleration_full_length")
        for key in runtime["design_profile_resolution"]["paths"]:
            runtime["design_profile_resolution"]["paths"][key] = "must-not-read-current-default.json"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root/"runtime.json"
            snapshot.write_text(json.dumps(runtime))
            script = root/"prepare.ps1"
            script.write_text(r"""param($Repo,$Entry,$Snapshot,$Root)
Set-StrictMode -Version Latest;$ErrorActionPreference='Stop'
. (Join-Path $Repo 'common/contracts/run_artifact_support.ps1')
$ast=[Management.Automation.Language.Parser]::ParseFile($Entry,[ref]$null,[ref]$null)
$select=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.Contains('Compiled COMSOL runtime identity differs.')},$true)
$inputs=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Extent.Text.Contains('Compiled COMSOL runtime omits its resolved design input definitions.')},$true)
$resolvedBlock=$ast.Find({param($n)$n-is[Management.Automation.Language.IfStatementAst]-and$n.Clauses[0].Item1.Extent.Text-eq'$null-ne$compiledRuntime'-and$n.Extent.Text.Contains('-Value $compiledRuntime.design_profile_resolution.resolved_design')},$true)
$ResolvedRuntimeProfilePath=$Snapshot;$compiledRuntime=$null
$frozen=Get-Content $Snapshot -Raw|ConvertFrom-Json -Depth 100
$ProjectId=$frozen.project_id;$RuntimeProfileId=$frozen.runtime_profile_id;$DesignProfileId=$frozen.design_profile_id
$profileResolution=Join-Path $Root 'profile.json';$request=Join-Path $Root 'request.json';$variables=Join-Path $Root 'variables.json';$envelope=Join-Path $Root 'envelope.json';$resolved=Join-Path $Root 'resolved.json'
if($null-eq$select-or$null-eq$inputs-or$null-eq$resolvedBlock){throw 'COMSOL preparation consumer is missing'}
Invoke-Expression $select.Extent.Text
$profile=Get-Content $profileResolution -Raw|ConvertFrom-Json -Depth 100
Invoke-Expression $inputs.Extent.Text
Invoke-Expression $resolvedBlock.Extent.Text
'COMSOL_RESOLVED_INPUTS=PASS'
""", encoding="utf-8")
            completed = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(script), str(REPO_ROOT),
                str(REPO_ROOT/"projects"/PROJECT_ID/"runtime/run_finite_3d_transport.ps1"), str(snapshot), str(root)],
                cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout+completed.stderr)
            self.assertEqual(json.loads((root/"resolved.json").read_text()), runtime["design_profile_resolution"]["resolved_design"])
            for name, file in (("design_request", "request"), ("design_variables", "variables"), ("optimization_envelope", "envelope")):
                self.assertEqual(json.loads((root/(file+".json")).read_text()), runtime["design_profile_resolution"]["input_definitions"][name])

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 required")
    def test_public_wrappers_pass_one_resolved_runtime_without_reselecting_defaults(self) -> None:
        runtime = resolve_runtime_profile(REPO_ROOT, PROJECT_ID, "quadrupole_no_acceleration_full_length")
        runtime["solver_numerics"]["comsol"]["values"]["trajectory"]["maximum_global_time_us"] = 23
        runtime["solver_numerics"]["simion"]["values"]["trajectory"]["maximum_global_time_us"] = 29
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root/"projects"/PROJECT_ID
            (project/"runtime").mkdir(parents=True)
            (project/"workflows/no_collision_transport").mkdir(parents=True)
            shutil.copyfile(REPO_ROOT/"projects"/PROJECT_ID/"runtime/project_transport_launcher_support.ps1", project/"runtime/project_transport_launcher_support.ps1")
            snapshot = root/"runtime.json"
            snapshot.write_text(json.dumps(runtime))
            stub = r"""param($ProjectId,$RuntimeProfileId,$DesignProfileId,$ParticleSourcePath,$EngineeringBudgetPath,$RunId,
$RetentionClass,$RetentionReason,$PythonExe,$RfStepsPerPeriod,$MaximumTimeUs,$ResolvedRuntimeProfilePath,
$EvidenceContractPath,$StopStage,$MeshAutoLevel,$WorkingRegionMaximumElementSizeMm,$ReferenceComsolRunId,
$CellMmX,$CellMmY,$CellMmZ,$TrajectoryQuality,$CaseSet)
$ErrorActionPreference='Stop'
$profile=Get-Content $ResolvedRuntimeProfilePath -Raw|ConvertFrom-Json
@{id=$profile.runtime_profile_id;time=$MaximumTimeUs;run=$RunId;resolved=$profile.design_profile_resolution.resolved_design.resolved_sha256}|
 ConvertTo-Json|Set-Content (Join-Path $PSScriptRoot ([IO.Path]::GetFileNameWithoutExtension($PSCommandPath)+'.json'))
$global:LASTEXITCODE=0
"""
            for solver, native, expected in (("comsol", "run_finite_3d_transport", 23), ("simion", "run_simion_finite_3d_transport", 29)):
                with self.subTest(solver=solver):
                    wrapper = project/"workflows/no_collision_transport"/("run_"+solver+".ps1")
                    shutil.copyfile(REPO_ROOT/"projects"/PROJECT_ID/"workflows/no_collision_transport"/wrapper.name, wrapper)
                    (project/"runtime"/(native+".ps1")).write_text(stub, encoding="utf-8")
                    result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(wrapper),
                        "-ResolvedRuntimeProfilePath", str(snapshot), "-RunId", "20261030_123000__sim__simion__resolved-wrapper",
                        "-PythonExe", str(root/"python-must-not-start.exe")], cwd=root,
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                    actual = json.loads((project/"runtime"/(native+".json")).read_text())
                    self.assertEqual(actual["id"], runtime["runtime_profile_id"])
                    self.assertEqual(actual["time"], expected)
                    self.assertEqual(actual["resolved"], runtime["design_profile_resolution"]["resolved_design"]["resolved_sha256"])
                    self.assertEqual(actual["run"], "20261030_123000__sim__simion__resolved-wrapper")

    def test_execution_binding_projects_each_actual_structure_without_run_authorization(self) -> None:
        for variant in VARIANTS:
            with self.subTest(variant=variant):
                result = resolve_execution_binding(REPO_ROOT, PROJECT_ID, {
                    "runtime_profile_id": variant + "_no_acceleration_full_length",
                })
                frozen = result.pop("resolved_runtime")
                self.assertEqual(frozen["runtime_profile_id"], variant + "_no_acceleration_full_length")
                self.assertEqual(result, {"project_id": PROJECT_ID, "structural_variant_id": variant,
                                          "authorized_run_id": None,
                                          "tools": ["comsol", "matlab", "simion", "python"]})

    def test_execution_binding_projects_the_campaign_owned_run_identity(self) -> None:
        path = REPO_ROOT / "projects/rf_multipole_ion_optics/config/campaigns/20260731__noacc_vs_segmented_h15_n100.json"
        for variant, short in (("hexapole", "hex"), ("octupole", "oct")):
            experiment_id = short + "_segmented_h15_n100"
            runtime = resolve_campaign_experiment(REPO_ROOT, PROJECT_ID, path, experiment_id)
            with self.subTest(variant=variant):
                self.assertIs(runtime["engineering_budget"]["inline_contract"]["pilot_authorization"]["authorized"], False)
                self.assertEqual(resolve_execution_binding(REPO_ROOT, PROJECT_ID, {
                    "campaign_path": str(path), "experiment_id": experiment_id,
                }), {
                    "project_id": PROJECT_ID, "structural_variant_id": variant,
                    "authorized_run_id": runtime["engineering_budget"]["inline_contract"]["pilot_authorization"]["scope"]["authorized_run_id"],
                })

    def test_execution_binding_rejects_incomplete_mixed_and_extra_selectors(self) -> None:
        for bindings in ({}, {"campaign_path": "campaign.json"}, {"experiment_id": "experiment"},
                         {"runtime_profile_id": "profile", "campaign_path": "campaign.json", "experiment_id": "experiment"},
                         {"runtime_profile_id": "profile", "authorized_run_id": "forged"}):
            with self.subTest(bindings=bindings), self.assertRaisesRegex(ValueError, "execution binding requires"):
                resolve_execution_binding(REPO_ROOT, PROJECT_ID, bindings)

    def _current_campaign(self) -> dict[str, object]:
        campaign = json.loads(
            (REPO_ROOT / "projects/rf_multipole_ion_optics/config/campaigns/20260731__noacc_vs_segmented_h15_n100.json").read_text(
                encoding="utf-8-sig"
            )
        )
        experiment = next(
            item for item in campaign["experiments"] if item["experiment_id"] == "hex_segmented_h15_n100"
        )
        campaign["schema_version"] = 7
        campaign["campaign_id"] = "test_drive_variation"
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
        experiment["execution_profile_id"] = "hexapole_simion_transport_campaign_engineering"
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
                    "rf_multipole_ion_optics",
                    path,
                    "hex_segmented_h15_n100",
                )

    def test_campaign_compiles_governed_drive_candidate(self) -> None:
        resolved = self._resolve_campaign_document(self._current_campaign())
        design = resolved["design_profile_resolution"]
        self.assertEqual(design["profile"]["design_profile_id"], "hexapole_segmented_rod_axial_acceleration")
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
        self.assertNotIn("downstream_terminal_profile", resolved)
        self.assertNotIn("downstream_terminal", design["resolved_design"])
        self.assertRegex(resolved["campaign"]["experiment_row_sha256"], r"^[A-F0-9]{64}$")
        self.assertRegex(
            resolved["campaign"]["design_variable_authorization_sha256"],
            r"^[A-F0-9]{64}$",
        )

    def test_phase_matched_n5000_requires_and_accepts_its_n1000_prefix(self) -> None:
        campaign = self._current_campaign()
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

    def test_campaign_accepts_phase_matched_primary_only_row(self) -> None:
        campaign = self._current_campaign()
        campaign["experiments"][0]["particle_source_profile_id"] = "family_mother_sample_v1_n1000"
        campaign["experiments"][0]["case_set"] = "primary_only"
        campaign["simion_pa_basis_policy"] = {"kind": "content_addressed_geometry_basis", "reuse_scope": "same_project_same_fingerprint"}
        resolved = self._resolve_campaign_document(campaign)
        self.assertEqual(resolved["particle_source_phase_derivation"]["authority_particle_count"], 1000)
        self.assertEqual(resolved["case_set"], "primary_only")
        self.assertEqual(resolved["simion_pa_basis_policy"], campaign["simion_pa_basis_policy"])

    def test_volume_source_binds_receipt_for_solver_preflight(self) -> None:
        source = runtime_profile._resolve_particle_source(
            REPO_ROOT, REPO_ROOT / "projects" / PROJECT_ID, PROJECT_ID,
            "octupole_continuous_axial_volume_snapshot_v1_n1000",
        )
        binding = source["volume_snapshot_receipt"]
        self.assertTrue(Path(binding["path"]).is_file())
        self.assertRegex(binding["sha256"], r"^[A-F0-9]{64}$")

    def test_campaign_binds_declared_energy_transform(self) -> None:
        campaign = self._current_campaign()
        del campaign["particle_source_phase_policy"]
        campaign["particle_source_transform_policy"] = {
            "kind": "preserve_phase_position_direction_and_scale_energy",
            "rf_frequency_Hz": 1_210_000.0,
            "n1000_reference_profile_id": "family_mother_sample_v1_n1000",
        }
        campaign["simion_pa_basis_policy"] = {"kind": "content_addressed_geometry_basis", "reuse_scope": "same_project_same_fingerprint"}
        campaign["experiments"][0]["source_kinetic_energy_eV"] = 5.0
        resolved = self._resolve_campaign_document(campaign)
        self.assertEqual(resolved["particle_source_derivation"]["target_kinetic_energy_eV"], 5.0)
        self.assertEqual(resolved["particle_source_derivation"]["authority_particle_count"], 100)

    def test_campaign_rejects_two_source_transformation_policies(self) -> None:
        campaign = self._current_campaign()
        campaign["particle_source_transform_policy"] = {
            "kind": "preserve_phase_position_direction_and_scale_energy",
            "rf_frequency_Hz": 1_210_000.0,
            "n1000_reference_profile_id": "family_mother_sample_v1_n1000",
        }
        campaign["simion_pa_basis_policy"] = {"kind": "content_addressed_geometry_basis", "reuse_scope": "same_project_same_fingerprint"}
        campaign["experiments"][0]["source_kinetic_energy_eV"] = 5.0
        with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign"):
            self._resolve_campaign_document(campaign)

    def test_new_campaigns_reject_retired_versions_and_terminal_binding(self) -> None:
        for version in range(1, 7):
            campaign = self._current_campaign()
            campaign["schema_version"] = version
            with self.subTest(version=version), self.assertRaisesRegex(
                ValueError, "invalid multipole transport campaign"
            ):
                self._resolve_campaign_document(campaign)
        campaign = self._current_campaign()
        campaign["downstream_terminal_profile"] = {
            "integration_id": "instrument_assembly", "terminal_profile_id": "retired", "registry_sha256": "0" * 64,
        }
        with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign"):
            self._resolve_campaign_document(campaign)

    def test_campaign_rejects_unauthorized_derived_and_out_of_range_values(self) -> None:
        derived = self._current_campaign()
        derived["experiments"][0]["design_variable_values"] = {"rod_radius": 2.0}
        with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign"):
            self._resolve_campaign_document(derived)

        out_of_range = self._current_campaign()
        out_of_range["experiments"][0]["design_variable_values"]["rf_frequency"] = 1_300_000.0
        with self.assertRaisesRegex(ValueError, "outside its narrow range"):
            self._resolve_campaign_document(out_of_range)

        missing_axis = self._current_campaign()
        del missing_axis["experiments"][0]["design_variable_values"]["rf_frequency"]
        with self.assertRaisesRegex(ValueError, "keys differ from its authorization"):
            self._resolve_campaign_document(missing_axis)

    def test_campaign_execution_profile_resolves_only_the_designated_runner(self) -> None:
        project_root = REPO_ROOT / "projects" / PROJECT_ID
        registry_path = project_root / "config" / "execution_profiles.json"
        original_load = runtime_profile._load
        paths = (
            ("runtime/run_simion_transport_campaign.ps1", True),
            ("runtime/../runtime/run_simion_transport_campaign.ps1", True),
            ("../../projects/rf_multipole_ion_optics/runtime/run_simion_transport_campaign.ps1", True),
            ("other/runtime/run_simion_transport_campaign.ps1", False),
            ("../orthogonal_accelerator/runtime/run_simion_transport_campaign.ps1", False),
            ("other/projects/rf_multipole_ion_optics/runtime/run_simion_transport_campaign.ps1", False),
        )
        for entrypoint, accepted in paths:
            with self.subTest(entrypoint=entrypoint):
                registry = original_load(registry_path)
                profile = next(
                    item for item in registry["profiles"]
                    if item["profile_id"] == "hexapole_simion_transport_campaign_engineering"
                )
                run = next(item for item in profile["steps"] if item["kind"] == "run")
                run["entrypoint"] = entrypoint

                def changed_registry(path: Path) -> dict[str, object]:
                    return registry if path == registry_path else original_load(path)

                with patch.object(runtime_profile, "_load", side_effect=changed_registry):
                    if accepted:
                        result = runtime_profile._resolve_execution_profile(
                            project_root, PROJECT_ID, profile["profile_id"],
                            structural_variant_id="hexapole",
                        )
                        self.assertEqual(result["profile"]["steps"], profile["steps"])
                    else:
                        with self.assertRaisesRegex(ValueError, "governed SIMION campaign engineering workflow"):
                            runtime_profile._resolve_execution_profile(
                                project_root, PROJECT_ID, profile["profile_id"],
                                structural_variant_id="hexapole",
                            )

    def test_campaign_rejects_execution_profile_and_authority_mismatches(self) -> None:
        unsupported = self._current_campaign()
        unsupported["experiments"][0]["execution_profile_id"] = "transport_no_collision_candidate"
        with self.assertRaisesRegex(ValueError, "execution profile is not unique"):
            self._resolve_campaign_document(unsupported)

        campaign = self._current_campaign()
        design = runtime_profile.resolve_design_profile(
            REPO_ROOT,
            "rf_multipole_ion_optics",
            "hexapole_segmented_rod_axial_acceleration",
        )
        execution = runtime_profile._resolve_execution_profile(
            REPO_ROOT / "projects/rf_multipole_ion_optics",
            "rf_multipole_ion_optics",
            "hexapole_simion_transport_campaign_engineering",
            structural_variant_id="hexapole",
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
                    "rf_multipole_ion_optics",
                    campaign,
                    campaign["experiments"][0],
                    design,
                )

        wide_campaign = copy.deepcopy(campaign)
        wide_campaign["design_variable_authorization"]["variable_limits"][0]["maximum"] = 501.0
        with self.assertRaisesRegex(ValueError, "range exceeds catalog bounds"):
            runtime_profile._compile_campaign_design_candidate(
                REPO_ROOT,
                "rf_multipole_ion_optics",
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
                    "rf_multipole_ion_optics",
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
                "rf_multipole_ion_optics",
                campaign,
                campaign["experiments"][0],
                wrong_identity,
            )

    def test_legacy_scalar_simion_cells_normalize_to_canonical_xyz(self) -> None:
        resolved = resolve_runtime_profile(
            REPO_ROOT,
            "rf_multipole_ion_optics",
            "hexapole_no_acceleration_full_length",
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
        from projects.rf_multipole_ion_optics.tests.domain.test_particle_source_preflight import planar_release_spec

        design = runtime_profile.resolve_design_profile(
            REPO_ROOT, "rf_multipole_ion_optics", "octupole_no_acceleration_full_length"
        )["resolved_design"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "projects/rf_multipole_ion_optics"
            (project / "config").mkdir(parents=True)
            spec = project / "config/release.json"
            spec.write_text(json.dumps(planar_release_spec(design)), encoding="utf-8")
            registry = project / "config/particle_source_profiles.json"
            document = dict(
                schema_version=1,
                role="multipole_particle_source_profiles",
                project_id="rf_multipole_ion_optics",
                profiles={"new_source": {"release_spec": "config/release.json"}},
            )
            registry.write_text(json.dumps(document), encoding="utf-8")
            with patch(
                "common.ion_release.mt19937_disk_cone_rf_phase.generate_mt19937_disk_cone_rf_phase_states",
                side_effect=AssertionError("resolution sampled"),
            ):
                value = runtime_profile._resolve_particle_source(
                    root, project, "rf_multipole_ion_optics", "new_source", resolved=design
                )
            self.assertEqual(value["particle_count"], 100)
            self.assertNotIn("path", value)
            self.assertEqual(value["release_spec"]["path"], str(spec.resolve()))
            self.assertFalse((project / "config/release.csv").exists())
            with self.assertRaisesRegex(ValueError, "campaign transforms"):
                runtime_profile._resolve_particle_source(root, project, "rf_multipole_ion_optics", "new_source")
            document["profiles"]["new_source"]["path"] = "unused.csv"
            registry.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "keys differ"):
                runtime_profile._resolve_particle_source(
                    root, project, "rf_multipole_ion_optics", "new_source", resolved=design
                )

    def test_multipole_family_profiles_freeze_one_shared_source(self) -> None:
        resolved = [
            resolve_runtime_profile(
                REPO_ROOT,
                PROJECT_ID,
                f"{variant}_no_acceleration_full_length",
            )
            for variant in VARIANTS
        ]
        self.assertEqual(
            {item["particle_source"]["sha256"] for item in resolved},
            {"0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F"},
        )
        self.assertEqual(
            {item["particle_source"]["path"] for item in resolved},
            {str((REPO_ROOT / "projects/rf_multipole_ion_optics/config/sources/rf_multipole_family_mother_sample_v1_100.csv").resolve())},
        )

    def test_project_wrappers_expose_profile_identity_not_free_parameters(self) -> None:
        forbidden = (
            "[string]$ParticleSourcePath", "[int]$MeshAutoLevel", "[double]$CellMm",
            "[int]$RfStepsPerPeriod", "[int]$TrajectoryQuality", "[double]$MaximumTimeUs",
            "[string]$TemplateIob",
        )
        entry = REPO_ROOT / "projects" / PROJECT_ID / "workflows/no_collision_transport"
        for name in ("run_comsol.ps1", "run_simion.ps1"):
            source = (entry / name).read_text(encoding="utf-8-sig")
            self.assertIn("[string]$RuntimeProfileId", source)
            for token in forbidden:
                self.assertNotIn(token, source)

    def test_registration_identity_comes_from_all_structural_variants(self) -> None:
        project_root = REPO_ROOT / "projects" / PROJECT_ID
        descriptor = json.loads((project_root / "config/project.json").read_text(encoding="utf-8-sig"))
        self.assertIsNone(descriptor["contracts"]["baseline"])
        profiles = json.loads(
            (project_root / descriptor["contracts"]["design_profiles"]).read_text(encoding="utf-8-sig")
        )
        expected = {"quadrupole": (2, 4), "hexapole": (3, 6), "octupole": (4, 8)}
        self.assertEqual({item["variant_id"] for item in descriptor["structural_variants"]}, set(expected))
        self.assertEqual({item["structural_variant_id"] for item in profiles["profiles"]}, set(expected))
        for profile in profiles["profiles"]:
            identity = profile["identity"]
            self.assertEqual(identity["project_id"], descriptor["project_id"])
            self.assertEqual(identity["family_id"], descriptor["family_id"])
            self.assertEqual(
                (identity["radial_order_n"], identity["electrode_count"]),
                expected[profile["structural_variant_id"]],
            )

    def test_runtime_registry_is_read_once_and_rejects_nontext_paths(self) -> None:
        project = "rf_multipole_ion_optics"
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
                    resolve_runtime_profile(REPO_ROOT, project, "hexapole_no_acceleration_full_length")
                else:
                    with self.assertRaisesRegex(ValueError, "registry path is invalid"):
                        resolve_runtime_profile(REPO_ROOT, project, "hexapole_no_acceleration_full_length")
                self.assertEqual(len(calls), 1)

    def test_particle_source_hash_is_read_once_and_stale_identity_is_rejected(self) -> None:
        source = REPO_ROOT / "projects/rf_multipole_ion_optics/config/sources/rf_multipole_family_mother_sample_v1_100.csv"
        original = runtime_profile._sha256
        with patch.object(runtime_profile, "_sha256", wraps=original) as hashed:
            resolved = resolve_runtime_profile(REPO_ROOT, "rf_multipole_ion_optics", "hexapole_no_acceleration_full_length")
        self.assertEqual(sum(call.args[0] == source for call in hashed.call_args_list), 1)
        self.assertEqual(resolved["particle_source"]["sha256"], original(source))
        with patch.object(
            runtime_profile, "_sha256", side_effect=lambda path: "0" * 64 if path == source else original(path)
        ):
            with self.assertRaisesRegex(ValueError, "particle-source SHA-256 differs"):
                resolve_runtime_profile(REPO_ROOT, "rf_multipole_ion_optics", "hexapole_no_acceleration_full_length")

    def test_unknown_runtime_profile_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown runtime profile"):
            resolve_runtime_profile(REPO_ROOT, "rf_multipole_ion_optics", "not-a-profile")

    def test_runtime_stop_stage_is_explicit_or_normalized_to_transport(self) -> None:
        normal = resolve_runtime_profile(
            REPO_ROOT,
            "rf_multipole_ion_optics",
            "hexapole_no_acceleration_full_length",
        )
        self.assertEqual(normal["stop_stage"], "transport")
        registry_path = REPO_ROOT / "projects/rf_multipole_ion_optics/config/runtime_profiles.json"
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
            "rf_multipole_ion_optics",
            "quadrupole_no_acceleration_full_length",
        )
        self.assertEqual(
            resolved["design_profile_id"],
            "quadrupole_no_acceleration_full_length",
        )
        self.assertEqual(
            resolved["particle_source"]["sha256"],
            "0125C3AB02B2321EF26A3A913CF6EC04325FD0D48597D2CB439D0CE42411662F",
        )
        for name in ("run_comsol.ps1", "run_simion.ps1"):
            source = (
                REPO_ROOT / "projects/rf_multipole_ion_optics/workflows/no_collision_transport" / name
            ).read_text(encoding="utf-8-sig")
            self.assertIn("[string]$RuntimeProfileId", source)
            self.assertNotIn("[string]$ParticleSourcePath", source)

    def test_hybrid_numerics_do_not_inherit_old_geometry_authorization(self) -> None:
        for variant in ("quadrupole", "octupole"):
            baseline = resolve_runtime_profile(
                REPO_ROOT, PROJECT_ID, f"{variant}_no_acceleration_full_length",
            )
            hybrid = resolve_runtime_profile(
                REPO_ROOT, PROJECT_ID,
                f"{variant}_no_acceleration_full_length_n100_hybrid_exit025_temporal_refined",
            )
            self.assertEqual(baseline["engineering_budget"]["path"], hybrid["engineering_budget"]["path"])
            budget = json.loads(Path(baseline["engineering_budget"]["path"]).read_text(encoding="utf-8-sig"))
            self.assertFalse(budget["pilot_authorization"]["authorized"])
            self.assertNotEqual(
                baseline["solver_numerics"]["comsol"]["profile_id"],
                hybrid["solver_numerics"]["comsol"]["profile_id"],
            )


if __name__ == "__main__":
    unittest.main()

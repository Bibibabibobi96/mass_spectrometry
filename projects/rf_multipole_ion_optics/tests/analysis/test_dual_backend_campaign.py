"""Real campaign/compiler/budget/dispatch contracts with inert solver boundaries."""

from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from projects.rf_multipole_ion_optics.runtime import runtime_profile as runtime
from projects.rf_multipole_ion_optics.runtime.resource_budget import (
    validate_pilot_budget,
)
from projects.rf_multipole_ion_optics.tests.analysis import (
    test_comsol_campaign_request as fixture,
)

REPO = Path(runtime.__file__).resolve().parents[3]
PROJECT = "projects/rf_multipole_ion_optics"
PWSH = shutil.which("pwsh")


def request():
    data = fixture.request()
    data["campaign_id"] = "dual_backend_geometry_fixture"
    data["design_variable_authorization"] = dict(
        allowed_variable_ids=["vacuum_z_min"],
        variable_limits=[
            dict(variable_id="vacuum_z_min", unit="mm", minimum=-3, maximum=-3)
        ],
    )
    row = data["experiments"][0]
    row["execution_profile_id"] = "octupole_simion_transport_campaign_engineering"
    row["design_variable_values"] = {"vacuum_z_min": -3}
    row["experiment_id"] = "geometry_comsol"
    row["authorized_run_id"] = "20261031_010000__test__comsol__geometry-fixture"
    other = copy.deepcopy(row)
    other.update(
        solver="simion",
        experiment_id="geometry_simion",
        authorized_run_id="20261031_010001__test__simion__geometry-fixture",
    )
    other["resource_authorization"]["limits"]["maximum_pa_grid_points"] = 35000000
    data["experiments"].append(other)
    return data


class DualBackendCampaignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.tree = Path(cls.temp.name) / "source"
        for area in (
            "common/contracts",
            "common/paths",
            PROJECT + "/core",
            PROJECT + "/runtime",
            PROJECT + "/analysis",
            PROJECT + "/config",
            PROJECT + "/variants",
        ):
            for source in (REPO / area).rglob("*"):
                if (
                    source.is_file()
                    and "__pycache__" not in source.parts
                    and source.suffix in (".py", ".ps1", ".json", ".csv", ".lua")
                ):
                    target = cls.tree / source.relative_to(REPO)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        target = cls.tree / "config/project_registry.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "config/project_registry.json", target)
        for relative in (
            "common/require_powershell7.ps1",
            "common/host_execution_lease.ps1",
            "common/host_resource_scheduler.py",
            "common/host_resource_policy.json",
            "common/resource_budget_support.ps1",
        ):
            target = cls.tree / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, target)

    def setUp(self):
        self.case = tempfile.TemporaryDirectory()
        self.addCleanup(self.case.cleanup)
        self.root = Path(self.case.name)

    def write(self, data):
        path = self.root / "campaign.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def resolve(self, data, solver="comsol"):
        path = self.write(data)
        row = next(row for row in data["experiments"] if row["solver"] == solver)
        return path, runtime.resolve_campaign_experiment(
            self.tree, "rf_multipole_ion_optics", path, row["experiment_id"]
        )

    def test_actual_resolver_budget_and_backend_declarations(self):
        for solver in ("comsol", "simion"):
            with self.subTest(solver=solver):
                path, resolved = self.resolve(request(), solver)
                budget = validate_pilot_budget(
                    repo_root=self.tree,
                    budget_path=path,
                    project_id="rf_multipole_ion_optics",
                    solver=solver,
                    runtime_profile_id=resolved["runtime_profile_id"],
                    design_profile_id=resolved["design_profile_id"],
                    particle_source_path=Path(resolved["particle_source"]["path"]),
                    retention_class="solver_review",
                    run_id=resolved["engineering_budget"]["inline_contract"][
                        "pilot_authorization"
                    ]["scope"]["authorized_run_id"],
                    resolved_runtime=resolved,
                )
                self.assertEqual(budget["solver"], solver)
                self.assertEqual(
                    resolved["engineering_budget"]["inline_contract"][
                        "pilot_authorization"
                    ]["scope"]["allowed_solvers"],
                    [solver],
                )
                self.assertEqual(
                    resolved["design_profile_resolution"]["resolved_design"][
                        "geometry_mm"
                    ]["numerical_domain"]["z_min_mm"],
                    -3,
                )
        profile = next(
            p
            for p in json.loads(
                (self.tree / PROJECT / "config/execution_profiles.json").read_text(
                    encoding="utf-8"
                )
            )["profiles"]
            if p["profile_id"] == "octupole_simion_transport_campaign_engineering"
        )
        self.assertEqual(
            set(profile["tools"]), {"simion", "comsol", "matlab", "python"}
        )
        self.assertTrue(
            {"simion_model", "comsol_model"} <= set(profile["deliverable_outputs"])
        )

    @unittest.skipUnless(PWSH, "PowerShell 7 required")
    def test_comsol_mesh_build_resolves_and_dispatches_with_real_budget(self):
        data = request()
        data["experiments"] = data["experiments"][:1]
        data["experiments"][0]["stop_stage"] = "mesh_build"
        path, resolved = self.resolve(data)
        self.assertEqual(resolved["stop_stage"], "mesh_build")
        snapshot = self.root / "mesh_snapshot.json"
        snapshot.write_text(json.dumps(resolved), encoding="utf-8")
        self.dispatch(data, snapshot=snapshot, path=path)

    def test_campaign_rejects_unsupported_stop_stages_before_dispatch(self):
        for solver, stage in (("simion", "mesh_build"), ("comsol", "field_solve"),
                              ("comsol", "not_a_stage")):
            with self.subTest(solver=solver, stage=stage):
                data = request()
                row = next(row for row in data["experiments"] if row["solver"] == solver)
                row["stop_stage"] = stage
                with self.assertRaisesRegex(ValueError, "invalid multipole transport campaign.*stop_stage"):
                    self.resolve(data, solver)

    @unittest.skipUnless(PWSH, "PowerShell 7 required")
    def test_minimum_argument_drift_is_rejected_by_real_finite_preflight(self):
        data = request()
        data["experiments"] = data["experiments"][:1]
        self.dispatch(data, minimum_override=0.3,
                      expected_error="minimum element size differs from the authorized runtime profile")

    def test_transport_compiler_does_not_promise_mesh_only_outputs(self):
        from common.contracts.compile_execution_plan import compile_execution
        from common.contracts.plan_design_request import build_plan

        campaign = request()
        campaign["experiments"] = campaign["experiments"][:1]
        neutral = json.loads((REPO / "common/contracts/examples/rf_quadrupole_transport.example.json").read_text(encoding="utf-8"))
        neutral.update(status="approved", evidence_level="plan", design_variables=[],
                       approval=dict(approved_by="owner", approved_on="2026-10-31"))
        neutral["target"].update(structural_variant_id="octupole", mode="octupole_finite_3d_no_collision")
        neutral["operating_points"] = [dict(mass=dict(value=100,unit="Da"),charge_state=1)]
        neutral["objectives"] = neutral["objectives"][:1]
        neutral["required_outputs"] = ["simulation_results", "validation_report", "comsol_model"]
        request_path = self.root / "design_request.json"
        request_path.write_text(json.dumps(neutral), encoding="utf-8")
        registry = REPO / "config/project_registry.json"
        plan, _ = build_plan(request_path, registry, "20261031_010002__analysis__repo__mesh-binding")
        plan_path = self.root / "design_plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        for stage in ("transport", "mesh_build"):
            with self.subTest(stage=stage):
                campaign["experiments"][0]["stop_stage"] = stage
                path = self.write(campaign)
                bindings = dict(campaign_path=str(path), experiment_id="geometry_comsol")
                if stage == "transport":
                    result = compile_execution(plan_path, registry, bindings)
                    self.assertEqual(result["status"], "EXECUTION_READY", result)
                else:
                    with self.assertRaisesRegex(ValueError, "requires stop_stage=transport"):
                        compile_execution(plan_path, registry, bindings)

    def test_explicit_minimum_is_validated_by_the_real_resolver(self):
        catalog = self.tree / PROJECT / "config/comsol_solver_numerics.json"
        original = catalog.read_text(encoding="utf-8")
        try:
            for invalid in (0, -0.2, True, "0.2", 3.0):
                with self.subTest(minimum=invalid):
                    document = json.loads(original)
                    document["profiles"]["core_flow_development_coarse_8us"]["mesh"]["minimum_element_size_mm"] = invalid
                    catalog.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "minimum_element_size_mm"):
                        self.resolve(request())
        finally:
            catalog.write_text(original, encoding="utf-8")

    def test_comsol_request_variables_match_the_actual_authorized_row(self):
        path, resolved = self.resolve(request(), "comsol")
        bindings = dict(campaign_path=str(path), experiment_id=resolved["runtime_profile_id"])
        context = self.root / "requested_variables.json"
        for variables in ([], ["vacuum_z_min"], ["rf_amplitude"], ["rf_frequency"]):
            with self.subTest(variables=variables):
                context.write_text(json.dumps(dict(required_outputs=["comsol_model"],
                                                  constraints=[], design_variables=variables)), encoding="utf-8")
                if any(variable != "vacuum_z_min" for variable in variables):
                    with self.assertRaisesRegex(ValueError, "cannot consume requested design variables"):
                        runtime.resolve_execution_binding(self.tree, "rf_multipole_ion_optics", bindings,
                                                          request_path=context)
                else:
                    selected = runtime.resolve_execution_binding(
                        self.tree, "rf_multipole_ion_optics", bindings, request_path=context)
                    self.assertEqual(selected["tools"], ["comsol", "matlab", "python"])
        data = request()
        del data["design_variable_authorization"]
        for row in data["experiments"]:
            del row["execution_profile_id"]
            del row["design_variable_values"]
        path, resolved = self.resolve(data, "comsol")
        context.write_text(json.dumps(dict(required_outputs=["comsol_model"], constraints=[],
                                          design_variables=["vacuum_z_min"])), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "cannot consume requested design variables"):
            runtime.resolve_execution_binding(self.tree, "rf_multipole_ion_optics",
                                              dict(campaign_path=str(path), experiment_id=resolved["runtime_profile_id"]),
                                              request_path=context)

    def test_rejects_wrong_unit_outside_catalog_and_wrong_profile(self):
        for kind, expected in [
            ("unit", "unit differs"),
            ("bounds", "range exceeds catalog bounds"),
            ("profile", "different structural variant"),
        ]:
            with self.subTest(kind=kind):
                data = request()
                if kind == "unit":
                    data["design_variable_authorization"]["variable_limits"][0][
                        "unit"
                    ] = "V"
                elif kind == "bounds":
                    data["design_variable_authorization"]["variable_limits"][0].update(
                        minimum=-41, maximum=-41
                    )
                else:
                    data["experiments"][0]["execution_profile_id"] = (
                        "hexapole_simion_transport_campaign_engineering"
                    )
                with self.assertRaisesRegex(ValueError, expected):
                    self.resolve(data)

    def test_project_binding_rejects_models_from_other_backend_and_comsol_phase_constraint(
        self,
    ):
        for solver in ("comsol", "simion"):
            with self.subTest(solver=solver):
                path, resolved = self.resolve(request(), solver)
                context = self.root / "design_request.json"
                # Only the projection fields: shared compiler owns full request validation.
                context.write_text(
                    json.dumps(
                        dict(
                            required_outputs=[
                                "simion_model" if solver == "comsol" else "comsol_model"
                            ],
                            constraints=[],
                            design_variables=[],
                        )
                    ),
                    encoding="utf-8",
                )
                bindings = dict(
                    campaign_path=str(path),
                    experiment_id=resolved["runtime_profile_id"],
                )
                selected = runtime.resolve_execution_binding(
                    self.tree, "rf_multipole_ion_optics", bindings
                )
                self.assertEqual(
                    selected["tools"],
                    ["comsol", "matlab", "python"]
                    if solver == "comsol"
                    else ["simion", "python"],
                )
                with self.assertRaisesRegex(ValueError, "cannot deliver"):
                    runtime.resolve_execution_binding(
                        self.tree,
                        "rf_multipole_ion_optics",
                        bindings,
                        request_path=context,
                    )
                context.write_text(
                    json.dumps(
                        dict(
                            required_outputs=[solver + "_model"],
                            constraints=[
                                dict(parameter="phase_matched_particle_source")
                            ]
                            if solver == "comsol"
                            else [],
                            design_variables=[],
                        )
                    ),
                    encoding="utf-8",
                )
                if solver == "comsol":
                    with self.assertRaisesRegex(ValueError, "cannot enforce SIMION"):
                        runtime.resolve_execution_binding(
                            self.tree,
                            "rf_multipole_ion_optics",
                            bindings,
                            request_path=context,
                        )
                else:
                    selected = runtime.resolve_execution_binding(
                        self.tree,
                        "rf_multipole_ion_optics",
                        bindings,
                        request_path=context,
                    )
                    self.assertEqual(
                        selected["resolved_runtime"]["runtime_profile_id"],
                        resolved["runtime_profile_id"],
                    )

    def test_named_two_backend_runtime_keeps_both_actual_tools(self):
        selected = runtime.resolve_execution_binding(
            self.tree,
            "rf_multipole_ion_optics",
            {"runtime_profile_id": "quadrupole_no_acceleration_full_length"},
        )
        self.assertEqual(
            set(selected["tools"]), {"comsol", "matlab", "simion", "python"}
        )

    def test_comsol_does_not_gain_other_candidate_variables(self):
        data = request()
        data["design_variable_authorization"] = dict(
            allowed_variable_ids=["rf_phase"],
            variable_limits=[
                dict(variable_id="rf_phase", unit="rad", minimum=0, maximum=0)
            ],
        )
        for row in data["experiments"]:
            row["design_variable_values"] = {"rf_phase": 0}
        with self.assertRaisesRegex(ValueError, "vacuum_z_min only"):
            self.resolve(data)

    def test_comsol_keeps_simion_policies_rejected(self):
        policies = {
            "particle_source_phase_policy": dict(
                kind="match_baseline_rf_phase",
                baseline_frequency_Hz=1e6,
                frequency_variable_id="rf_frequency",
                n1000_reference_profile_id="not-resolved",
            ),
            "particle_source_transform_policy": dict(
                kind="preserve_phase_position_direction_and_scale_energy",
                rf_frequency_Hz=1e6,
                n1000_reference_profile_id="not-resolved",
            ),
            "simion_pa_basis_policy": dict(
                kind="content_addressed_geometry_basis",
                reuse_scope="same_project_same_fingerprint",
            ),
        }
        for key, value in policies.items():
            with self.subTest(policy=key):
                data = request()
                data[key] = value
                if key == "particle_source_transform_policy":
                    data["simion_pa_basis_policy"] = policies["simion_pa_basis_policy"]
                    for row in data["experiments"]:
                        row["source_kinetic_energy_eV"] = 2
                with self.assertRaisesRegex(
                    ValueError, "SIMION-specific policies are unsupported"
                ):
                    self.resolve(data)

    def test_comsol_analysis_requests_stay_rejected(self):
        data = request()
        for row in data["experiments"]:
            row["case_set"] = "primary_only"
        data["analysis_requests"] = [
            dict(
                capability_id="multipole_exit_state_comparison_v1",
                experiment_ids=["geometry_comsol", "geometry_simion"],
                baseline_experiment_id="geometry_comsol",
                analysis_run_id="20261031_010200__analysis__cross__fixture",
                parameters={},
            )
        ]
        with self.assertRaisesRegex(
            ValueError, "SIMION-specific policies are unsupported"
        ):
            self.resolve(data)

    @unittest.skipUnless(PWSH, "PowerShell 7 required")
    def test_status_diff_and_all_dry_run_stay_solver_free(self):
        path = self.write(request())
        for flags in (
            ["-Status"],
            [
                "-ExperimentId",
                "geometry_comsol",
                "-SemanticDiffAgainst",
                "geometry_simion",
            ],
            ["-All", "-DryRun"],
        ):
            with self.subTest(flags=flags):
                env = os.environ.copy()
                env["PYTHONPATH"] = str(self.tree)
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                result = subprocess.run(
                    [
                        PWSH,
                        "-NoProfile",
                        "-File",
                        str(
                            self.tree
                            / PROJECT
                            / "runtime/run_simion_transport_campaign.ps1"
                        ),
                        "-CampaignPath",
                        str(path),
                        "-RepoRoot",
                        str(self.tree),
                        "-PythonExe",
                        sys.executable,
                        *flags,
                    ],
                    cwd=self.tree,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((self.tree.parent / "artifacts").exists())

    @unittest.skipUnless(PWSH, "PowerShell 7 required")
    def test_frozen_backend_or_campaign_drift_rejected_before_inert_dispatch(self):
        for kind in ("solver", "campaign"):
            with self.subTest(kind=kind):
                data = request()
                data["experiments"] = data["experiments"][:1]
                path, resolved = self.resolve(data)
                if kind == "solver":
                    resolved["engineering_budget"]["inline_contract"][
                        "pilot_authorization"
                    ]["scope"]["allowed_solvers"] = ["simion"]
                else:
                    data["claim_limit"] = "Changed after freezing"
                    path = self.write(data)
                snapshot = self.root / "negative_snapshot.json"
                snapshot.write_text(json.dumps(resolved), encoding="utf-8")
                self.dispatch(
                    data,
                    snapshot=snapshot,
                    path=path,
                    expected_error="Campaign preflight identity differs"
                    if kind == "solver"
                    else "Compiled runtime campaign binding differs",
                )

    @unittest.skipUnless(PWSH, "PowerShell 7 required")
    def test_actual_campaign_and_launcher_dispatch_both_backends_without_solver(self):
        self.dispatch(request())

    @unittest.skipUnless(PWSH, "PowerShell 7 required")
    def test_frozen_runtime_dispatch_does_not_resolve_missing_catalog(self):
        data = request()
        data["experiments"] = data["experiments"][:1]
        path, resolved = self.resolve(data)
        snapshot = self.root / "snapshot.json"
        snapshot.write_text(json.dumps(resolved), encoding="utf-8")
        catalog = self.tree / PROJECT / "variants/octupole/config/design_variables.json"
        hidden = catalog.with_suffix(".hidden")
        catalog.rename(hidden)
        try:
            self.dispatch(data, snapshot=snapshot, path=path)
        finally:
            hidden.rename(catalog)

    def dispatch(self, data, snapshot=None, path=None, expected_error=None, minimum_override=None):
        path = path or self.write(data)
        # Only final solver consumers are inert; actual campaign, launcher,
        # resolver and budget execute. This produces no native/scientific result.
        script = self.root / "invoke.ps1"
        instrument = r"""
$ErrorActionPreference='Stop'
$source='@@SOURCE@@';$events='@@EVENTS@@';$python='@@PYTHON@@'
# Retain the real authorized-argument check and frozen numerical materialization.
$finiteText=Get-Content -LiteralPath '@@FINITE_SOURCE@@' -Raw -Encoding UTF8
$checkStart=$finiteText.IndexOf('  $authorizedHmin=')
$checkEnd=$finiteText.IndexOf('}finally{',$checkStart)
$checkText=$finiteText.Substring($checkStart,$checkEnd-$checkStart)
$freezeStart=$finiteText.IndexOf('  $solverNumericsDocument=[ordered]')
$freezeEnd=$finiteText.IndexOf('  $evidence=$null',$freezeStart)
$freezeText=$finiteText.Substring($freezeStart,$freezeEnd-$freezeStart)
foreach($solver in @('comsol','simion')){
 $relative=if($solver-eq'comsol'){'runtime/run_finite_3d_transport.ps1'}else{'runtime/run_simion_finite_3d_transport.ps1'}
 $file=Join-Path $source ('projects/rf_multipole_ion_optics/'+$relative)
 $ast=[Management.Automation.Language.Parser]::ParseFile($file,[ref]$null,[ref]$null)
 $body=@'
$ErrorActionPreference='Stop'
$resolved=Get-Content -LiteralPath $ResolvedRuntimeProfilePath -Raw|ConvertFrom-Json
$budget=Join-Path (Split-Path '@@EVENTS@@') ('budget_@@SOLVER@@.json')
Push-Location '@@SOURCE@@'
try{& $PythonExe -B -m projects.rf_multipole_ion_optics.runtime.resource_budget --repo-root '@@SOURCE@@' --budget $EngineeringBudgetPath --project-id $ProjectId --solver '@@SOLVER@@' --runtime-profile-id $RuntimeProfileId --design-profile-id $DesignProfileId --particle-source $ParticleSourcePath --retention-class $RetentionClass --run-id $RunId --resolved-runtime-profile $ResolvedRuntimeProfilePath --output $budget
 if($LASTEXITCODE-ne0){throw 'REAL_BUDGET_FAILED'}
 & $PythonExe -B -c 'import sys;from common.contracts.artifact_retention import validate_retention;validate_retention(dict(policy_version=1,**{"class":sys.argv[1]},reason=sys.argv[2] if sys.argv[1]!="compact" else None))' $RetentionClass $RetentionReason
 if($LASTEXITCODE-ne0){throw 'REAL_RETENTION_POLICY_FAILED'}
}finally{Pop-Location}
$frozenMinimum=$null
if('@@SOLVER@@'-eq'comsol'){
 $authorizedNumerics=$resolved.solver_numerics.comsol.values
 $authorizedBackend=$authorizedNumerics.stationary_linear_solver_backend
 $authorizedElementOrder=$authorizedNumerics.electric_potential_element_order
 @@MINIMUM_OVERRIDE@@
 @@AUTH_CHECK@@
 $numerics=Join-Path (Split-Path '@@EVENTS@@') 'actual_frozen_numerics.json'
 @@MATERIALIZE@@
 $frozen=Get-Content -LiteralPath $numerics -Raw|ConvertFrom-Json
 if($frozen.mesh.PSObject.Properties.Name-contains'minimum_element_size_mm'){$frozenMinimum=$frozen.mesh.minimum_element_size_mm}
}
@{minimum_parameter=$(if('@@SOLVER@@'-eq'comsol'-and-not[double]::IsNaN($MinimumElementSizeMm)){$MinimumElementSizeMm}else{$null});frozen_minimum=$frozenMinimum;solver='@@SOLVER@@';run_id=$RunId;runtime_id=$RuntimeProfileId;domain=$resolved.design_profile_resolution.resolved_design.geometry_mm.numerical_domain;budget=$budget;stop_stage=$resolved.stop_stage;consumer_stop_stage=$(if('@@SOLVER@@'-eq'comsol'){$StopStage}else{'transport'});budget_stop_stage=(Get-Content -LiteralPath $budget -Raw|ConvertFrom-Json).stop_stage;retention_class=$RetentionClass;retention_reason=$RetentionReason;inert=$true;simion_exe_forwarded=$PSBoundParameters.ContainsKey('SimionExe')}|ConvertTo-Json -Compress|Add-Content -LiteralPath '@@EVENTS@@' -Encoding utf8
'@
 $body=$body.Replace('@@SOLVER@@',$solver).Replace('@@AUTH_CHECK@@',$checkText).Replace('@@MATERIALIZE@@',$freezeText)
 [IO.File]::WriteAllText($file,'[CmdletBinding()]'+[Environment]::NewLine+$ast.ParamBlock.Extent.Text+[Environment]::NewLine+$body,[Text.UTF8Encoding]::new($false))
}
& (Join-Path $source 'projects/rf_multipole_ion_optics/runtime/run_simion_transport_campaign.ps1') -CampaignPath '@@CAMPAIGN@@' @@SELECTION@@ -RepoRoot $source -PythonExe $python -SimionExe $python @@SNAPSHOT@@
"""
        replacements = {
            "@@MINIMUM_OVERRIDE@@": "" if minimum_override is None else f"$MinimumElementSizeMm={minimum_override}",
            "@@FINITE_SOURCE@@": str(REPO / PROJECT / "runtime/run_finite_3d_transport.ps1").replace("'", "''"),
            "@@SOURCE@@": str(self.tree).replace("'", "''"),
            "@@EVENTS@@": str(self.root / "events.jsonl").replace("'", "''"),
            "@@PYTHON@@": sys.executable.replace("'", "''"),
            "@@CAMPAIGN@@": str(path).replace("'", "''"),
            "@@SELECTION@@": "-ExperimentId '"
            + data["experiments"][0]["experiment_id"]
            + "'"
            if snapshot
            else "-All",
            "@@SNAPSHOT@@": "-ResolvedRuntimeProfilePath '"
            + str(snapshot).replace("'", "''")
            + "'"
            if snapshot
            else "",
        }
        for key, value in replacements.items():
            instrument = instrument.replace(key, value)
        script.write_text(instrument, encoding="utf-8", newline="\n")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.tree)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [PWSH, "-NoProfile", "-File", str(script)],
            cwd=self.tree,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        if expected_error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected_error, result.stdout + result.stderr)
            self.assertFalse((self.root / "events.jsonl").exists())
            return
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        records = [
            json.loads(line)
            for line in (self.root / "events.jsonl")
            .read_text(encoding="utf-8-sig")
            .splitlines()
        ]
        self.assertEqual(
            [r["solver"] for r in records], [r["solver"] for r in data["experiments"]]
        )
        self.assertTrue(
            all(r["inert"] and r["domain"]["z_min_mm"] == -3 for r in records)
        )
        self.assertEqual(
            [r["simion_exe_forwarded"] for r in records],
            [row["solver"] == "simion" for row in data["experiments"]],
        )
        for record in records:
            if record["solver"] == "comsol":
                self.assertEqual(record["minimum_parameter"], 0.2)
                self.assertEqual(record["frozen_minimum"], 0.2)
        expected_stages = [row["stop_stage"] for row in data["experiments"]]
        self.assertEqual([r["stop_stage"] for r in records], expected_stages)
        self.assertEqual([r["consumer_stop_stage"] for r in records], expected_stages)
        self.assertEqual([r["budget_stop_stage"] for r in records], expected_stages)
        self.assertFalse((self.tree.parent / "artifacts").exists())


if __name__ == "__main__":
    unittest.main()

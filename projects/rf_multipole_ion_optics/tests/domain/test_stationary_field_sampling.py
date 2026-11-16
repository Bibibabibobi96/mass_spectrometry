"""Tests for solver-neutral multipole stationary-field sampling."""

from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from pathlib import Path
from typing import Any

from projects.rf_multipole_ion_optics.analysis.stationary_field_sampling import (
    FIELD_OUTPUT_COLUMNS,
    StationaryFieldContractError,
    compare_stationary_field_outputs,
    generate_stationary_field_sample_rows,
    load_stationary_field_output_csv,
    main,
    validate_stationary_bvp,
    validate_stationary_output_authority,
)


def _resolved_design() -> dict[str, Any]:
    rods = []
    for index in range(6):
        angle = index * math.pi / 3
        rods.append(
            {
                "center_x_mm": 6.0 * math.cos(angle),
                "center_y_mm": 6.0 * math.sin(angle),
                "radius_mm": 2.0,
                "electrode_group": index % 2 + 1,
            }
        )
    return {
        "schema_version": 3,
        "role": "multipole_resolved_design_do_not_edit",
        "units": {"length": "mm"},
        "coordinate": {
            "coordinate_id": "multipole_canonical_xyz",
            "axial_axis": "+z",
        },
        "geometry_mm": {
            "inscribed_radius_r0": 4.0,
            "rod_z_min": 0.0,
            "rod_z_max": 10.0,
            "rod_array": {"rods": rods},
            "enclosure": {"model":"bare"},
            "numerical_domain": {"radius_mm":12.0,"z_min_mm":-1.0,"z_max_mm":12.0,"working_region_radius_mm":3.0},
            "observations": {"release_plane_z_mm":-1.5,"handoff_plane_z_mm":11.,"census_plane_z_mm":11.5,"acceptance_radius_mm":3.},
        },

    }


def _sampling_plan() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "role": "multipole_stationary_field_sampling_plan",
        "coordinate_id": "multipole_canonical_xyz",
        "units": {
            "length": "mm",
            "potential": "V",
            "electric_field": "V/m",
        },
        "axial_sampling": {
            "uniform_range": "rod_span",
            "uniform_sample_count": 3,
            "named_plane_ids": [
                "canonical_handoff_plane",
                "source_release_plane",
                "rod_exit",
            ],
        },
        "cross_section_sampling": {
            "rod_inward_clear_radius_fractions": [0.0, 0.5, 0.9],
            "azimuth_count": 4,
        },
        "bvp": {
            "domain": "resolved_design.geometry_mm.numerical_domain",
            "exterior": "zero_normal_electric_field",
            "electrode_voltages_v_by_group": {
                "differential": {"1":100.0,"2":-100.0},
                "static": {"1":0.0,"2":0.0},
            },
        },
        "potential_reference": "zero_mean_conductor_voltage",
    }


def _field_rows(
    potential_scale: float = 1.0,
    field_scale: float = 1.0,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    points = (
        ("p0", "entrance_aperture_plate_downstream_face", 0.0, 0.0, 0.0),
        ("p1", "rod_span_uniform", 1.0, -1.0, 5.0),
    )
    for field_case in ("differential", "static"):
        case_scale = 1.0 if field_case == "differential" else 2.0
        for index, (point_id, region, x_mm, y_mm, z_mm) in enumerate(
            points, start=1
        ):
            rows.append(
                {
                    "sample_id": point_id,
                    "region": region,
                    "field_case": field_case,
                    "x_mm": str(x_mm),
                    "y_mm": str(y_mm),
                    "z_mm": str(z_mm),
                    "potential_V": str(
                        potential_scale * case_scale * index
                    ),
                    "Ex_V_per_m": str(field_scale * case_scale * index),
                    "Ey_V_per_m": str(
                        field_scale * case_scale * (index + 1)
                    ),
                    "Ez_V_per_m": str(
                        field_scale * case_scale * (index + 2)
                    ),
                }
            )
    return rows


class StationaryFieldSamplingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def _write_rows(
        self,
        name: str,
        rows: list[dict[str, str]],
        columns: tuple[str, ...] = FIELD_OUTPUT_COLUMNS,
    ) -> Path:
        path = self.root / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_generation_is_deterministic_and_inside_clear_radius(self) -> None:
        first = generate_stationary_field_sample_rows(
            _resolved_design(), _sampling_plan()
        )
        second = generate_stationary_field_sample_rows(
            _resolved_design(), _sampling_plan()
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 6 * (1 + 4 + 4))
        self.assertEqual(tuple(first[0]), (
            "sample_id", "region", "x_mm", "y_mm", "z_mm"
        ))
        self.assertEqual(
            [row["region"] for row in first][::9],
            [
                "rod_span_uniform",
                "rod_span_uniform",
                "rod_span_uniform",
                "source_release_plane",
                "rod_exit",
                "canonical_handoff_plane",
            ],
        )
        self.assertEqual(len({str(row["sample_id"]) for row in first}), len(first))
        for row in first:
            self.assertLess(
                math.hypot(float(row["x_mm"]), float(row["y_mm"])), 4.0
            )

    def test_plan_rejects_unknown_alias_and_boundary_fraction(self) -> None:
        plan = _sampling_plan()
        plan["cross_section_sampling"]["radius_fractions"] = [0.0]
        with self.assertRaisesRegex(
            StationaryFieldContractError, "fields differ"
        ):
            generate_stationary_field_sample_rows(_resolved_design(), plan)
        plan = _sampling_plan()
        plan["cross_section_sampling"][
            "rod_inward_clear_radius_fractions"
        ] = [0.0, 1.0]
        with self.assertRaisesRegex(StationaryFieldContractError, r"\[0, 1\)"):
            generate_stationary_field_sample_rows(_resolved_design(), plan)

    def test_bvp_requires_actual_exterior_reference_and_conductor_voltages(self):
        for case in ("missing", "exterior", "reference", "voltage", "grounded"):
            plan = _sampling_plan()
            resolved = _resolved_design()
            if case == "missing": plan.pop("bvp")
            elif case == "exterior": plan["bvp"]["exterior"] = "ground"
            elif case == "reference": plan["potential_reference"] = "outer_shell"
            elif case == "voltage": plan["bvp"]["electrode_voltages_v_by_group"]["differential"]["1"] = 1.0
            else: resolved["geometry_mm"]["enclosure"]["model"] = "cylindrical_grounded_shell"
            with self.subTest(case=case), self.assertRaises(StationaryFieldContractError):
                validate_stationary_bvp(resolved, plan)

    def test_authority_binds_common_points_and_rejects_native_tamper(self):
        resolved_path = self.root/"resolved.json"; plan_path = self.root/"plan.json"; points_path = self.root/"points.csv"
        resolved_path.write_text(json.dumps(_resolved_design()), encoding="utf-8")
        plan_path.write_text(json.dumps(_sampling_plan()), encoding="utf-8")
        self.assertEqual(main(["generate","--resolved-design",str(resolved_path),"--sampling-plan",str(plan_path),"--output",str(points_path)]),0)
        authority_path = self.root/"authority.json"
        self.assertEqual(main(["authorize","--resolved-design",str(resolved_path),"--sampling-plan",str(plan_path),
            "--points",str(points_path),"--source-id","pure-fixture","--output",str(authority_path)]),0)
        authority = json.loads(authority_path.read_text(encoding="utf-8"))
        self.assertEqual(authority["bvp_by_case"]["differential"]["electrode_voltages_v_by_group"],{"1":100.0,"2":-100.0})
        self.assertEqual(authority["potential_reference"],"zero_mean_conductor_voltage")
        with points_path.open(encoding="utf-8",newline="") as stream: points=list(csv.DictReader(stream))
        rows=[]
        for field_case in ("differential","static"):
            for point in points:
                rows.append(dict(point,field_case=field_case,potential_V="0",Ex_V_per_m="0",Ey_V_per_m="0",Ez_V_per_m="0"))
        output=self._write_rows("authorized.csv",rows)
        validation=self.root/"validation.json"
        self.assertEqual(main(["validate","--input",str(output),"--output",str(validation),"--authority",str(authority_path)]),0)
        candidate=json.loads(json.dumps(authority));candidate["source"]["source_id"]="independent-fixture"
        candidate_path=self.root/"candidate-authority.json";candidate_path.write_text(json.dumps(candidate),encoding="utf-8")
        comparison_authority=self.root/"comparison-authority.json"
        self.assertEqual(main(["comparison-authority","--reference-authority",str(authority_path),
            "--candidate-authority",str(candidate_path),"--coordinate-tolerance-mm","0","--output",str(comparison_authority)]),0)
        compared=self.root/"compared.json"
        self.assertEqual(main(["compare","--reference",str(output),"--candidate",str(output),
            "--comparison-authority",str(comparison_authority),"--output",str(compared)]),0)
        result=json.loads(compared.read_text(encoding="utf-8"))
        self.assertEqual(result["field_cases"]["differential"]["paired_valid_count"],len(points))
        candidate["bvp_by_case"]["static"]["exterior"]="ground"
        candidate_path.write_text(json.dumps(candidate),encoding="utf-8")
        with self.assertRaisesRegex(StationaryFieldContractError,"bvp_by_case"):
            main(["comparison-authority","--reference-authority",str(authority_path),
                "--candidate-authority",str(candidate_path),"--coordinate-tolerance-mm","0","--output",str(comparison_authority)])
        rows[0]["x_mm"]="12345"
        tampered=self._write_rows("tampered.csv",rows)
        with self.assertRaisesRegex(StationaryFieldContractError,"identity|coordinates"):
            validate_stationary_output_authority(authority,tampered)

    def test_original_entries_wire_zero_compute_saved_export_and_pre_fly_simion_completion(self):
        root=Path(__file__).resolve().parents[2]
        comsol=(root/"runtime/run_finite_3d_transport.ps1").read_text(encoding="utf-8")
        simion=(root/"runtime/run_simion_finite_3d_transport.ps1").read_text(encoding="utf-8")
        saved=(root/"comsol/reextract_finite_3d_transport.m").read_text(encoding="utf-8")
        self.assertIn("StationaryFieldSamplingPlanPath",comsol)
        self.assertIn("--authority $stationaryAuthority",comsol)
        self.assertIn("export_comsol_stationary_field_samples",saved)
        self.assertIn("receipt.native_solves=0",saved)
        self.assertNotIn("mphsave",saved)
        self.assertNotRegex(saved,r"(?i)\.compute\s*\(")
        self.assertIn("export_stationary_field_samples.lua",simion)
        export_block="if((Get-Variable fieldOnly -ErrorAction SilentlyContinue)-and$fieldOnly){"
        self.assertEqual(simion.count(export_block),1)
        self.assertLess(simion.index(export_block),simion.index("Invoke-SimionStep 'build_runtime_iob'"))
        self.assertIn("-RequiredOutputPaths @($fieldSamples,$fieldSampleValidation)",simion)

    def test_simion_preregistration_binds_actual_solver_authorities_and_implementation(self):
        import hashlib
        import shutil
        import subprocess
        if shutil.which("pwsh") is None: self.skipTest("PowerShell 7 required")
        repo=Path(__file__).resolve().parents[4]
        relative=lambda path:path.relative_to(repo).as_posix()
        digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest().upper()
        budget=self.root/"budget.json";budget.write_text("{}",encoding="utf-8")
        implementation=[
            "projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1",
            "projects/rf_multipole_ion_optics/runtime/finite_3d_transport_preflight.ps1",
            "projects/rf_multipole_ion_optics/runtime/project_transport_launcher_support.ps1",
            "projects/rf_multipole_ion_optics/simion/export_stationary_field_samples.lua",
            "projects/rf_multipole_ion_optics/analysis/stationary_field_sampling.py"]
        project=repo/"projects/rf_multipole_ion_optics"
        authorities={"runtime_profiles_sha256":project/"config/runtime_profiles.json",
            "engineering_budget_sha256":budget,"particle_source_profiles_sha256":project/"config/particle_source_profiles.json",
            "design_profiles_sha256":project/"config/design_profiles.json",
            "simion_solver_numerics_sha256":project/"config/simion_solver_numerics.json"}
        plan=project/"config/contracts/stationary_field_sampling_plan.json"
        tokens=["CHECKPOINT=MESH_COMPLETE","CHECKPOINT=STATIONARY_FIELDS_COMPLETE",
            "CHECKPOINT=STATIONARY_FIELD_SAMPLES_COMPLETE","STOP_STAGE=field_solve","PARTICLE_PHYSICS_CREATED=0",
            "PARTICLE_STUDIES_CREATED=0","FIELD_SOLVE_DIAGNOSTIC=PASS","STATUS=PASS"]
        document={"schema_version":2,"role":"multipole_simion_field_solver_isolation_preregistration",
            "status":"authorized_not_run","project_id":"rf_multipole_ion_optics","preregistered_before_run":True,
            "authorization":{"maximum_commercial_run_count":1,"automatic_retry_count":0,"planned_run_id":"fixture",
                "runtime_profile_id":"fixture-profile","design_profile_id":"fixture-design","particle_source_profile_id":"fixture-source",
                "simion_solver_numerics_profile_id":"fixture-numerics","stop_stage":"field_solve","retention_class":"solver_review"},
            "frozen_identity":{"expected_run_parent_resolved_design_sha256":"A"*64,
                **{key:digest(path) for key,path in authorities.items()}},
            "frozen_implementation":{"files":[{"path":name,"sha256":digest(repo/name)} for name in implementation]},
            "field_sampling":{"role":"multipole_stationary_field_sampling","expected_point_count":1,"expected_row_count":2,
                "field_cases":["differential","static"],"plan_path":relative(plan),"plan_sha256":digest(plan)},
            "required_report":{"tokens":tokens,"forbidden_checkpoints":["PRIMARY_PARTICLE_CASE_COMPLETE","CONTROL_PARTICLE_CASE_COMPLETE"]}}
        path=self.root/"prereg.json";path.write_text(json.dumps(document),encoding="utf-8")
        q=lambda value:"'"+str(value).replace("'","''")+"'"
        script=(". "+q(repo/"projects/rf_multipole_ion_optics/runtime/finite_3d_transport_preflight.ps1")+";"
            "$result=Assert-MultipoleFieldPreregistration -Path "+q(path)+" -RepoRoot "+q(repo)+
            " -ProjectId rf_multipole_ion_optics -RunId fixture -RuntimeProfileId fixture-profile -DesignProfileId fixture-design"
            " -ParticleSourceProfileId fixture-source -SolverNumericsProfileId fixture-numerics -RetentionClass solver_review"
            " -ExpectedResolvedSha256 "+q("A"*64)+" -EngineeringBudgetPath "+q(budget)+" -Solver simion;"
            "$result.role|ConvertTo-Json -Compress")
        result=subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],cwd=self.root,
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("multipole_simion_field_solver_isolation_preregistration",result.stdout)
        document["role"]="multipole_comsol_field_solver_isolation_preregistration";path.write_text(json.dumps(document),encoding="utf-8")
        refused=subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],cwd=self.root,
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
        self.assertNotEqual(refused.returncode,0)
        self.assertIn("identity or status is invalid",refused.stderr)

    def test_simion_original_field_block_binds_outputs_without_iob_fly_or_transport(self):
        import shutil
        import subprocess
        import sys
        if shutil.which("pwsh") is None: self.skipTest("PowerShell 7 required")
        repo=Path(__file__).resolve().parents[4]
        resolved_path=self.root/"resolved.json";plan_path=self.root/"plan.json";points_path=self.root/"points.csv"
        resolved_path.write_text(json.dumps(_resolved_design()),encoding="utf-8")
        plan_path.write_text(json.dumps(_sampling_plan()),encoding="utf-8")
        main(["generate","--resolved-design",str(resolved_path),"--sampling-plan",str(plan_path),"--output",str(points_path)])
        authority=self.root/"authority.json"
        main(["authorize","--resolved-design",str(resolved_path),"--sampling-plan",str(plan_path),"--points",str(points_path),
            "--source-id","simion-inert-entry","--output",str(authority)])
        with points_path.open(encoding="utf-8",newline="") as stream: points=list(csv.DictReader(stream))
        for field_case in ("differential","static"):
            rows=[dict(point,field_case=field_case,potential_V="0",Ex_V_per_m="0",Ey_V_per_m="0",Ez_V_per_m="0") for point in points]
            self._write_rows(field_case+".csv",rows)
        results=self.root/"results";results.mkdir();(self.root/"logs").mkdir();(self.root/"simion").mkdir()
        (results/"usage.json").write_text("{}",encoding="utf-8")
        def q(value): return "'"+str(value).replace("'","''")+"'"
        script=r'''$ErrorActionPreference='Stop';Set-StrictMode -Version Latest
$fieldOnly=$true;$codeRoot=__REPO__;$python=__PYTHON__;$fieldSamplePoints=__POINTS__;$fieldSampleAuthority=__AUTHORITY__
$resultDir=__RESULTS__;$logDir=__LOGS__;$solverDir=__SOLVER__;$physicalRunDir=__ROOT__;$runDir=$physicalRunDir
$summary=Join-Path $resultDir 'summary.json';$resourceUsage=Join-Path $resultDir 'usage.json';$RunId='inert-field';$ProjectId='rf_multipole_ion_optics'
$DesignProfileId='fixture';$resolvedHash='A'*64;$phaseTimings=@{};$runTimer=[Diagnostics.Stopwatch]::StartNew();$fieldCheckpointOutputs=@()
$fieldPlan=$null;$origin=12.;$zShift=1.;$resolvedCellMmX=1.;$resolvedCellMmY=1.;$resolvedCellMmZ=1.
$stationaryVoltages=@{differential=@('1=100','2=-100');static=@('1=0','2=0')}
$fieldPreregistration=@{field_sampling=@{expected_point_count=__COUNT__;expected_row_count=__ROWS__}}
$nativeOperations=[Collections.ArrayList]::new();$hostReleaseState=@{released=$false};$ownerContext=@{};$hostExecutionOutcome='failed';$hostExecutionLease=@{}
$continuationCapacity=$null;$deferFinalization=$false;$ResultPath=Join-Path $resultDir 'result.json';$script:operations=@();$script:required=@()
function Set-RfRunPhase($Next){}
function Copy-VerifiedRunInput($Source,$Destination){Copy-Item -LiteralPath $Source -Destination $Destination}
function Convert-WorkflowOwnerPath($Context,$Path){return $Path}
function Get-RunPythonImportRoots($RepoRoot){return @((Join-Path $RepoRoot 'src'),$RepoRoot)}
function Invoke-SimionStep($Name,$Arguments,$Environment=@{}){
 $script:operations+=$Name;Copy-Item -LiteralPath (Join-Path __ROOT__ ($Arguments[7]+'.csv')) -Destination $Arguments[6]
}
function Get-RfSimionStoppedWriterCompletion($HostLease,$NativeOperations,$State){$State.released=$true;return @{operations=@();resource_releases=@()}}
function Complete-RunArtifactPowerShellOwner {
 param($Context,$Status,$Summary,$OutputPaths,$RequiredOutputPaths,$WriterCompletion,$WritersStopped,$ResourceUsagePaths,$OriginalFailure)
 $script:required=@($RequiredOutputPaths);$script:completedStatus=$Status
}
$ast=[Management.Automation.Language.Parser]::ParseFile((Join-Path $codeRoot 'projects/rf_multipole_ion_optics/runtime/run_simion_finite_3d_transport.ps1'),[ref]$null,[ref]$null)
$nodes=@($ast.FindAll({param($n)$n-is[Management.Automation.Language.IfStatementAst]},$true)|Where-Object{$_.Extent.Text.TrimStart().StartsWith('if((Get-Variable fieldOnly')})
if($nodes.Count-ne1){throw 'Unique field export/finalization block missing'}
$node=$nodes[0]
Invoke-Expression $node.Extent.Text
if(@($script:operations|Where-Object{$_-notin@('stationary_sample_differential','stationary_sample_static')}).Count){throw 'Transport/native operation escaped field-only branch'}
if($script:operations.Count-ne2-or$script:completedStatus-ne'success'){throw 'Field-only sampling/finalization did not complete'}
__RESULT__
'''
        script=script.replace("__REPO__",q(repo)).replace("__PYTHON__",q(sys.executable)).replace("__POINTS__",q(points_path))
        script=script.replace("__AUTHORITY__",q(authority)).replace("__RESULTS__",q(results)).replace("__LOGS__",q(self.root/"logs"))
        script=script.replace("__SOLVER__",q(self.root/"simion")).replace("__ROOT__",q(self.root)).replace("__COUNT__",str(len(points)))
        script=script.replace("__ROWS__",str(2*len(points))).replace("__RESULT__","@($script:operations+$script:required)|ConvertTo-Json -Compress")
        outcome=subprocess.run([shutil.which("pwsh"),"-NoProfile","-Command",script],cwd=self.root,
            capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=60)
        self.assertEqual(outcome.returncode,0,outcome.stdout+outcome.stderr)
        facts=json.loads(outcome.stdout.strip().splitlines()[-1])
        self.assertEqual(facts[:2],["stationary_sample_differential","stationary_sample_static"])
        self.assertEqual({Path(value).name for value in facts[2:]},{"stationary_field_samples.csv","stationary_field_sample_validation.json"})
        summary=json.loads((results/"summary.json").read_text(encoding="utf-8-sig"))
        self.assertEqual(summary["fly_calls"],0)
        self.assertFalse((self.root/"simion/quad_monolithic.iob").exists())

    def test_simion_sampling_resource_uses_no_save_pa_double_and_canonical_units(self):
        import shutil
        import subprocess
        lua=shutil.which("lua") or shutil.which("lua5.1")
        if lua is None: self.skipTest("portable Lua unavailable")
        root=Path(__file__).resolve().parents[2]
        resource=root/"simion/export_stationary_field_samples.lua"
        points=self.root/"native-points.csv"
        points.write_text("sample_id,region,x_mm,y_mm,z_mm\np0,vacuum,0,0,0\np1,vacuum,1,2,3\n",encoding="utf-8")
        output=self.root/"native.csv";stub=self.root/"pa_double.lua"
        stub.write_text("simion={pas={}} function simion.pas:close() end function simion.pas:open(path) "
            "assert(path=='inert.pa0');local p={} function p:fast_adjust(v) assert(v[1]==100 and v[2]==-100) end "
            "function p:inside_vc(x,y,z) return true end function p:potential_vc(x,y,z) return x+y+z end "
            "function p:field_vc(x,y,z) return 1,2,3 end function p:close() end return p end",encoding="utf-8")
        script="dofile("+repr(stub.as_posix())+")\n"+resource.read_text(encoding="utf-8")
        combined=self.root/"combined.lua";combined.write_text(script,encoding="utf-8")
        result=subprocess.run([lua,str(combined),"inert.pa0",str(points),str(output),"differential","10,10,10","1,1,1","1=100","2=-100"],
            cwd=self.root,capture_output=True,text=True,encoding="utf-8",timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        records=load_stationary_field_output_csv(output)
        self.assertEqual(len(records),2)
        self.assertEqual((records[0].Ex_V_per_m,records[0].Ey_V_per_m,records[0].Ez_V_per_m),(1000.,2000.,3000.))
        self.assertNotIn(":save",resource.read_text(encoding="utf-8"))

    def test_load_and_compare_valid_outputs(self) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows("reference.csv", _field_rows())
        )
        candidate = load_stationary_field_output_csv(
            self._write_rows(
                "candidate.csv",
                _field_rows(potential_scale=1.5, field_scale=2.0),
            )
        )
        result = compare_stationary_field_outputs(reference, candidate)
        self.assertEqual(result["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")
        self.assertFalse(result["acceptance_thresholds_applied"])
        self.assertEqual(result["total_sample_count"], 4)
        differential = result["field_cases"]["differential"]
        self.assertEqual(differential["sample_count"], 2)
        self.assertEqual(
            tuple(differential["regions"]),
            (
                "entrance_aperture_plate_downstream_face",
                "rod_span_uniform",
            ),
        )
        self.assertEqual(
            differential["regions"]["rod_span_uniform"]["sample_count"], 1
        )
        self.assertGreater(
            differential["potential"]["rms_absolute_difference_V"], 0
        )
        self.assertGreater(
            differential["field_vector"][
                "maximum_difference_norm_V_per_m"
            ],
            0,
        )
        for component in ("Ex", "Ey", "Ez"):
            self.assertGreater(
                differential["field_components"][component][
                    "rms_absolute_difference_V_per_m"
                ],
                0,
            )

    def test_load_rejects_missing_column(self) -> None:
        columns = tuple(
            column
            for column in FIELD_OUTPUT_COLUMNS
            if column != "Ez_V_per_m"
        )
        rows = [
            {key: value for key, value in row.items() if key in columns}
            for row in _field_rows()
        ]
        path = self._write_rows("missing.csv", rows, columns)
        with self.assertRaisesRegex(
            StationaryFieldContractError, "columns or column order"
        ):
            load_stationary_field_output_csv(path)

    def test_load_rejects_duplicate_id(self) -> None:
        rows = _field_rows()
        rows[1]["sample_id"] = rows[0]["sample_id"]
        rows[1]["field_case"] = rows[0]["field_case"]
        path = self._write_rows("duplicate.csv", rows)
        with self.assertRaisesRegex(
            StationaryFieldContractError, "must be unique"
        ):
            load_stationary_field_output_csv(path)

    def test_load_rejects_nan(self) -> None:
        rows = _field_rows()
        rows[0]["Ex_V_per_m"] = "NaN"
        path = self._write_rows("nan.csv", rows)
        with self.assertRaisesRegex(StationaryFieldContractError, "must be finite"):
            load_stationary_field_output_csv(path)

    def test_compare_rejects_coordinate_difference(self) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows("reference.csv", _field_rows())
        )
        rows = _field_rows()
        for row in rows:
            if row["sample_id"] == "p0":
                row["x_mm"] = "0.0000001"
        candidate = load_stationary_field_output_csv(
            self._write_rows("coordinate.csv", rows)
        )
        with self.assertRaisesRegex(
            StationaryFieldContractError, "coordinates differ"
        ):
            compare_stationary_field_outputs(reference, candidate)

    def test_near_zero_reference_normalization_is_null_not_infinite(
        self,
    ) -> None:
        reference = load_stationary_field_output_csv(
            self._write_rows(
                "near_zero.csv",
                _field_rows(potential_scale=1e-320, field_scale=1e-320),
            )
        )
        candidate = load_stationary_field_output_csv(
            self._write_rows("finite.csv", _field_rows())
        )
        result = compare_stationary_field_outputs(reference, candidate)
        differential = result["field_cases"]["differential"]
        self.assertIsNone(
            differential["potential"]["reference_normalized_rms"]
        )
        self.assertIsNone(
            differential["field_vector"]["reference_normalized_rms"]
        )
        for component in ("Ex", "Ey", "Ez"):
            self.assertIsNone(
                differential["field_components"][component][
                    "reference_normalized_rms"
                ]
            )

    def test_single_public_utility_boundary_generates_validates_and_compares(
        self,
    ) -> None:
        resolved_path = self.root / "resolved.json"
        plan_path = self.root / "plan.json"
        points_path = self.root / "points.csv"
        resolved_path.write_text(json.dumps(_resolved_design()), encoding="utf-8")
        plan_path.write_text(json.dumps(_sampling_plan()), encoding="utf-8")
        self.assertEqual(
            main(
                [
                    "generate",
                    "--resolved-design",
                    str(resolved_path),
                    "--sampling-plan",
                    str(plan_path),
                    "--output",
                    str(points_path),
                ]
            ),
            0,
        )
        with points_path.open(encoding="utf-8", newline="") as handle:
            point_rows = list(csv.DictReader(handle))
        self.assertEqual(
            tuple(point_rows[0]),
            ("sample_id", "region", "x_mm", "y_mm", "z_mm"),
        )

        field_path = self._write_rows("field.csv", _field_rows())
        validation_path = self.root / "validation.json"
        self.assertEqual(
            main(
                [
                    "validate",
                    "--input",
                    str(field_path),
                    "--output",
                    str(validation_path),
                ]
            ),
            0,
        )
        validation = json.loads(validation_path.read_text(encoding="utf-8"))
        self.assertEqual(validation["point_count"], 2)
        self.assertEqual(validation["row_count"], 4)

        comparison_path = self.root / "comparison.json"
        self.assertEqual(
            main(
                [
                    "compare",
                    "--reference",
                    str(field_path),
                    "--candidate",
                    str(field_path),
                    "--output",
                    str(comparison_path),
                ]
            ),
            0,
        )
        comparison = json.loads(comparison_path.read_text(encoding="utf-8"))
        self.assertEqual(comparison["status"], "INCONCLUSIVE_DIAGNOSTIC_ONLY")


if __name__ == "__main__":
    unittest.main()

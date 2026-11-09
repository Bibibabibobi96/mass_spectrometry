[CmdletBinding(DefaultParameterSetName='Run')]
param(
  [Parameter(Mandatory=$true,ParameterSetName='Run')][string]$ComsolRunDirectory,
  [Parameter(Mandatory=$true,ParameterSetName='Reference')][string]$SourceReferencePath,
  [Parameter(Mandatory=$true)][string]$InterfacePath,
  [Parameter(Mandatory=$true)][string]$OutputDir,
  [Parameter(Mandatory=$true)][string]$PythonExe
)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$code=@"
import json
import sys
from pathlib import Path
from msplatform.io.manifest_records import file_record
from msplatform.results.gas_field import read_gas_field
from msplatform.components.dual_cone_tandem_quadrupole_ion_interface.gas_runtime import export_runtime

if sys.argv[1] == "Reference":
    reference = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8-sig"))
else:
    manifest = Path(sys.argv[2]).resolve() / "run_manifest.json"
    reference = dict(manifest=file_record(manifest, "required_evidence"), product_id="gas_field")
field = read_gas_field(reference)
paths = field.data_locations
output = Path(sys.argv[4]).resolve()
export_runtime(
    paths["field_csv"], paths["field_metadata"],
    output / "gas_field_runtime.lua", output / "gas_field_manifest.json",
    paths["science"], paths["numerics"], paths["geometry"], Path(sys.argv[3]).resolve(),
)
print("SIMION_GAS_FIELD_MANIFEST=" + str(output / "gas_field_manifest.json"))
"@
$source=if($PSCmdlet.ParameterSetName-eq'Reference'){$SourceReferencePath}else{$ComsolRunDirectory}
& $PythonExe -I -B -c $code $PSCmdlet.ParameterSetName $source $InterfacePath $OutputDir
if($LASTEXITCODE-ne0){throw "Published gas runtime compilation failed with exit code $LASTEXITCODE."}

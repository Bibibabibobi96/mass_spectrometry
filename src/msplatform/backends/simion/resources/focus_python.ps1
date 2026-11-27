Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'

function Invoke-FocusFrozenPython {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$CodeRoot,
    [Parameter(Mandatory)][string]$OriginsPath,[string]$Module='',[string[]]$Arguments=@())
  # -I ignores cwd/PYTHONPATH. All installed imports use this one snapshot.
  $bootstrap=@'
import importlib,importlib.util,json,runpy,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
origins=Path(sys.argv[2])
module=sys.argv[3]
arguments=sys.argv[4:]
sys.path[:0]=[str(root/'src'),str(root)] if (root/'src').is_dir() else [str(root)]
entry_origin=None
try:
    if module:
        entry_origin=Path(importlib.util.find_spec(module).origin).resolve()
        if not entry_origin.is_relative_to(root):
            raise RuntimeError("Focus Python entry is outside its frozen package")
        sys.argv=[module,*arguments]
        runpy.run_module(module,run_name="__main__",alter_sys=True)
    else:
        for name in ("msplatform.particle_release.cylinder","msplatform.backends.simion.oa_focus_source","msplatform.workflows.oa_focus_analysis"):
            importlib.import_module(name)
        campaign=json.loads(Path(arguments[0]).read_text(encoding="utf-8-sig"))
        from msplatform.components.orthogonal_accelerator.focus_campaign import validate_campaign
        contract=json.loads((root/"src/msplatform/components/orthogonal_accelerator/component_contract.json").read_text(encoding="utf-8"))
        validate_campaign(campaign,geometry_profile=contract["geometry_profiles"][campaign["geometry_profile_id"]])
finally:
    paths={name:str(Path(value.__file__).resolve()) for name,value in sys.modules.items()
           if name.split('.')[0] == "msplatform" and getattr(value,"__file__",None)}
    if entry_origin is not None:
        paths[module]=str(entry_origin)
    if any(not Path(path).is_relative_to(root) for path in paths.values()):
        raise RuntimeError("Focus Python imported code outside its frozen package")
    fact={"module":module or "preflight","code_root":str(root),"module_paths":paths,
          "geometry_contract_path":str(root/"src/msplatform/components/orthogonal_accelerator/component_contract.json")}
    facts=json.loads(origins.read_text(encoding="utf-8")) if origins.exists() else []
    facts.append(fact)
    origins.write_text(json.dumps(facts,indent=2)+"\n",encoding="utf-8")
'@
  & $Python -I -B -c $bootstrap $CodeRoot $OriginsPath $Module @Arguments
}

function Initialize-FocusFrozenPython {
  [CmdletBinding()]
  param([Parameter(Mandatory)][string]$PackageRoot,[Parameter(Mandatory)][string]$RunConfig,
    [Parameter(Mandatory)][string]$Python,[Parameter(Mandatory)][string]$CampaignPath,
    [Parameter(Mandatory)][string[]]$InputNames)
  $config=Get-Content -LiteralPath $RunConfig -Raw -Encoding utf8|ConvertFrom-Json -AsHashtable
  $root=Split-Path -Parent $RunConfig
  $code=Join-Path $root 'inputs/code'
  $origins=Join-Path $root 'results/python_execution.json'
  $groups=@('src/msplatform')
  $enumerate=@'
import json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(root.parent))
from msplatform.execution.inputs import enumerate_python_sources
paths=enumerate_python_sources(root.parent,package_roots=['msplatform'])
paths=sorted(set(paths)|set(enumerate_python_sources(root.parent,package_roots=['msplatform'],
    provider_root='msplatform',resource_suffixes=('.schema.json',))))
print(json.dumps(paths))
'@
  $savedOutputEncoding=$OutputEncoding
  try{
    $OutputEncoding=[Text.UTF8Encoding]::new($false)
    $selection=(& $Python -X utf8 -I -B -c $enumerate $PackageRoot)-join"`n"
  }finally{$OutputEncoding=$savedOutputEncoding}
  if($LASTEXITCODE-ne0){throw 'Focus Python package enumeration failed'}
  $files=@($selection|ConvertFrom-Json|ForEach-Object{'src/'+[string]$_})
  $files+='src/msplatform/components/orthogonal_accelerator/component_contract.json'
  $files+='src/msplatform/backends/simion/resources/focus_python.ps1'
  foreach($relative in @($files|Sort-Object)){
    $destination=Join-Path $code $relative
    Copy-VerifiedRunInput (Join-Path $PackageRoot $relative.Substring('src/msplatform/'.Length)) $destination|Out-Null
    $config.inputs['python_code__'+$relative.Replace('/','__')]=$destination
  }
  $config.parameters.python_package_groups=$groups
  $config.parameters.python_code_root=$code
  foreach($name in $InputNames){
    $config.inputs[$name]=Join-Path $root ('inputs/'+$name)
  }
  $config|ConvertTo-Json -Depth 100|Set-Content -LiteralPath $RunConfig -Encoding utf8
  Invoke-FocusFrozenPython -Python $Python -CodeRoot $code -OriginsPath $origins -Arguments @($CampaignPath)
  if($LASTEXITCODE-ne0){throw 'Frozen focus Python import or geometry resource preflight failed'}
  return @{code_root=$code;origins_path=$origins}
}

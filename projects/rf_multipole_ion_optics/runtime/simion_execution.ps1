Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\..\..\common\resource_budget_support.ps1')

function Get-RfSimionStoppedWriterCompletion {
    param($HostLease,[Parameter(Mandatory)][AllowEmptyCollection()]$NativeOperations,[Parameter(Mandatory)][hashtable]$State)
    if($State.released){return $State.completion}
    $releases=@()
    if($null-ne$HostLease){
        $token=[string]$HostLease.token
        try{
            if($HostLease.inherited){
                $result=Invoke-HostResourceTransaction -StatePath $HostLease.state_path -Request @{operation='inherit';token=$token}
                if($result.status-cne'acquired'-or$result.token-cne$token){throw 'Inherited RF host grant is unconfirmed.'}
                $result=Exit-HostResourceStage -Lease $HostLease -PassThru
            }else{
                $result=Exit-HostResourceStage -Lease $HostLease -PassThru
                if($result.status-cne'released'-or$result.token-cne$token){throw 'RF host release is unconfirmed.'}
            }
        }catch{$_.Exception.Data['rf_host_release_unconfirmed']=$true;throw}
        if($NativeOperations.Count){$releases+=@{release_id='simion';completion_receipt=@{host_release=@{
            inherited=[bool]$HostLease.inherited;token=$token;result=$(if($HostLease.inherited){$result}else{@{status=[string]$result.status;token=$token}});error=$null}}}}
    }elseif($NativeOperations.Count){throw 'RF native operations lack their host owner.'}
    $State.completion=@{operations=@($NativeOperations|ForEach-Object{$_});resource_releases=@($releases)}
    $State.released=$true
    return $State.completion
}

function Set-RfSimionExecutionPhase {
    param([Parameter(Mandatory)]$Context,[AllowEmptyString()][string]$Name='')
    $now=$Context.clock.Elapsed.TotalSeconds
    if($Context.phase){
        if(-not$Context.phase_seconds.Contains($Context.phase)){$Context.phase_seconds[$Context.phase]=0.0}
        $Context.phase_seconds[$Context.phase]+=$now-$Context.phase_started
    }
    $Context.phase=$Name;$Context.phase_started=$now;$Context.elapsed_seconds=$now
}

function Protect-RfSimionContinuationEvidence {
    param([Parameter(Mandatory)][string[]]$Chain,
          [Parameter(Mandatory)][AllowEmptyCollection()][Collections.IList]$Guards)
    foreach($ancestor in $Chain){
        [void]$Guards.Add((Enter-RunTerminalConsumptionGuard -RunDirectory $ancestor))
        $manifestPath=Join-Path $ancestor 'run_manifest.json'
        $manifestSha=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash
        $manifest=Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8|ConvertFrom-Json
        $records=@($manifest.outputs)+@($manifest.inputs.PSObject.Properties|ForEach-Object{$_.Value})+@($manifest.run_config)
        $paths=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        [void]$paths.Add([IO.Path]::GetFullPath($manifestPath))
        $prefix=[IO.Path]::GetFullPath($ancestor).TrimEnd([IO.Path]::DirectorySeparatorChar)+[IO.Path]::DirectorySeparatorChar
        foreach($record in $records){
            if($null-eq$record-or-not$record.path){continue}
            $path=if([IO.Path]::IsPathRooted([string]$record.path)){[string]$record.path}else{Join-Path $ancestor ([string]$record.path)}
            $path=[IO.Path]::GetFullPath($path)
            if($path.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)-and(Test-Path -LiteralPath $path -PathType Leaf)){[void]$paths.Add($path)}
        }
        foreach($path in $paths){[void]$Guards.Add([IO.File]::Open($path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read))}
        if((Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash-ne$manifestSha){throw 'RF continuation manifest changed while acquiring guards.'}
    }
}

function Write-RfSimionPreparedBatchCompletion {
    param([Parameter(Mandatory)]$Record,[Parameter(Mandatory)]$BatchRun,
          [Parameter(Mandatory)][string]$CaseName,[Parameter(Mandatory)][string]$RunDir,
          [Parameter(Mandatory)][string]$PythonExe,[Parameter(Mandatory)][string]$RepositoryRoot,
          [Parameter(Mandatory)][AllowEmptyCollection()][Collections.Generic.List[string]]$Outputs)
    if($null-eq$Record.exit_code){throw 'RF batch writer exit is unconfirmed.'}
    if([int]$Record.exit_code-ne0){return}
    $count=[int]$BatchRun.batch.particle_id_max-[int]$BatchRun.batch.particle_id_min+1
    Push-Location $RepositoryRoot
    try{
        & $PythonExe -m projects.rf_multipole_ion_optics.runtime.simion_batch_completion `
            --stdout $Record.specification.stdout --state $BatchRun.state --summary $BatchRun.summary --particle-count $count | Out-Null
        if($LASTEXITCODE-ne0){throw 'RF prepared batch completion is invalid.'}
    }finally{Pop-Location}
    $paths=@([string]$Record.specification.stdout,[string]$BatchRun.state,[string]$BatchRun.summary)
    $relative=@($paths|ForEach-Object{
        $value=[IO.Path]::GetRelativePath($RunDir,$_).Replace('\','/')
        if($value-eq'..'-or$value.StartsWith('../')-or[IO.Path]::IsPathRooted($value)){throw 'RF completed output escapes its run.'}
        $value
    })
    $receipt=Join-Path $RunDir ('results/simion_batch_completion__{0}__batch_{1:D2}.json'-f$CaseName,[int]$BatchRun.batch.index)
    Write-RunJson -Atomic -Path $receipt -Value @{schema_version=1;role='multipole_simion_completed_batch';case=$CaseName;
        batch_index=[int]$BatchRun.batch.index;particle_id_min=[int]$BatchRun.batch.particle_id_min;
        particle_id_max=[int]$BatchRun.batch.particle_id_max;particle_count=$count;retention_class='compact';outputs=$relative}
    foreach($path in @($paths)+@($receipt)){if(-not$Outputs.Contains($path)){$Outputs.Add($path)}}
}

function Initialize-RfSimionPreparedContinuation {
    param([Parameter(Mandatory)][string]$ManifestPath,[Parameter(Mandatory)][string]$RunDir,
          [Parameter(Mandatory)][string]$ArtifactRoot,[Parameter(Mandatory)][string]$PythonExe,
          [Parameter(Mandatory)][string]$RepositoryRoot,[Parameter(Mandatory)]$RunConfig,
          [Parameter(Mandatory)][string]$RunConfigPath,[Parameter(Mandatory)][string]$CaseName,
          [Parameter(Mandatory)][string[]]$InputNames,[Parameter(Mandatory)][string]$BatchPlanPath,
          [Parameter(Mandatory)][string]$DispatchPlanPath,[string]$CapacityOwner='')
    $manifest=(Resolve-Path -LiteralPath $ManifestPath).Path
    if([IO.Path]::GetFileName($manifest)-cne'run_manifest.json'){throw 'RF continuation requires an explicit run manifest.'}
    $parent=Split-Path -Parent $manifest
    $prefix=[IO.Path]::GetFullPath((Split-Path -Parent $RunDir)).TrimEnd('\')+'\'
    if(-not$parent.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)-or$parent-ieq[IO.Path]::GetFullPath($RunDir)){
        throw 'RF continuation requires a distinct same-project run.'
    }
    $context=[pscustomobject]@{capacity=$null;guards=[Collections.Generic.List[IDisposable]]::new();units=@{};all_reused=$false;chain=@();predecessor=$parent}
    Push-Location $RepositoryRoot
    try{
        $chain=& $PythonExe -m projects.rf_multipole_ion_optics.runtime.simion_batch_continuation `
            --predecessor $parent --project $RunConfig.project --mode $RunConfig.mode
        if($LASTEXITCODE-ne0){throw 'RF continuation ancestry is invalid.'}
        $context.chain=@(($chain-join"`n")|ConvertFrom-Json)
        if(@($context.chain|Where-Object{-not[IO.Path]::GetFullPath($_).StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)}).Count){throw 'RF ancestry escapes its project.'}
        $context.capacity=Enter-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $RepositoryRoot `
            -ArtifactRoot $ArtifactRoot -RunDirectory $RunDir -CommittedNewBytes 0 -ProtectedPaths $context.chain `
            -Owner $(if($CapacityOwner){$CapacityOwner}else{$RunConfig.project})
        Protect-RfSimionContinuationEvidence -Chain $context.chain -Guards $context.guards
        $arguments=@('-m','projects.rf_multipole_ion_optics.runtime.simion_batch_continuation',
            '--predecessor',$parent,'--project',$RunConfig.project,'--run-dir',$RunDir,'--case',$CaseName,'--output-layout','prepared')
        foreach($name in $InputNames){$arguments+=@('--input',$name)}
        $planned=& $PythonExe @arguments
        if($LASTEXITCODE-ne0){throw 'RF prepared continuation identity is invalid.'}
        $plan=($planned-join"`n")|ConvertFrom-Json
        Write-RunJson -Path $BatchPlanPath -Value $plan.batch_plan -Depth 20
        foreach($unit in $plan.replay.units){if($unit.action-eq'reuse'){$context.units[[string]$unit.key]=$unit}}
        $context.all_reused=[int]$plan.replay.replay_unit_count-eq0
        if(-not$context.all_reused){
            $fixed=@('-m','common.simion.resource_scheduler','--prepare-fixed-recovery-plan',$DispatchPlanPath,
                '--fixed-batch-plan',$BatchPlanPath,'--profiles',[string]$RunConfig.inputs.simion_resource_profiles,'--output',$DispatchPlanPath)
            foreach($unit in $plan.replay.units|Where-Object{$_.action-eq'replay'}){
                if($unit.key-notmatch'\.batch_(\d+)$'){throw 'RF continuation batch key is invalid.'}
                $fixed+=@('--replay-batch-index',[string][int]$Matches[1])
            }
            & $PythonExe @fixed | Out-Null
            if($LASTEXITCODE-ne0){throw 'RF fixed continuation resource planning failed.'}
        }
        $RunConfig.inputs.continuation_predecessor_manifest=$manifest
        $RunConfig.inputs.continuation_plan=Join-Path $RunDir 'inputs/simion_whole_unit_replay_plan.json'
        $RunConfig.execution_batch_count=[int]$plan.batch_plan.batch_count
        Write-RunJson -Path $RunConfigPath -Value $RunConfig -Depth 20
        return $context
    }catch{
        $failure=$_
        foreach($guard in $context.guards){$guard.Dispose()}
        if($null-ne$context.capacity){try{Exit-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $RepositoryRoot -Session $context.capacity|Out-Null}catch{$failure.Exception.Data['capacity_release_error']=[string]$_}}
        throw $failure
    }finally{Pop-Location}
}

function Get-RfSimionPaBasisArguments {
    return @{gem2pa=@('--nogui','--noprompt','gem2pa','quad_monolithic.gem','quad_monolithic.pa#');
        refine=@('--nogui','--noprompt','refine','quad_monolithic.pa#')}
}

function New-RfSimionLayoutSeedCompanion {
    param([Parameter(Mandatory)][string]$IobPath,[Parameter(Mandatory)][string]$SeedPaPath)
    $path=[IO.Path]::ChangeExtension($IobPath,'.pa0')
    if(Test-Path -LiteralPath $path){return [pscustomobject]@{path=$path;created=$false}}
    Copy-VerifiedRunInput -Source $SeedPaPath -Destination $path|Out-Null
    return [pscustomobject]@{path=$path;created=$true}
}

function Remove-RfSimionLayoutSeedCompanion {
    param([Parameter(Mandatory)]$Companion,[Parameter(Mandatory)]$BuildObservation)
    if(-not$Companion.created){return}
    if($BuildObservation.exit_confirmed-ne$true-or$BuildObservation.returncode-ne0){
        throw 'Template companion requires confirmed successful builder exit before removal.'
    }
    # This is only the companion created by this call, never an original field.
    $item=Get-Item -LiteralPath $Companion.path
    if($item.IsReadOnly){$item.IsReadOnly=$false}
    [IO.File]::Delete($Companion.path)
}

function Initialize-RfSimionPreparedField {
    param([Parameter(Mandatory)]$Package,[Parameter(Mandatory)][string]$IdentityPath,
          [Parameter(Mandatory)][hashtable]$Preparation,[Parameter(Mandatory)]$HostLease,
          [Parameter(Mandatory)][string]$TemplateIobPath,[Parameter(Mandatory)][string]$TemplateConPath,
          [Parameter(Mandatory)][string]$PythonExe,[Parameter(Mandatory)][string]$RepositoryRoot,
          [Parameter(Mandatory)][string]$ArtifactRoot,[Parameter(Mandatory)][string]$Owner,
          [Parameter(Mandatory)][AllowEmptyCollection()][Collections.Generic.List[object]]$NativeOperations,
          [string]$SourceRunPath='',[string[]]$ExistingProtectedRuns=@(),$CapacitySession=$null,
          [string]$TemplateSeedPaPath='')
    $physicalIob=Join-Path $Package.artifact_run_dir ([IO.Path]::GetRelativePath($Package.run_dir,$Preparation.IobPath))
    $context=[pscustomobject]@{iob_path=$physicalIob;checkpoint_path=$null;producer_manifest=$null;
        guard=$null;capacity=$CapacitySession;owns_capacity=$false;output_paths=@();source_reused=$false}
    $layoutArguments=$Preparation.Clone()
    # SIMION saves relative PA references against the IOB save location. Bind
    # both save and inspect to its permanent location, never the execution alias.
    $layoutArguments.IobPath=$physicalIob
    $layoutArguments.NativeOperations=$NativeOperations
    if($TemplateSeedPaPath){$layoutArguments.TemplateSeedPaPath=$TemplateSeedPaPath}
    try{
        $needsLayout=$true
        if($SourceRunPath){
            $source=Read-RfSimionFieldCheckpoint -SourceRunPath $SourceRunPath -IdentityPath $IdentityPath `
                -ProgramSourcePath $Preparation.ProgramSourcePath -TemplateIobPath $TemplateIobPath -TemplateConPath $TemplateConPath `
                -Python $PythonExe -RepoRoot $RepositoryRoot
            if($null-ne$CapacitySession){
                $updated=Update-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $RepositoryRoot -Session $CapacitySession `
                    -ProtectedPaths @(@($CapacitySession.protected_paths)+@($source.protected_paths)|Select-Object -Unique)
                $context.capacity=$updated.session
            }else{
                $context.capacity=Enter-ArtifactWorkflowCapacitySession -Python $PythonExe -RepoRoot $RepositoryRoot `
                    -ArtifactRoot $ArtifactRoot -RunDirectory $Package.artifact_run_dir -CommittedNewBytes 0 `
                    -ProtectedPaths @($source.protected_paths) -Owner $Owner
                $context.owns_capacity=$true
            }
            $context.guard=Protect-RfSimionFieldCheckpoint -Checkpoint $source -ExistingProtectedRuns $ExistingProtectedRuns
            $context.checkpoint_path=$source.checkpoint_path;$context.producer_manifest=$source.producer_manifest;$context.source_reused=$true
            $layoutArguments.ControllerPath=[string]$source.controller_path
            $needsLayout=[bool]$source.requires_iob_rebind
            if(-not$needsLayout){$context.iob_path=[string]$source.iob_path}
        }else{
            Initialize-RfSimionPaBasis -SimionExe $Preparation.SimionExe -CandidateDir $Preparation.CandidateDir `
                -HostLease $HostLease -NativeOperations $NativeOperations | Write-Host
            $checkpoint=Write-RfSimionFieldCheckpoint -RunDirectory $Package.artifact_run_dir -IdentityPath $IdentityPath `
                -IobPath $physicalIob -NativeOperations $NativeOperations -Python $PythonExe -RepoRoot $RepositoryRoot
            $context.checkpoint_path=$checkpoint.checkpoint_path;$context.output_paths=@($checkpoint.output_paths)
            $layoutArguments.ControllerPath=[IO.Path]::ChangeExtension($physicalIob,'.pa0')
        }
        if($needsLayout){
            Copy-VerifiedRunInput -Source $TemplateIobPath -Destination $physicalIob|Out-Null
            Copy-VerifiedRunInput -Source $TemplateConPath -Destination ([IO.Path]::ChangeExtension($physicalIob,'.con'))|Out-Null
            Initialize-RfSimionPreparedBatch @layoutArguments | Write-Host
            if(-not$SourceRunPath){
                $checkpoint=Write-RfSimionFieldCheckpoint -RunDirectory $Package.artifact_run_dir -IdentityPath $IdentityPath `
                    -IobPath $physicalIob -NativeOperations $NativeOperations -Python $PythonExe -RepoRoot $RepositoryRoot
                $context.output_paths=@($context.output_paths)+@($checkpoint.output_paths)|Select-Object -Unique
            }
        }
        return $context
    }catch{
        $_.Exception.Data['rf_field_context']=$context
        throw
    }
}

function Invoke-RfSimionPreparationProcess {
    param([Parameter(Mandatory)][string]$Name,[Parameter(Mandatory)][string]$SimionExe,
          [Parameter(Mandatory)][string[]]$ArgumentList,[Parameter(Mandatory)][string]$CandidateDir,
          [Parameter(Mandatory)][string]$RunDir,[Parameter(Mandatory)][string]$Stdout,[Parameter(Mandatory)][string]$Stderr,
          [hashtable]$Environment=@{},[AllowEmptyCollection()][Collections.Generic.List[object]]$NativeOperations=$null,
          [switch]$AllowNonzeroExit)
    $operation=[ordered]@{operation_id=$Name;resource_release_id='simion';observation=@{exit_confirmed=$false;returncode=$null}}
    if($null-ne$NativeOperations){$NativeOperations.Add($operation)}
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Stdout)|Out-Null
    Write-Host "RF_NATIVE_OPERATION=START NAME=$Name"
    try{
        $result=Invoke-ResourceBudgetedProcess -Limits $null -RunDir $RunDir -UsagePath (Join-Path $RunDir ('results/'+$Name+'_resource_usage.json')) `
            -FilePath $SimionExe -ArgumentList $ArgumentList -WorkingDirectory $CandidateDir `
            -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr -Environment $Environment
    }catch{
        # A root handle alone cannot attest unknown descendants. The existing
        # process owner must return normally before this boundary can seal PA.
        $_.Exception.Data['simion_wave_writer_completion_confirmed']=$false
        throw
    }
    if($result.resource_budget_exceeded){
        try{throw "SIMION $Name stopped at the public physical-memory danger boundary."}
        catch{$_.Exception.Data['simion_wave_writer_completion_confirmed']=$false;throw}
    }
    $operation.observation=@{exit_confirmed=$true;returncode=[int]$result.exit_code;
        process_id=[int]$result.root_process_id;process_started_at_utc_ticks=[long]$result.root_process_started_at_utc_ticks}
    Write-Host "RF_NATIVE_OPERATION=COMPLETE NAME=$Name EXIT_CODE=$($result.exit_code)"
    if([int]$result.exit_code-ne0-and-not$AllowNonzeroExit){
        try{throw "SIMION $Name failed with exit code $($result.exit_code)."}
        catch{$_.Exception.Data['simion_wave_writer_completion_confirmed']=$true;throw}
    }
    return $result
}

function Initialize-RfSimionPaBasis {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        $HostLease = $null,
        [AllowEmptyCollection()][Collections.Generic.List[object]]$NativeOperations=$null
    )

    Push-Location $CandidateDir
    try {
        $arguments=Get-RfSimionPaBasisArguments
        $run=Split-Path -Parent $CandidateDir;$logs=Join-Path $run 'logs'
        $null=Invoke-RfSimionPreparationProcess -Name gem2pa -SimionExe $SimionExe -ArgumentList $arguments.gem2pa `
            -CandidateDir $CandidateDir -RunDir $run -Stdout (Join-Path $logs 'simion_gem2pa_stdout.txt') `
            -Stderr (Join-Path $logs 'simion_gem2pa_stderr.txt') -NativeOperations $NativeOperations
        if ($null -ne $HostLease) {
            $HostLease = Update-HostResourceStage -Lease $HostLease -Stage pa_refine `
              -Budget (Get-HostResourceBudget -Role SIMION -Stage pa_refine) -RetainedMemoryBytes 0
        } else { Assert-HostResourceHeavyStage }
        $null=Invoke-RfSimionPreparationProcess -Name refine -SimionExe $SimionExe -ArgumentList $arguments.refine `
            -CandidateDir $CandidateDir -RunDir $run -Stdout (Join-Path $logs 'simion_refine_stdout.txt') `
            -Stderr (Join-Path $logs 'simion_refine_stderr.txt') -NativeOperations $NativeOperations
        if ($null -ne $HostLease) {
            $HostLease = Update-HostResourceStage -Lease $HostLease -Stage prepare `
              -Budget (Get-HostResourceBudget -Role SIMION -Stage prepare) -RetainedMemoryBytes 0
        }
    } finally {
        Pop-Location
    }
}

function Initialize-RfSimionPreparedBatch {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$Fly2Path,
        [Parameter(Mandatory = $true)][string]$IobBuilderScript,
        [Parameter(Mandatory = $true)][string]$ProgramSourcePath,
        [Parameter(Mandatory = $true)][string]$RunConfigLua,
        [Parameter(Mandatory = $true)][string]$InspectScript,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][string]$RfDriveKernelPath,
        [string]$ControllerPath='',
        [string]$TemplateSeedPaPath='',
        [AllowEmptyCollection()][Collections.Generic.List[object]]$NativeOperations=$null
    )

    $iobStdoutPath = Join-Path $LogDir 'simion_iob_stdout.txt'
    $iobStderrPath = Join-Path $LogDir 'simion_iob_stderr.txt'
    $iobExitCodePath = Join-Path $LogDir 'simion_iob_exit_code.txt'
    $stdoutPath = Join-Path $LogDir 'simion_stdout.txt'
    $stderrPath = Join-Path $LogDir 'simion_stderr.txt'
    Push-Location $CandidateDir
    try {
        $companion=$null
        if($ControllerPath-and-not(Test-Path -LiteralPath ([IO.Path]::ChangeExtension($IobPath,'.pa0')))){
            if(-not$TemplateSeedPaPath){throw 'Rebinding a field requires the registered template PA companion.'}
            $companion=New-RfSimionLayoutSeedCompanion -IobPath $IobPath -SeedPaPath $TemplateSeedPaPath
        }
        $buildArguments=@('--nogui','--noprompt','lua',$IobBuilderScript,$IobPath,$ProgramSourcePath,$Fly2Path)
        if($ControllerPath){$buildArguments+=@($ControllerPath)}
        $environment=@{MULTIPOLE_SIMION_RUN_CONFIG_LUA=$RunConfigLua;MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA=$RfDriveKernelPath;
            RFQUAD_SIMION_REFERENCE_REPORT=$IobReport;RFQUAD_SIMION_REFERENCE_IOB=$IobPath}
        $run=Split-Path -Parent $CandidateDir
        $built=Invoke-RfSimionPreparationProcess -Name build_runtime_iob -SimionExe $SimionExe -ArgumentList $buildArguments `
            -CandidateDir $CandidateDir -RunDir $run -Stdout (Join-Path $LogDir 'simion_iob_build_stdout.txt') `
            -Stderr (Join-Path $LogDir 'simion_iob_build_stderr.txt') -Environment $environment -NativeOperations $NativeOperations
        if($null-ne$companion){
            Remove-RfSimionLayoutSeedCompanion -Companion $companion -BuildObservation @{exit_confirmed=$true;returncode=$built.exit_code}
        }
        Start-Sleep -Milliseconds 500

        'NOT_STARTED' | Set-Content -LiteralPath $iobExitCodePath -Encoding ASCII
        $inspectArguments = @('--nogui','--noprompt','lua',$InspectScript)
        $inspectProcess=Invoke-RfSimionPreparationProcess -Name inspect_runtime_iob -SimionExe $SimionExe -ArgumentList $inspectArguments `
            -CandidateDir $CandidateDir -RunDir $run -Stdout $iobStdoutPath -Stderr $iobStderrPath `
            -Environment $environment -NativeOperations $NativeOperations -AllowNonzeroExit
        [string]$inspectProcess.exit_code |
            Set-Content -LiteralPath $iobExitCodePath -Encoding ASCII
        Get-Content -LiteralPath $iobStdoutPath -Encoding UTF8 | Write-Host
        if ((Get-Item -LiteralPath $iobStderrPath).Length -gt 0) {
            Get-Content -LiteralPath $iobStderrPath -Encoding UTF8 | Write-Host
        }
        if ($inspectProcess.exit_code -ne 0) {
            throw "SIMION IOB runtime contract failed with exit code $($inspectProcess.exit_code)."
        }
        Start-Sleep -Milliseconds 500

    } finally {
        Pop-Location
    }
}

function New-RfSimionFlyProcessSpecification {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$Fly2Path,
        [Parameter(Mandatory = $true)][string]$RunConfigLua,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod,
        [Parameter(Mandatory = $true)][string]$RfDriveKernelPath
    )

    if ($TrajectoryQuality -le 0 -or $RfStepsPerPeriod -le 0) {
        throw 'SIMION launch numerics must be positive.'
    }
    [pscustomobject]@{
        name = $Name
        file_path = $SimionExe
        working_directory = $CandidateDir
        argument_list = @(
            '--nogui','--noprompt','fly',
            '--trajectory-quality',[string]$TrajectoryQuality,
            '--particles',$Fly2Path,
            '--programs','1',
            '--retain-trajectories','0',
            '--adjustable',"transport_rf_steps_per_period=$RfStepsPerPeriod",
            $IobPath
        )
        stdout = Join-Path $LogDir 'simion_stdout.txt'
        stderr = Join-Path $LogDir 'simion_stderr.txt'
        environment = @{
            MULTIPOLE_SIMION_RUN_CONFIG_LUA = $RunConfigLua
            MULTIPOLE_SIMION_RF_DRIVE_KERNEL_LUA = $RfDriveKernelPath
            RFQUAD_SIMION_REFERENCE_REPORT = $IobReport
            RFQUAD_SIMION_REFERENCE_IOB = $IobPath
        }
    }
}

function Get-RfSimionFlyArgumentIdentity {
    param([Parameter(Mandatory)]$CoreConfig)
    # Keep actual native switches while removing owner-specific locations.
    $native=New-RfSimionFlyProcessSpecification -Name '@case' -SimionExe '@simion' -CandidateDir '@directory' `
        -IobPath '@iob' -Fly2Path '@fly2' -RunConfigLua '@config' -IobReport '@report' -LogDir '.' `
        -TrajectoryQuality ([int]$CoreConfig.trajectory_quality) -RfStepsPerPeriod ([int]$CoreConfig.rf_steps_per_period) -RfDriveKernelPath '@kernel'
    return @($native.argument_list)
}

function Invoke-RfSimionParticleBatchWave {
    [CmdletBinding()]
    param(
        [AllowNull()]$HostLease,
        [Parameter(Mandatory = $true)][string]$SimionExe,
        [Parameter(Mandatory = $true)][string]$CandidateDir,
        [Parameter(Mandatory = $true)][string]$IobPath,
        [Parameter(Mandatory = $true)][string]$RootFly2Path,
        [Parameter(Mandatory = $true)][string]$IobBuilderScript,
        [Parameter(Mandatory = $true)][string]$ProgramSourcePath,
        [Parameter(Mandatory = $true)][string]$RootRunConfigLua,
        [Parameter(Mandatory = $true)][string]$InspectScript,
        [Parameter(Mandatory = $true)][string]$IobReport,
        [Parameter(Mandatory = $true)][string]$LogDir,
        [Parameter(Mandatory = $true)][int]$TrajectoryQuality,
        [Parameter(Mandatory = $true)][int]$RfStepsPerPeriod,
        [Parameter(Mandatory = $true)][object[]]$BatchRuns,
        [Parameter(Mandatory = $true)][string]$BatchPlanPath,
        [Parameter(Mandatory = $true)][string]$DispatchPlanPath,
        [Parameter(Mandatory = $true)][string]$RunDir,
        [Parameter(Mandatory = $true)][string]$UsagePath,
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        $FirstSpecification = $null,
        [scriptblock]$Replan = $null,
        [scriptblock]$PrepareAfterObservation = $null,
        [switch]$Prepared,
        [hashtable]$ContinuationUnits=@{},
        [string]$CaseName='',
        [Collections.Generic.List[string]]$CompletionOutputs=$null,
        [Collections.Generic.List[object]]$NativeOperations=$null,
        [string]$RfDriveKernelPath=''
    )

    if ($BatchRuns.Count -eq 0) { throw 'SIMION particle batch wave requires at least one batch.' }
    $pendingRuns=@($BatchRuns|Where-Object{$ContinuationUnits.Count-eq0-or-not$ContinuationUnits.ContainsKey(('{0}.batch_{1:D2}'-f$CaseName,[int]$_.batch.index))})
    foreach($batchRun in $(if($ContinuationUnits.Count){$BatchRuns}else{@()})){
        $key=('{0}.batch_{1:D2}'-f$CaseName,[int]$batchRun.batch.index)
        if(-not$ContinuationUnits.ContainsKey($key)){continue}
        $paths=@($ContinuationUnits[$key].terminal_outputs|ForEach-Object{[string]$_.path})
        foreach($kind in @('state','summary')){
            $leaf=[IO.Path]::GetFileName([string]$batchRun.$kind)
            $matches=@($paths|Where-Object{[IO.Path]::GetFileName($_)-ceq$leaf})
            if($matches.Count-ne1){throw "RF reused $kind output is ambiguous."}
            $batchRun.$kind=$matches[0]
        }
    }
    if (-not $Prepared -and $pendingRuns.Count) {
        Initialize-RfSimionPaBasis -SimionExe $SimionExe -CandidateDir $CandidateDir -HostLease $HostLease | Write-Host
        Initialize-RfSimionPreparedBatch -SimionExe $SimionExe -CandidateDir $CandidateDir `
            -IobPath $IobPath -Fly2Path $RootFly2Path -IobBuilderScript $IobBuilderScript `
            -ProgramSourcePath $ProgramSourcePath -RunConfigLua $RootRunConfigLua `
            -InspectScript $InspectScript -IobReport $IobReport -LogDir $LogDir -RfDriveKernelPath $RfDriveKernelPath | Write-Host
    }
    if (-not $Prepared -and $pendingRuns.Count) {
        $HostLease = Update-HostResourceStage -Lease $HostLease -Stage flight `
          -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
    }
    $batchState=[pscustomobject]@{runs=@($BatchRuns)}
    $prepare = {
        param($formal)
        $preparedBatches = if ($null -ne $formal) { @(& $PrepareAfterObservation $formal) } else { @($BatchRuns) }
        if ($preparedBatches.Count -eq 0) { throw 'SIMION particle batch preparation returned no batches.' }
        $batchState.runs=@($preparedBatches)
        $specifications = @($preparedBatches | Where-Object{$ContinuationUnits.Count-eq0-or-not$ContinuationUnits.ContainsKey(('{0}.batch_{1:D2}'-f$CaseName,[int]$_.batch.index))} | ForEach-Object {
            $specification=New-RfSimionFlyProcessSpecification -Name ([string]$_.name) `
                -SimionExe $SimionExe -CandidateDir $CandidateDir -IobPath ([string]$_.config.iob) `
                -Fly2Path ([string]$_.config.fly2) -RunConfigLua ([string]$_.lua) -IobReport $IobReport `
                -LogDir ([string]$_.log_dir) -TrajectoryQuality ([int]$_.config.trajectory_quality) `
                -RfStepsPerPeriod ([int]$_.config.rf_steps_per_period) -RfDriveKernelPath $RfDriveKernelPath
            $specification|Add-Member -NotePropertyName scheduler_batch -NotePropertyValue $_.batch
            $specification
        })
        if ($null -ne $formal) { $specifications = @($specifications | Where-Object{$_.name-cne$formal.process_record.specification.name}) }
        return [pscustomobject]@{pending=$specifications;batch_runs=$preparedBatches}
    }
    $complete={
        param($record)
        if($null-ne$NativeOperations){
            if($null-eq$record.exit_code){throw 'RF Fly writer exit is unconfirmed.'}
            $NativeOperations.Add(@{operation_id=('fly:'+ [string]$record.specification.name);resource_release_id='simion';
                observation=@{exit_confirmed=$true;returncode=[int]$record.exit_code;
                    process_id=[int]$record.root_process_id;process_started_at_utc_ticks=[long]$record.root_process_started_at_utc_ticks}})
        }
        if(-not$CaseName){return}
        $matches=@($batchState.runs|Where-Object{$_.name-ceq$record.specification.name})
        if($matches.Count-ne1){throw 'RF completed worker is outside its frozen batch plan.'}
        Write-RfSimionPreparedBatchCompletion -Record $record -BatchRun $matches[0] -CaseName $CaseName `
            -RunDir $RunDir -PythonExe $PythonExe -RepositoryRoot $RepositoryRoot -Outputs $CompletionOutputs
    }
    $receipt = Invoke-SimionBatchPhase -DispatchPlanPath $DispatchPlanPath `
        -RunDir $RunDir -UsagePath $UsagePath -PrepareRemaining $prepare `
        -FirstSpecification $FirstSpecification -Replan $Replan -OnProcessCompleted $complete
    $BatchRuns = @($receipt.prepared.batch_runs)
    if ($receipt.resource_budget_exceeded) {
        throw 'SIMION particle batch wave reached sustained critical memory pressure.'
    }
    $failed = @($receipt.processes | Where-Object { $null -ne $_.exit_code -and [int]$_.exit_code -ne 0 })
    if ($failed.Count -gt 0) { throw "SIMION particle batch wave failed: $($failed.name -join ', ')" }
    Push-Location $RepositoryRoot
    try {
        foreach ($merge in @(@{output = $BatchRuns[0].merged_state; property = 'state'}, @{output = $BatchRuns[0].merged_trajectory; property = 'trajectory'})) {
            if($merge.property-eq'trajectory'-and$ContinuationUnits.Count){continue}
            if($BatchRuns.Count-eq1-and[IO.Path]::GetFullPath($BatchRuns[0].($merge.property))-ieq[IO.Path]::GetFullPath($merge.output)){continue}
            $arguments = @('-m','common.simion.particle_batching','--merge-rebase-csv','--output',$merge.output)
            foreach ($batchRun in $BatchRuns) {
                $arguments += @('--batch-csv',$batchRun.($merge.property),[string]$batchRun.batch.simion_particle_id_offset)
            }
            & $PythonExe @arguments | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'SIMION shared particle CSV merge failed.' }
        }
        $summaryArguments = @('-m','common.simion.particle_batching','--merge-summaries',
            '--batch-plan',$BatchPlanPath,'--output',$BatchRuns[0].merged_summary)
        foreach ($batchRun in $BatchRuns) { $summaryArguments += @('--batch-summary',$batchRun.summary) }
        if($BatchRuns.Count-ne1-or[IO.Path]::GetFullPath($BatchRuns[0].summary)-ine[IO.Path]::GetFullPath($BatchRuns[0].merged_summary)){
            & $PythonExe @summaryArguments | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'SIMION shared summary merge failed.' }
        }
    } finally {
        Pop-Location
    }
    return $receipt
}

function Update-RfSimionDispatchAfterFormalObservation {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$RepositoryRoot,
        [Parameter(Mandatory = $true)][string]$DispatchRequestPath,
        [Parameter(Mandatory = $true)][string]$ResourceProfilesPath,
        [Parameter(Mandatory = $true)][string]$DispatchPlanPath,
        [Parameter(Mandatory = $true)][string]$BatchPlanPath,
        [Parameter(Mandatory = $true)]$Observation
    )
    if ([int64]$Observation.observed_peak_process_tree_working_set_bytes -lt 1) {
        throw 'The first formal SIMION batch did not produce a usable resource observation.'
    }
    $arguments = @(
        '-m','common.simion.resource_scheduler','--request',$DispatchRequestPath,
        '--profiles',$ResourceProfilesPath,'--output',$DispatchPlanPath,
        '--available-memory-bytes',([string]$Observation.available_memory_bytes),
        '--total-physical-memory-bytes',([string]$Observation.total_physical_memory_bytes),
        '--observed-formal-peak-bytes',([string]$Observation.observed_peak_process_tree_working_set_bytes),
        '--observed-formal-cpu-percent',([string]$Observation.observed_process_cpu_percent),
        '--observed-background-cpu-percent',([string]$Observation.observed_background_cpu_percent)
    )
    if ($Observation.completed_naturally) { $arguments += '--first-batch-completed' }
    Push-Location $RepositoryRoot
    try {
        & $PythonExe @arguments | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'SIMION formal-first dispatch replanning failed.' }
        & $PythonExe -m common.simion.particle_batching --from-dispatch-plan $DispatchPlanPath `
            --output $BatchPlanPath | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'SIMION formal-first particle batch planning failed.' }
    } finally {
        Pop-Location
    }
    return [pscustomobject]@{
        dispatch = Get-Content -LiteralPath $DispatchPlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
        batches = Get-Content -LiteralPath $BatchPlanPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
}

function Invoke-RfSimionAdaptiveBatchWave {
    <# Preserve the first formal batch across replanning; workflows own batch inputs. #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][hashtable]$WaveArguments,
        [Parameter(Mandatory)][ref]$BatchRuns,
        [Parameter(Mandatory)]$DispatchPlan,
        [Parameter(Mandatory)][string]$DispatchRequestPath,
        [Parameter(Mandatory)][string]$ResourceProfilesPath,
        [Parameter(Mandatory)][scriptblock]$PrepareReplannedBatches,
        [Parameter(Mandatory)]$RunConfig,
        [Parameter(Mandatory)][string]$RunConfigPath
    )
    $arguments = $WaveArguments.Clone()
    $continuing=$arguments.ContainsKey('ContinuationRequested')-and[bool]$arguments.ContinuationRequested
    $arguments.Remove('ContinuationRequested')
    $batchRunsRef = $BatchRuns
    $missing=@($arguments.BatchRuns|Where-Object{-not$arguments.ContainsKey('ContinuationUnits')-or
        -not$arguments.ContinuationUnits.ContainsKey(('{0}.batch_{1:D2}'-f$arguments.CaseName,[int]$_.batch.index))})
    $observed = $missing.Count-gt0-and[string]$DispatchPlan.estimation.kind -eq 'formal_first_batch_observation'
    if ($observed) {
        if(-not$arguments.ContainsKey('Prepared')-or-not[bool]$arguments.Prepared){
        Initialize-RfSimionPaBasis -SimionExe $arguments.SimionExe -CandidateDir $arguments.CandidateDir -HostLease $arguments.HostLease | Write-Host
        Initialize-RfSimionPreparedBatch -SimionExe $arguments.SimionExe -CandidateDir $arguments.CandidateDir `
            -IobPath $arguments.IobPath -Fly2Path $arguments.RootFly2Path -IobBuilderScript $arguments.IobBuilderScript `
            -ProgramSourcePath $arguments.ProgramSourcePath -RunConfigLua $arguments.RootRunConfigLua `
            -InspectScript $arguments.InspectScript -IobReport $arguments.IobReport -LogDir $arguments.LogDir -RfDriveKernelPath $arguments.RfDriveKernelPath | Write-Host
        }
        $arguments.HostLease = Update-HostResourceStage -Lease $arguments.HostLease -Stage flight `
            -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
        $first = if($continuing){@($missing|Sort-Object -Descending -Property @{Expression={[int]$_.batch.particle_id_max-[int]$_.batch.particle_id_min+1}})[0]}else{$arguments.BatchRuns[0]}
        $spec = New-RfSimionFlyProcessSpecification -Name $first.name `
            -SimionExe $arguments.SimionExe -CandidateDir $arguments.CandidateDir -IobPath $first.config.iob `
            -Fly2Path $first.config.fly2 -RunConfigLua $first.lua -IobReport $arguments.IobReport -LogDir $first.log_dir `
            -TrajectoryQuality $first.config.trajectory_quality -RfStepsPerPeriod $first.config.rf_steps_per_period -RfDriveKernelPath $arguments.RfDriveKernelPath
        if($first.PSObject.Properties.Name-contains'batch'-or($first-is[Collections.IDictionary]-and$first.Contains('batch'))){
            $spec|Add-Member -NotePropertyName scheduler_batch -NotePropertyValue $first.batch
        }
        $replanState = [pscustomobject]@{batches = @()}
        $replan = {
        param($observation)
        if($continuing){
            $calibrate=@('-m','common.simion.resource_scheduler','--recovered-missing-plan',$arguments.DispatchPlanPath,
                '--output',$arguments.DispatchPlanPath,'--available-memory-bytes',[string]$observation.available_memory_bytes,
                '--total-physical-memory-bytes',[string]$observation.total_physical_memory_bytes,
                '--observed-formal-peak-bytes',[string]$observation.observed_peak_process_tree_working_set_bytes,
                '--observed-formal-cpu-percent',[string]$observation.observed_process_cpu_percent,
                '--observed-background-cpu-percent',[string]$observation.observed_background_cpu_percent)
            if($observation.completed_naturally){$calibrate+='--first-batch-completed'}
            Push-Location $arguments.RepositoryRoot
            try{& $arguments.PythonExe @calibrate|Out-Null;if($LASTEXITCODE-ne0){throw 'RF missing-batch observation failed.'}}finally{Pop-Location}
            $replanState.batches=@($arguments.BatchRuns)
            return
        }
        $replanned = Update-RfSimionDispatchAfterFormalObservation `
            -PythonExe $arguments.PythonExe -RepositoryRoot $arguments.RepositoryRoot `
            -DispatchRequestPath $DispatchRequestPath -ResourceProfilesPath $ResourceProfilesPath `
            -DispatchPlanPath $arguments.DispatchPlanPath -BatchPlanPath $arguments.BatchPlanPath `
            -Observation $observation
        $replanState.batches = @(& $PrepareReplannedBatches $replanned.batches)
        $batchRunsRef.Value = $replanState.batches
        $RunConfig.execution_batch_count = [int]$replanned.batches.batch_count
        $RunConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $RunConfigPath -Encoding UTF8
        }
        $arguments.FirstSpecification = $spec
        $arguments.Replan = $replan
        $arguments.PrepareAfterObservation = { param($formal) return @($replanState.batches) }
        $arguments.Prepared = $true
    }
    elseif($missing.Count-gt0-and$arguments.ContainsKey('Prepared')-and[bool]$arguments.Prepared){
        $arguments.HostLease=Update-HostResourceStage -Lease $arguments.HostLease -Stage flight `
            -Budget (Get-HostResourceBudget -Role SIMION -Stage flight) -RetainedMemoryBytes 0
    }
    $receipt = Invoke-RfSimionParticleBatchWave @arguments
    $lease=$arguments.HostLease
    if($null-ne$lease){
        $role=if($missing.Count){'SIMION'}else{'GATE'}
        $lease = Update-HostResourceStage -Lease $lease -Stage postprocess `
            -Budget (Get-HostResourceBudget -Role $role -Stage postprocess) -RetainedMemoryBytes 0
        if($missing.Count){Complete-ResourceUsage -RunDir $arguments.RunDir -UsagePath $arguments.UsagePath | Out-Null}
    }
    $profile = $null
    if ($observed -and -not$continuing) {
        $profile = Join-Path (Split-Path -Parent $arguments.UsagePath) 'simion_resource_profile.json'
        Push-Location $arguments.RepositoryRoot
        try {
            & $arguments.PythonExe -m common.simion.resource_profile publish --run-id $RunConfig.run_id `
                --resource-usage $arguments.UsagePath --dispatch-plan $arguments.DispatchPlanPath --output $profile | Write-Host
            if ($LASTEXITCODE -ne 0) { throw 'SIMION resource profile publication failed.' }
        } finally { Pop-Location }
    }
    return [pscustomobject]@{
        receipt = $receipt; lease = $lease; batches = $BatchRuns.Value; resource_profile = $profile
    }
}

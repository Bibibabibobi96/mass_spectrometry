Set-StrictMode -Version Latest

function Assert-RfTransportParticleTableIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ComsolParticlePath,
        [Parameter(Mandatory = $true)][string]$SimionParticlePath,
        [string]$ExplicitParticlePath = ''
    )

    $comsolPath = [IO.Path]::GetFullPath($ComsolParticlePath)
    $simionPath = [IO.Path]::GetFullPath($SimionParticlePath)
    $comsolHash = (Get-FileHash -LiteralPath $comsolPath -Algorithm SHA256).Hash
    $simionHash = (Get-FileHash -LiteralPath $simionPath -Algorithm SHA256).Hash
    if ($comsolHash -ne $simionHash) {
        throw 'COMSOL and SIMION particle table contents differ.'
    }

    $selectedPath = if ([string]::IsNullOrWhiteSpace($ExplicitParticlePath)) {
        $comsolPath
    } else {
        [IO.Path]::GetFullPath($ExplicitParticlePath)
    }
    $selectedHash = (Get-FileHash -LiteralPath $selectedPath -Algorithm SHA256).Hash
    if ($selectedHash -ne $comsolHash) {
        throw 'Explicit particle table contents differ from the solver run configs.'
    }

    [pscustomobject]@{
        path = $selectedPath
        sha256 = $comsolHash
    }
}

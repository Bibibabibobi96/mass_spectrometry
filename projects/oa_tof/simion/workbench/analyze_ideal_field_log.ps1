param(
  [Parameter(Mandatory = $true)][string]$Log,
  [Parameter(Mandatory = $true)][string]$IonFile,
  [Parameter(Mandatory = $true)][string]$Mode,
  [Parameter(Mandatory = $true)][string]$Distribution,
  [double]$DetectorRadiusMm = 40,
  [string]$ParticleCsv = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$inv = [Globalization.CultureInfo]::InvariantCulture

function Convert-InvariantDouble([string]$Text) {
  return [double]::Parse($Text, [Globalization.NumberStyles]::Float, $inv)
}

function Get-Mean($Values) {
  $a = @($Values)
  if ($a.Count -eq 0) { return [double]::NaN }
  return ($a | Measure-Object -Average).Average
}

function Get-SampleStd($Values) {
  $a = @($Values)
  if ($a.Count -lt 2) { return [double]::NaN }
  $mean = Get-Mean $a
  $sum = 0.0
  foreach ($v in $a) { $sum += ($v - $mean) * ($v - $mean) }
  return [Math]::Sqrt($sum / ($a.Count - 1))
}

function Get-Correlation($X, $Y) {
  $xa = @($X); $ya = @($Y)
  if ($xa.Count -ne $ya.Count -or $xa.Count -lt 2) { return [double]::NaN }
  $mx = Get-Mean $xa; $my = Get-Mean $ya
  $sxx = 0.0; $syy = 0.0; $sxy = 0.0
  for ($i = 0; $i -lt $xa.Count; $i++) {
    $dx = $xa[$i] - $mx; $dy = $ya[$i] - $my
    $sxx += $dx * $dx; $syy += $dy * $dy; $sxy += $dx * $dy
  }
  if ($sxx -le 0 -or $syy -le 0) { return [double]::NaN }
  return $sxy / [Math]::Sqrt($sxx * $syy)
}

$initial = @{}
$ionNumber = 0
foreach ($line in Get-Content -LiteralPath $IonFile) {
  if ([string]::IsNullOrWhiteSpace($line)) { continue }
  $ionNumber++
  $c = $line.Split(',')
  if ($c.Count -lt 9) { throw "Malformed ION line $ionNumber in $IonFile" }
  $initial[$ionNumber] = [pscustomobject]@{
    MassAmu = Convert-InvariantDouble $c[1]
    ChargeState = [int](Convert-InvariantDouble $c[2])
    X0Mm = Convert-InvariantDouble $c[3]
    Y0Mm = Convert-InvariantDouble $c[4]
    Z0Mm = Convert-InvariantDouble $c[5]
    EnergyEv = Convert-InvariantDouble $c[8]
  }
}

$number = '[-+0-9.eE]+'
$pattern = "TRACE: detector_crossing ion=(\d+) t=($number) x=($number) y=($number) z=($number) r=($number) zmax=($number)"
$rows = [Collections.Generic.List[object]]::new()
foreach ($line in Get-Content -LiteralPath $Log) {
  if ($line -notmatch $pattern) { continue }
  $n = [int]$Matches[1]
  if (-not $initial.ContainsKey($n)) { throw "Detector crossing references ion $n absent from $IonFile" }
  $p = $initial[$n]
  $r = Convert-InvariantDouble $Matches[6]
  $rows.Add([pscustomobject]@{
    Mode = $Mode; Distribution = $Distribution; Ion = $n
    MassAmu = $p.MassAmu; ChargeState = $p.ChargeState
    X0Mm = $p.X0Mm; Y0Mm = $p.Y0Mm; Z0Mm = $p.Z0Mm; EnergyEv = $p.EnergyEv
    TofUs = Convert-InvariantDouble $Matches[2]
    XMm = Convert-InvariantDouble $Matches[3]
    YMm = Convert-InvariantDouble $Matches[4]
    RadiusMm = $r
    ZmaxMm = Convert-InvariantDouble $Matches[7]
    Hit = ($r -le $DetectorRadiusMm)
  })
}

if ($rows.Count -eq 0) { throw "No detector_crossing records found in $Log" }
$uniqueIons = @($rows | Select-Object -ExpandProperty Ion -Unique)
if ($rows.Count -ne $initial.Count -or $uniqueIons.Count -ne $initial.Count) {
  throw "Incomplete detector-plane census in $Log`: emitted=$($initial.Count), crossings=$($rows.Count), unique_ions=$($uniqueIons.Count)"
}
if ($ParticleCsv) {
  $parent = Split-Path -Parent $ParticleCsv
  if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
  $rows | Sort-Object Ion | Export-Csv -LiteralPath $ParticleCsv -NoTypeInformation -Encoding UTF8
}

$hits = @($rows | Where-Object Hit)
$misses = @($rows | Where-Object { -not $_.Hit })
$hitTof = @($hits | ForEach-Object TofUs)
$allTof = @($rows | ForEach-Object TofUs)
$hitX0 = @($hits | ForEach-Object X0Mm)
$hitY0 = @($hits | ForEach-Object Y0Mm)
$hitZ0 = @($hits | ForEach-Object Z0Mm)
$hitEnergy = @($hits | ForEach-Object EnergyEv)
$missZ0 = @($misses | ForEach-Object Z0Mm)
$missEnergy = @($misses | ForEach-Object EnergyEv)
$allX0 = @($rows | ForEach-Object X0Mm)
$allY0 = @($rows | ForEach-Object Y0Mm)
$allZ0 = @($rows | ForEach-Object Z0Mm)
$allEnergy = @($rows | ForEach-Object EnergyEv)
$allRadius = @($rows | ForEach-Object RadiusMm)
$meanTof = Get-Mean $hitTof
$stdTofUs = Get-SampleStd $hitTof
$fwhmFactor = 2.0 * [Math]::Sqrt(2.0 * [Math]::Log(2.0))
$fwhmTofUs = $fwhmFactor * $stdTofUs

[pscustomobject]@{
  Mode = $Mode
  Distribution = $Distribution
  Emitted = $initial.Count
  Crossed = $rows.Count
  Hit = $hits.Count
  EfficiencyPct = 100.0 * $hits.Count / $initial.Count
  MeanTofUs = $meanTof
  StdTofNs = 1000.0 * $stdTofUs
  FwhmTofNs = 1000.0 * $fwhmTofUs
  ResolutionFwhm = $meanTof / (2.0 * $fwhmTofUs)
  AllCrossingStdTofNs = 1000.0 * (Get-SampleStd $allTof)
  MaxHitRadiusMm = if ($hits.Count) { ($hits.RadiusMm | Measure-Object -Maximum).Maximum } else { [double]::NaN }
  MaxCrossingRadiusMm = ($rows.RadiusMm | Measure-Object -Maximum).Maximum
  MeanZmaxMm = Get-Mean $rows.ZmaxMm
  CorrTofX0 = Get-Correlation $hitX0 $hitTof
  CorrTofY0 = Get-Correlation $hitY0 $hitTof
  CorrTofZ0 = Get-Correlation $hitZ0 $hitTof
  CorrTofEnergy = Get-Correlation $hitEnergy $hitTof
  CorrRadiusX0 = Get-Correlation $allX0 $allRadius
  CorrRadiusY0 = Get-Correlation $allY0 $allRadius
  CorrRadiusZ0 = Get-Correlation $allZ0 $allRadius
  CorrRadiusEnergy = Get-Correlation $allEnergy $allRadius
  HitMeanZ0Mm = Get-Mean $hitZ0
  MissMeanZ0Mm = Get-Mean $missZ0
  HitMeanEnergyEv = Get-Mean $hitEnergy
  MissMeanEnergyEv = Get-Mean $missEnergy
  Log = (Resolve-Path -LiteralPath $Log).Path
}

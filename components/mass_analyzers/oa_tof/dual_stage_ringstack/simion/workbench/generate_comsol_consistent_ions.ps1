param(
  [int]$N = 100,
  [double]$MassAmu = 100,
  [int]$Charge = 1,
  [double]$EnergyMeanEv = 5,
  [double]$EnergyStdEv = 1,
  [double]$HalfWidthMm = 0.5,
  [double]$HalfWidthXmm = -1,
  [double]$HalfWidthYmm = -1,
  [double]$HalfWidthZmm = -1,
  [int]$Seed = 20260713,
  [string]$Output = 'oatof_comsol_100amu_gaussian_N100.ion'
)

$rng = [System.Random]::new($Seed)
$hx = if ($HalfWidthXmm -ge 0) { $HalfWidthXmm } else { $HalfWidthMm }
$hy = if ($HalfWidthYmm -ge 0) { $HalfWidthYmm } else { $HalfWidthMm }
$hz = if ($HalfWidthZmm -ge 0) { $HalfWidthZmm } else { $HalfWidthMm }
$m = $MassAmu * 1.66054e-27
$lines = [System.Collections.Generic.List[string]]::new()
for ($i = 0; $i -lt $N; $i++) {
  $x = -48.8 + (2*$rng.NextDouble() - 1)*$hx
  $y = 0.0 + (2*$rng.NextDouble() - 1)*$hy
  $z = 1.5 + (2*$rng.NextDouble() - 1)*$hz
  do {
    $u1 = [Math]::Max($rng.NextDouble(), 1e-15)
    $u2 = $rng.NextDouble()
    $normal = [Math]::Sqrt(-2.0 * [Math]::Log($u1)) * [Math]::Cos(2.0 * [Math]::PI * $u2)
    $energy = $EnergyMeanEv + $EnergyStdEv * $normal
  } while ($energy -le 0)
  $lines.Add(('0,{0:E8},{1},{2:E8},{3:E8},{4:E8},0,0,{5:E8},1,0' -f $MassAmu,$Charge,$x,$y,$z,$energy))
}
Set-Content -LiteralPath $Output -Value $lines -Encoding ASCII
Write-Output ("generated={0} N={1} mass_amu={2} charge={3} energy_mean_eV={4} energy_std_eV={5} seed={6}" -f (Resolve-Path $Output),$N,$MassAmu,$Charge,$EnergyMeanEv,$EnergyStdEv,$Seed)

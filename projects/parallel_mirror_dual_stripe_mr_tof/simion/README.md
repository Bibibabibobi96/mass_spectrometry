# MR-TOF Candidate SIMION 路径

`../analysis/simion_candidate_reference.py`由
`../config/simion_candidate_two_zone.json`生成早期候选 GEM 拓扑。它使用项目坐标：`z`是反射方向、`y`是漂移方向、`x`是横向聚焦方向，`z=0`是中央注入参考面。

`../analysis/full_candidate_geometry.py`是完整三维 Candidate 的唯一 GEM 源：稳定 ID
1--25 覆盖五电极双镜、四物理 Stripe、中央接地、两三角棱镜/接地屏蔽、新二区加速器及数值探测面。
镜/棱镜包络来自 2026-09-02 的只读 CAD 审计；Stripe 曲线和全局位姿尚是理论推导，不能称为
CAD-faithful。详情见[`../docs/CAD_AUDIT_20260902.md`](../docs/CAD_AUDIT_20260902.md)。

在本机生成 run-local PA：

```powershell
$run = 'C:\\Users\\Liao\\mass_spectrometry\\artifacts\\projects\\parallel_mirror_dual_stripe_mr_tof\\runs\\<run-id>\\simion'
python -m projects.parallel_mirror_dual_stripe_mr_tof.analysis.full_candidate_geometry `
  --contract projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json `
  --output "$run\\mrtof_full_candidate.gem"
& 'C:\\Program Files\\SIMION-2020\\simion.exe' --nogui lua `
  projects/parallel_mirror_dual_stripe_mr_tof/simion/build_full_candidate_pa.lua `
  "$run\\mrtof_full_candidate.gem" "$run\\mrtof_full_candidate.pa#" 4 0.4 1
```

`build_full_candidate_pa.lua` proves that electrodes 23/24 each occupy exactly one raw PA row.
After it has produced `pa0` and all basis arrays, `build_full_candidate_iob.lua` may build a single-PA
IOB from a bundled official SIMION template. Its instance translation is explicit: `(-90,-340,-350.129186803411)` mm,
which maps the two-zone first-order focus to the project `z=0` plane. `mrtof_candidate.lua` applies
mirror/Stripe/accelerator Fast Adjust and emits central-plane, turnaround and terminal events; the frozen
100 Th / +1 small bunch is `mrtof_candidate.fly2`.

No flight result has yet been certified from these assets. In particular, a detector hit, 25-oscillation
classification, TOF/FWHM and mass resolution require a completed basis set, IOB/Fly2 execution, and run-local
event receipt; do not infer them from successful GEM compilation.

本机官方依据为 SIMION 2020 的`examples/geometry/parallel_plate_capacitor_2d.gem`（零宽、节点对齐的理想栅）及`examples/field_dump/field_dump.lua`与`fielddumplib.lua`（Workbench 场导出），查阅日期为2026-09-02。当前 GEM 只冻结五电极镜和四个物理 Stripe 的候选拓扑；加速器、棱镜、接地屏蔽、PA边界、ideal-grid 行和 IOB 必须等待 SolidWorks CAD 审计和数值合同后生成。不得把该文本当作 Formal 资产或运行已验证模型。

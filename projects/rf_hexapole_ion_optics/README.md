# RF六极杆离子光学

本项目是 `rf_multipole_ion_optics` 家族的六极杆设计线。当前物理状态、资格边界和下一步以
[`docs/PROJECT.md`](docs/PROJECT.md)为准。

## 固定阅读顺序

1. 仓库根[`README.md`](../../README.md)。
2. 本项目[`docs/PROJECT.md`](docs/PROJECT.md)。
3. [`docs/multipoles/foundations.md`](../../docs/multipoles/foundations.md)和
   [`docs/multipoles/higher_multipoles.md`](../../docs/multipoles/higher_multipoles.md)。

## 当前权威入口

- 身份：[`config/project.json`](config/project.json)
- 机械、typed电气模式与设计profile：
  [`config/requests/mechanical_base.json`](config/requests/mechanical_base.json)、
  [`config/operating_modes.json`](config/operating_modes.json)、
  [`config/design_profiles.json`](config/design_profiles.json)
- 当前无加速发布：
  [`config/resolved_design_no_acceleration_full_length.json`](config/resolved_design_no_acceleration_full_length.json)
- 运行与数值profile：
  [`config/runtime_profiles.json`](config/runtime_profiles.json)、
  [`config/particle_source_profiles.json`](config/particle_source_profiles.json)、
  [`config/comsol_solver_numerics.json`](config/comsol_solver_numerics.json)、
  [`config/simion_solver_numerics.json`](config/simion_solver_numerics.json)
- 资格合同：[`config/qualification/`](config/qualification/)
- 公共家族合同：[`../../common/multipole/README.md`](../../common/multipole/README.md)
- 跨器件连接：
  [RF多极杆→oaTOF integration](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md)
- 家族工程推进指标：
  [`../../common/multipole/engineering_progression_acceptance.json`](../../common/multipole/engineering_progression_acceptance.json)

当前只发布三种设计模式，以及每种模式的N=100 baseline/空间/时间档和N=1000统计档。已关闭的
COMSOL mesh/solver试验和SIMION定向跟进不再是可执行profile，结论见
[`docs/history/20260802__retired-comsol-qualification-campaigns.md`](docs/history/20260802__retired-comsol-qualification-campaigns.md)。

## 执行入口

- L1：[`analysis/run_transport.ps1`](analysis/run_transport.ps1)
- L2场筛选：[`analysis/run_round_rod_field_screen.ps1`](analysis/run_round_rod_field_screen.ps1)
- L2传输：[`analysis/run_round_rod_transport.ps1`](analysis/run_round_rod_transport.ps1)
- L3 COMSOL：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)
- L3 SIMION：[`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

入口只接受具名runtime profile。运行产物只进入
`artifacts/projects/rf_hexapole_ion_optics/runs/`，不进入Git。

## 资格边界

当前实验、资源终态、数值资格和商业运行授权只以[`docs/PROJECT.md`](docs/PROJECT.md)为准；本入口
不复制运行结果。工程阈值PASS不得改称数值收敛、Candidate或Formal资格。

历史材料：

- [N=100规范前证据](docs/history/20260723__pre-n100-multipole-functional-evidence.md)
- [早期closed hybrid mesh campaign](docs/history/20260729__closed-hybrid-mesh-campaigns.md)
- [已退役数值资格campaign摘要](docs/history/20260802__retired-comsol-qualification-campaigns.md)
- [RF幅值—频率相位匹配H15筛选](docs/history/20260803__hex-rf-drive-phase-matched-h15-n100.md)
- [RF幅值—频率相位匹配N=1000复核](docs/history/20260803__hex-rf-drive-phase-matched-h15-n1000.md)

## 历史补充索引
- [20260729__multipole-three-mode-posthoc-n100](docs/history/20260729__multipole-three-mode-posthoc-n100.md)
- [20260731__multipole-engineering-reanalysis-18-comparisons](docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md)
- [20260731__multipole-noacc-vs-segmented-h15-n100](docs/history/20260731__multipole-noacc-vs-segmented-h15-n100.md)
- [20260731__multipole-three-mode-h15-n100](docs/history/20260731__multipole-three-mode-h15-n100.md)
- [20260731__no-acceleration-multipole-discretization-followup](docs/history/20260731__no-acceleration-multipole-discretization-followup.md)
- [20260803__multipole-four-mode-source-energy-h15-n100](docs/history/20260803__multipole-four-mode-source-energy-h15-n100.md)

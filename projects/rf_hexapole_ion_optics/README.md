# RF六极杆离子光学

本项目是 `rf_multipole_ion_optics` 家族的六极杆设计线。当前物理状态、资格边界和下一步以
[`docs/PROJECT.md`](docs/PROJECT.md)为准。

## 固定阅读顺序

1. 仓库根[`README.md`](../../README.md)。
2. 本项目[`docs/PROJECT.md`](docs/PROJECT.md)。
3. [`docs/multipoles/foundations.md`](../../docs/multipoles/foundations.md)和
   [`docs/multipoles/higher_multipoles.md`](../../docs/multipoles/higher_multipoles.md)。

## 机器权威

项目身份见 [project.json](config/project.json)；机械、电气、源、数值和资格合同统一由
[PROJECT](docs/PROJECT.md)导航。共享编译与运行方法见
[公共多极杆入口](../../common/multipole/README.md)，跨器件连接见
[RF 多极杆→oaTOF integration](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md)。

## 执行入口

- L1：[`analysis/run_transport.ps1`](analysis/run_transport.ps1)
- L2场筛选：[`analysis/run_round_rod_field_screen.ps1`](analysis/run_round_rod_field_screen.ps1)
- L2传输：[`analysis/run_round_rod_transport.ps1`](analysis/run_round_rod_transport.ps1)
- L3 COMSOL：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)
- L3 SIMION：[`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

入口只接受具名runtime profile。运行产物只进入
`artifacts/projects/rf_hexapole_ion_optics/runs/`，不进入Git。

## History索引

<details>
<summary>展开只读历史记录</summary>

- [20260723__pre-n100-multipole-functional-evidence](docs/history/20260723__pre-n100-multipole-functional-evidence.md)
- [20260729__closed-hybrid-mesh-campaigns](docs/history/20260729__closed-hybrid-mesh-campaigns.md)
- [20260729__multipole-three-mode-posthoc-n100](docs/history/20260729__multipole-three-mode-posthoc-n100.md)
- [20260731__multipole-engineering-reanalysis-18-comparisons](docs/history/20260731__multipole-engineering-reanalysis-18-comparisons.md)
- [20260731__multipole-noacc-vs-segmented-h15-n100](docs/history/20260731__multipole-noacc-vs-segmented-h15-n100.md)
- [20260731__multipole-three-mode-h15-n100](docs/history/20260731__multipole-three-mode-h15-n100.md)
- [20260731__no-acceleration-multipole-discretization-followup](docs/history/20260731__no-acceleration-multipole-discretization-followup.md)
- [20260802__retired-comsol-qualification-campaigns](docs/history/20260802__retired-comsol-qualification-campaigns.md)
- [20260803__hex-rf-drive-phase-matched-h15-n100](docs/history/20260803__hex-rf-drive-phase-matched-h15-n100.md)
- [20260803__hex-rf-drive-phase-matched-h15-n1000](docs/history/20260803__hex-rf-drive-phase-matched-h15-n1000.md)
- [20260803__multipole-four-mode-source-energy-h15-n100](docs/history/20260803__multipole-four-mode-source-energy-h15-n100.md)

</details>

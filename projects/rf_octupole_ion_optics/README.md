# RF八极杆离子光学

本项目是RF多极杆家族的八极杆设计线。当前参数、资格、有效结论和开放任务只以
[`docs/PROJECT.md`](docs/PROJECT.md)为准；本页只负责导航。

## 阅读顺序

1. 仓库根[`README.md`](../../README.md)。
2. 本项目[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 共享实现与术语：[`common/multipole/README.md`](../../common/multipole/README.md)。
4. 理论背景：
   [共同理论](../../docs/multipoles/foundations.md)和
   [高阶多极杆](../../docs/multipoles/higher_multipoles.md)。
5. 跨器件单流程：
   [RF多极杆→oaTOF integration](../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/README.md)。

## 机器权威

| 职责 | 入口 |
|---|---|
| 身份 | [`config/project.json`](config/project.json) |
| 机械request | [`config/requests/mechanical_base.json`](config/requests/mechanical_base.json) |
| 变量与包络 | [`config/design_variables.json`](config/design_variables.json)、[`config/optimization_envelope.json`](config/optimization_envelope.json) |
| typed模式与设计profile | [`config/operating_modes.json`](config/operating_modes.json)、[`config/design_profiles.json`](config/design_profiles.json) |
| runtime与源 | [`config/runtime_profiles.json`](config/runtime_profiles.json)、[`config/particle_source_profiles.json`](config/particle_source_profiles.json) |
| 求解器数值 | [`config/comsol_solver_numerics.json`](config/comsol_solver_numerics.json)、[`config/simion_solver_numerics.json`](config/simion_solver_numerics.json) |
| 资格 | [`config/qualification/`](config/qualification/) |

活动设计只有`no_acceleration_full_length`、`segmented_rod_axial_acceleration`和
`exit_aperture_plate_acceleration`三个规范模式。几何、电气值和运行终态不在README复制。

## 执行

- COMSOL：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)
- SIMION：[`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

入口接受具名 runtime profile，或一个已预登记的 multipole campaign 加 experiment ID；后者仍解析为同一份
冻结 runtime contract，不能用作任意参数覆盖。产物只写
`artifacts/projects/rf_octupole_ion_optics/`；历史证据只按项目descriptor的
`archived_verified`位置读取。

## History索引

- [N=100规范前功能证据](docs/history/20260723__pre-n100-multipole-functional-evidence.md)

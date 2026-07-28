# RF六极杆离子导引项目

本项目是`rf_multipole_ion_optics`家族的独立六极杆设计线。当前已从理想L1、二维圆杆L2推进到带
参数化带孔接口板和有限外部区的三维COMSOL直接传输；现状与边界以
[`docs/PROJECT.md`](docs/PROJECT.md)为准。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 理论读取[`docs/multipoles/foundations.md`](../../docs/multipoles/foundations.md)和
   [`docs/multipoles/higher_multipoles.md`](../../docs/multipoles/higher_multipoles.md)。

只有调整设计族范围、跨项目优先级或长期阶段时才读
[`docs/ROADMAP.md`](../../docs/ROADMAP.md)，日常项目任务不把它加入固定阅读链。

## 当前入口

- 项目身份：[`config/project.json`](config/project.json)
- 三项目共享运行合同：[`../../common/multipole/README.md`](../../common/multipole/README.md)
  （轴向实体与物理面只采用其中的“轴向部件与物理面术语”）。
- 历史L1兼容输入：[`config/baseline.json`](config/baseline.json)，只读；`project.json`仅因当前registry
  schema把它保留为旧格式身份检查，不是活动solver参数权威。
- Phase 2设计请求、变量目录和优化包络：
  [`config/requests/baseline.json`](config/requests/baseline.json)、
  [`config/design_variables.json`](config/design_variables.json)、
  [`config/optimization_envelope.json`](config/optimization_envelope.json)
- 设计profile注册与解析发布：[`config/design_profiles.json`](config/design_profiles.json)、
  [`config/resolved_design.json`](config/resolved_design.json)。
- L3运行profile：[`config/runtime_profiles.json`](config/runtime_profiles.json)只绑定设计、
  粒子源和求解器数值profile身份；粒子源与COMSOL/SIMION数值分别由
  [`config/particle_source_profiles.json`](config/particle_source_profiles.json)、
  [`config/comsol_solver_numerics.json`](config/comsol_solver_numerics.json)和
  [`config/simion_solver_numerics.json`](config/simion_solver_numerics.json)发布。
- 无加速全长基线：`no_acceleration_full_length`保持79.6 mm杆长和现有紧邻接口几何，杆共同偏置、
  带孔接口板和外壳参考均为0 V；当前只有机器合同和静态门禁，不代表商业求解、收敛或资格PASS。
- 执行组合：[`config/execution_profiles.json`](config/execution_profiles.json)保留compile-only门禁；
  商业运行可由薄wrapper绑定同一profile，未提供evidence合同即为`UNQUALIFIED`。
- 运行入口：[`analysis/run_transport.ps1`](analysis/run_transport.ps1)
- L2圆杆筛选：[`analysis/run_round_rod_field_screen.ps1`](analysis/run_round_rod_field_screen.ps1)，
  固定通过`baseline_finite_3d` profile编译resolved，只发布逐候选场指标，不选择L3几何。
- L2传输：[`analysis/run_round_rod_transport.ps1`](analysis/run_round_rod_transport.ps1)
- L3 COMSOL薄wrapper：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)，
  公开入口只接受具名runtime profile，不接受粒子路径或自由数值。
- L3 SIMION独立回归：[`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

运行产物只进入`artifacts/projects/rf_hexapole_ion_guide/runs/`，不进入Git。

## 历史入口

- [`docs/history/20260723__pre-n100-multipole-functional-evidence.md`](docs/history/20260723__pre-n100-multipole-functional-evidence.md)：
  N=100规范生效前的L1/L2/L3、正长度连接器和分段加速功能证据。

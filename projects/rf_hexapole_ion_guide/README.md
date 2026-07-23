# RF六极杆离子导引项目

本项目是`rf_multipole_ion_optics`家族的独立六极杆设计线。当前已从理想L1、二维圆杆L2推进到带
参数化开孔端板和有限外部区的三维COMSOL直接传输；现状与边界以[`docs/PROJECT.md`](docs/PROJECT.md)为准。

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
- L1 baseline：[`config/baseline.json`](config/baseline.json)
- Phase 2设计请求、变量目录和优化包络：
  [`config/requests/baseline.json`](config/requests/baseline.json)、
  [`config/design_variables.json`](config/design_variables.json)、
  [`config/optimization_envelope.json`](config/optimization_envelope.json)
- 设计profile注册与解析发布：[`config/design_profiles.json`](config/design_profiles.json)、
  [`config/resolved_design.json`](config/resolved_design.json)。
- 执行组合：[`config/execution_profiles.json`](config/execution_profiles.json)保留compile-only门禁；
  商业运行可由薄wrapper绑定同一profile，未提供evidence合同即为`UNQUALIFIED`。
- 运行入口：[`analysis/run_transport.ps1`](analysis/run_transport.ps1)
- L2圆杆筛选：[`analysis/run_round_rod_field_screen.ps1`](analysis/run_round_rod_field_screen.ps1)，
  固定通过`baseline_finite_3d` profile编译resolved，只发布逐候选场指标，不选择L3几何。
- L2传输：[`analysis/run_round_rod_transport.ps1`](analysis/run_round_rod_transport.ps1)
- L3兼容薄wrapper：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)
- L3 SIMION独立回归：[`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

运行产物只进入`artifacts/projects/rf_hexapole_ion_guide/runs/`，不进入Git。

## 历史入口

- [`docs/history/20260723__pre-n100-multipole-functional-evidence.md`](docs/history/20260723__pre-n100-multipole-functional-evidence.md)：
  N=100规范生效前的L1/L2/L3、正长度连接器和分段加速功能证据。

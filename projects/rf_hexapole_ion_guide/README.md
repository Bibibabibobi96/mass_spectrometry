# RF六极杆离子导引项目

本项目是`rf_multipole_ion_optics`家族的独立六极杆设计线。当前已从理想L1、二维圆杆L2推进到带
参数化开孔端板和有限外部区的三维COMSOL直接传输；现状与边界以[`docs/PROJECT.md`](docs/PROJECT.md)为准。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)和[`docs/ROADMAP.md`](../../docs/ROADMAP.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 理论读取[`docs/multipoles/foundations.md`](../../docs/multipoles/foundations.md)和
   [`docs/multipoles/higher_multipoles.md`](../../docs/multipoles/higher_multipoles.md)。

## 当前入口

- 项目身份：[`config/project.json`](config/project.json)
- 三项目共享运行合同：[`../../common/multipole/README.md`](../../common/multipole/README.md)
- L1 baseline：[`config/baseline.json`](config/baseline.json)
- 运行入口：[`analysis/run_transport.ps1`](analysis/run_transport.ps1)
- L2圆杆筛选：[`analysis/run_round_rod_field_screen.ps1`](analysis/run_round_rod_field_screen.ps1)
- L2传输：[`analysis/run_round_rod_transport.ps1`](analysis/run_round_rod_transport.ps1)
- L3直接跟踪：[`analysis/run_finite_3d_transport.ps1`](analysis/run_finite_3d_transport.ps1)
- L3 SIMION独立回归：[`analysis/run_simion_finite_3d_transport.ps1`](analysis/run_simion_finite_3d_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

运行产物只进入`artifacts/projects/rf_hexapole_ion_guide/runs/`，不进入Git。

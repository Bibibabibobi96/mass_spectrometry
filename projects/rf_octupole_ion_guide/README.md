# RF八极杆离子导引项目

本项目是`rf_multipole_ion_optics`家族的独立八极杆设计线。当前具有理想有限长度L1参考，以及真实圆杆
二维COMSOL场筛选和无端部L2传输；现状与边界以[`docs/PROJECT.md`](docs/PROJECT.md)为准。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)和[`docs/ROADMAP.md`](../../docs/ROADMAP.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 理论读取[`docs/multipoles/foundations.md`](../../docs/multipoles/foundations.md)和
   [`docs/multipoles/higher_multipoles.md`](../../docs/multipoles/higher_multipoles.md)。

## 当前入口

- 项目身份：[`config/project.json`](config/project.json)
- L1 baseline：[`config/baseline.json`](config/baseline.json)
- 运行入口：[`analysis/run_transport.ps1`](analysis/run_transport.ps1)
- L2圆杆筛选：[`analysis/run_round_rod_field_screen.ps1`](analysis/run_round_rod_field_screen.ps1)
- L2传输：[`analysis/run_round_rod_transport.ps1`](analysis/run_round_rod_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

运行产物只进入`artifacts/projects/rf_octupole_ion_guide/runs/`，不进入Git。

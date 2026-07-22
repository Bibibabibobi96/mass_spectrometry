# RF八极杆离子导引项目

本项目是`rf_multipole_ion_optics`家族的独立八极杆设计线。当前只建立无碰撞、理想有限长度L1时域
传输参考，用于验证八极非线性场、统一合同和项目架构；现状与边界以[`docs/PROJECT.md`](docs/PROJECT.md)为准。

## 固定阅读顺序

1. 先读仓库根[`README.md`](../../README.md)和[`docs/ROADMAP.md`](../../docs/ROADMAP.md)。
2. 再读[`docs/PROJECT.md`](docs/PROJECT.md)。
3. 理论读取[`docs/multipoles/foundations.md`](../../docs/multipoles/foundations.md)和
   [`docs/multipoles/higher_multipoles.md`](../../docs/multipoles/higher_multipoles.md)。

## 当前入口

- 项目身份：[`config/project.json`](config/project.json)
- L1 baseline：[`config/baseline.json`](config/baseline.json)
- 运行入口：[`analysis/run_transport.ps1`](analysis/run_transport.ps1)
- 静态门禁：[`verify_project.ps1`](verify_project.ps1)

运行产物只进入`artifacts/projects/rf_octupole_ion_guide/runs/`，不进入Git。

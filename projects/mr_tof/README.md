# MR-TOF 项目使用指南

本目录是多次反射飞行时间质量分析器（MR-TOF）的独立原型项目。当前只接收了一套用户自绘
SolidWorks 工程图作为设计种子；它不是 oa-TOF 的 mode，也不属于 `projects/oa_tof/formal`。

## 固定阅读顺序

1. 先读[`docs/PROJECT.md`](docs/PROJECT.md)，确认当前能力边界、已有证据和开放任务。
2. 检查或处理现有 SolidWorks 图时再读[`docs/CAD.md`](docs/CAD.md)。
3. 理论、机器参数合同、COMSOL、SIMION和分析入口形成后，再按实际职责新增邻近文档或代码；不预建空目录。

仓库结构、产物生命周期、正式化和 Git 规则统一继承根[`README.md`](../../README.md)。原始 CAD
二进制保存在同级 `artifacts/projects/mr_tof/archive/` 的迁入快照中，不进入 Git。

## 当前权威入口

- 项目状态与下一步：[`docs/PROJECT.md`](docs/PROJECT.md)
- SolidWorks 原始图边界：[`docs/CAD.md`](docs/CAD.md)
- 项目身份与成熟度：[`config/project.json`](config/project.json)

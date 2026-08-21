# 开放路径平行镜双条带 MR-TOF 项目使用指南

本目录是开放路径平行镜双条带多次反射飞行时间质量分析器（MR-TOF）的独立原型项目。当前活动
硬件设计线由一组名义平行的伸长等时离子镜和两套独立偏压、独立形状的漂移条带电极组共同构成；
两套条带是同一分析器内耦合的空间返回/时间响应基，不是两个项目或两个运行 profile。本项目不是
单次反射 oa-TOF 的 mode。

## 固定阅读顺序

1. 先读[`docs/PROJECT.md`](docs/PROJECT.md)，确认当前能力边界、已有证据和开放任务。
2. 检查或处理现有 SolidWorks 图时再读[`docs/CAD.md`](docs/CAD.md)。
3. 建立机器参数合同、COMSOL、SIMION和分析入口时，再按实际职责新增邻近文档或代码；不预建空目录。

已审阅的MR-TOF理论参考见[`docs/theory/index.md`](docs/theory/index.md)。其中平行镜双条带模型是
当前活动设计目标；原 Astral 的收敛镜加单 Stripe/Ion Foil 方案只用于理论对照和解析回归，不启动
另一条单 Stripe 项目，也不自动成为本项目baseline。

仓库结构、产物生命周期、正式化和 Git 规则统一继承根[`README.md`](../../README.md)。原始 CAD
二进制已以迁移前`mr_tof`身份逐文件验证并只读迁入当前项目具名archive，不进入 Git；新运行只能使用当前
`parallel_mirror_dual_stripe_mr_tof`身份和同名artifact根。

## 当前权威入口

- 项目状态与下一步：[`docs/PROJECT.md`](docs/PROJECT.md)
- SolidWorks 原始图边界：[`docs/CAD.md`](docs/CAD.md)
- 项目身份与成熟度：[`config/project.json`](config/project.json)

## 历史补充索引
- [20260802__mrtof-project-identity-consolidation](docs/history/20260802__mrtof-project-identity-consolidation.md)

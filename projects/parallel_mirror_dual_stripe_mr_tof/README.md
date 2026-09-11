# 开放路径平行镜双条带 MR-TOF

本项目研究名义平行的伸长等时镜与两套独立偏压、独立形状的漂移条带。两套条带属于同一分析器，
共同控制空间返回和时间响应；本项目是与单反射 oa-TOF 平级的独立硬件设计线。

返回[仓库导航](../../README.md)。

## 阅读与操作入口

先读[当前状态](docs/PROJECT.md)确认能力、证据和开放任务，再按实际工作选择：

| 任务 | 入口 |
|---|---|
| 理解模型、符号、推导和验证范围 | [理论索引](docs/theory/index.md) |
| 构建、检查或运行 SIMION | [SIMION 实施说明](simion/README.md) |
| 处理原始装配、曲线或机械证据 | [CAD 实施说明](docs/CAD.md) |
| 查项目身份、旧资产位置和机器成熟度 | [项目描述符](config/project.json) |
| 查活动几何与 CAD 变换 | [候选几何合同](config/simion_candidate_two_zone.json)、[坐标合同](config/cad_to_theory_frame.json) |

COMSOL 或其他求解器是否已有可执行入口，以 PROJECT 的当前说明为准，不从目录名或理论计划推定。
实际执行的前提、输入、资源限制与产物检查由对应实施说明提供。

## 项目边界

原 Astral 的“收敛镜 + 单 Stripe/Ion Foil”仅作为理论对照和解析回归，不是另一条活动硬件线。
二区／三区正交加速器的局部理论、几何与复用实现由独立
[正交加速器项目](../orthogonal_accelerator/README.md)拥有；本项目负责 MR 专属输入、装配、棱镜、
镜组及整机飞行，不复制另一仪器的 Formal 或 integration 运行产物作为自身资格。

知识权威与单向几何链见[仓库架构](../../docs/REPOSITORY_ARCHITECTURE.md)，原始 CAD 只提供已审计
机械约束；归档、运行和发布见[生命周期](../../docs/LIFECYCLE.md)。新运行使用当前项目身份，
历史 `mr_tof` 资产按描述符保留原记录身份。

## 历史补充索引

- [项目身份整合](docs/history/20260802__mrtof-project-identity-consolidation.md)
- [CAD 审计上下文冻结](docs/history/20260911__cad-audit-context-freeze.md)

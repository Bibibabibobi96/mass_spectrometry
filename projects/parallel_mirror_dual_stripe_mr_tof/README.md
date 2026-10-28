# 开放路径平行镜双条带 MR-TOF

本项目研究伸长等时镜与形状化漂移条带的空间返回和时间响应。当前工程候选为关于z=0对称会聚的双镜、
五次项偏置Stripe及保留实体的接地线性Stripe；此前平行镜双偏压方案保留为对照。
本项目是与单反射 oa-TOF 平级的独立硬件设计线。候选实施与资格状态见PROJECT。

返回[仓库导航](../../README.md)。

## 阅读与操作入口

先读[当前状态](docs/PROJECT.md)确认能力、证据和开放任务，再按实际工作选择：

| 任务 | 入口 |
|---|---|
| 理解模型、符号、推导和验证范围 | [理论索引](docs/theory/index.md) |
| 构建、检查或运行 SIMION | [SIMION 实施说明](docs/SIMION.md) |
| 选择OA／IP并准备或执行跨器件链 | [统一集成入口](../../integrations/README.md)、[组装当前边界](docs/PROJECT.md#统一组装迁移任务) |
| 处理原始装配、曲线或机械证据 | [CAD 实施说明](docs/CAD.md) |
| 查项目身份、旧资产位置、Candidate 成熟度和机器登记的 baseline | [项目描述符](config/project.json) |
| 查活动几何与 CAD 变换 | [候选几何合同](config/simion_candidate_two_zone.json)、[坐标合同](config/cad_to_theory_frame.json) |

COMSOL 或其他求解器是否已有可执行入口，以 PROJECT 的当前说明为准，不从目录名或理论计划推定。
实际执行的前提、输入、资源限制与产物检查由对应实施说明提供。

## 项目边界

本项目自2026-10-12起新建SIMION场的各轴网格间距必须为0.01 mm的正整数倍，
最小间距0.01 mm，不再向下细分。该规则适用于全局场、局域场及导入场的规则采样；
各轴可采用不同间距。已有冻结资产及正在执行的旧网格试验保持原输入作为历史证据，
不得静默取整、改写旧结果或因此删除仍有消费者的PA；后续新网格方案按此规则重新规划。

原 Astral 的“收敛镜 + 单 Stripe/Ion Foil”为当前会聚候选提供理论依据；
现候选保留额外接地线性Stripe实体，不能视为原论文几何或已复现论文性能。
二区／三区正交加速器的局部理论、几何与复用实现由独立
[正交加速器项目](../orthogonal_accelerator/README.md)拥有。MR保留分析器几何、棱镜、镜组、系统布局约束、
匹配与验收；器件实例组装和跨项目飞行从[统一集成入口](../../integrations/README.md)进入。
组件请求与公共release由实际工作流冻结，不复制另一仪器的PA或Formal/integration结果作为自身资格。

知识权威与单向几何链见[仓库架构](../../docs/REPOSITORY_ARCHITECTURE.md)，原始 CAD 只提供已审计
机械约束；归档、运行和发布见[生命周期](../../docs/LIFECYCLE.md)。新运行使用当前项目身份，
历史 `mr_tof` 资产按描述符保留原记录身份。

项目描述符只登记已经稳定的机器能力和合同路径；当前物理状态、运行证据与未关闭任务仍以
[PROJECT](docs/PROJECT.md)为准。尚未形成单一正式执行链的试验 runner 不会为了目录可发现性而全部登记成
execution profile；轻量项目门禁统一由[`verify_project.ps1`](verify_project.ps1)进入，且不会启动商业求解器。
`Core`保留固定合同回归，并合并L1按[统一测试目录](../../common/README.md#门禁编排)传入的
`ChangedTestModules`，相同模块只运行一次。完整静态回归仍由`Static`承担；Core通过不证明其他未选模块通过。

## 历史补充索引

[历史索引](docs/history/README.md)集中列出已冻结实验、迁移和旧方案；需要追溯证据时按需进入。

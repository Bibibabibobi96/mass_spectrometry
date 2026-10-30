# 文档任务目录

返回[仓库入口](../README.md)。本页统一发现文档，正文保存在负责其知识的项目、组装或公共层；
不会为便于导航复制理论、参数、资格或规则。先按项目README与状态页确认任务，再选择下表所需分支。

## 全仓规则与操作

| 问题 | 唯一正文 |
|---|---|
| 项目、变体、实例和组装怎样划分，文件放哪里 | [仓库架构与知识权威](REPOSITORY_ARCHITECTURE.md) |
| 端口、位姿、组件接口、源、时钟、驱动与组装语义 | [连接与组装架构](COMPONENT_CONNECTION_ARCHITECTURE.md) |
| 运行、缓存、产物保留、历史与资料归档 | [生命周期](LIFECYCLE.md) |
| 环境、启动、软件验证与科学证据、Git及完成标准 | [操作指南](OPERATIONS.md) |
| 编码、合同、配置分层、进程、性能与测试 | [开发标准阅读导航](DEVELOPMENT_STANDARDS.md#阅读导航) |
| 科学图形的追溯、标注与展示 | [绘图标准](PLOTTING_STANDARDS.md) |
| 平台使命和跨项目建设顺序 | [愿景](VISION.md)、[路线图](ROADMAP.md) |
| Agent执行行为与权限 | [AGENTS](../AGENTS.md)，不替代上述项目知识 |

## 理论与科学方法

先找模型的所有者，再找其适用变体；被多个项目引用，不会自动改变理论的所有者。
项目局部公式、整机联合模型和公共数值方法分别维护，当前结果仍查PROJECT或INTEGRATION。

| 问题 | 正文入口与范围 |
|---|---|
| 多极杆场、阶数、电压约定、质量筛选、碰撞和出口相空间 | [多极杆理论](../projects/rf_multipole_ion_optics/docs/theory/index.md)，四／六／八极适用范围分别解释 |
| 二区／三区加速器的局部时间聚焦与源状态 | [正交加速器理论](../projects/orthogonal_accelerator/docs/theory/README.md) |
| 单反射器及加速器—反射器联合聚焦、条件相空间 | [单反射oa-TOF理论](../projects/single_reflection_oa_tof_mass_analyzer/docs/theory/README.md) |
| 多反射镜、漂移、Stripe及注入光学 | [MR-TOF理论](../projects/parallel_mirror_dual_stripe_mr_tof/docs/theory/index.md) |
| 双压力区捕获、碰撞冷却与脉冲提取的当前物理范围 | [Ion Processor状态](../projects/dual_pressure_rectilinear_ion_processor/docs/PROJECT.md) |
| 双锥气流与离子输运的模型假设及耦合范围 | [双锥接口状态](../projects/dual_cone_tandem_quadrupole_ion_interface/docs/PROJECT.md) |
| 电子轰击电离与离子出生状态的已有范围 | [EI离子源状态](../projects/apertured_tube_electron_impact_ion_source/docs/PROJECT.md) |
| 热电子发射、收集与电子枪的模型限制 | [Wehnelt电子枪状态](../projects/transverse_helical_filament_wehnelt_electron_gun/docs/PROJECT.md) |
| 网格、时间步、粒子统计、峰宽和跨求解器比较 | [验证方法](science/VALIDATION_METHODS.md) |
| 分辨率与允许时间误差的查表和计算 | [TOF误差预算](science/TOF_ERROR_BUDGET.md) |

没有独立理论长文的项目从其物理边界和机器合同开始，不为目录整齐建立空文档。
研究模型、求解器实现和已验证能力分别判断；资料索引或公式存在不能证明可执行或已获资格。

## 软件与执行

| 任务 | 阅读入口 |
|---|---|
| COMSOL路线、网格、原生追踪、API或故障定位 | [COMSOL按任务指南](tools/COMSOL_GUIDE.md)，再选择[API](tools/COMSOL_API.md)或[排错](tools/COMSOL_DEBUGGING.md) |
| SIMION长PA、场与程序经验 | [SIMION参考](tools/SIMION_REFERENCE.md) |
| 某项目的模型树、操作步骤和软件验证 | 对应项目README中的COMSOL／SIMION／CAD入口，不在公共指南复制项目参数 |
| 跨组件执行及联合证据 | [组装入口](../integrations/README.md) → 对应工作流和[集成状态](../integrations/docs/INTEGRATION.md) |
| 官方API或物理接口原始语义 | [供应商资料](references/software/README.md)，限定软件版本和相关章节 |

## 公共实现与机器合同

| 对象 | 邻近说明 |
|---|---|
| 门禁编排、资源调度与公共机制任务路由 | [公共机制入口](../common/README.md) |
| 峰形、场比较、粒子配对与数值统计 | [公共分析](../common/analysis/README.md) |
| run身份、冻结、manifest、保留、容量与项目发现 | [机器合同](../common/contracts/README.md) |
| 组件连接、完整与局部配方解析 | [公共连接合同](../common/integration/README.md) |
| 离子释放、种子、粒子身份与母群 | [公共离子释放](../common/ion_release/README.md) |
| SIMION执行、PA与缓存机制 | [公共SIMION实现](../common/simion/README.md) |
| COMSOL启动和公共验证模型 | [公共COMSOL实现](../common/comsol/README.md) |
| SolidWorks桥接和保存 | [公共SolidWorks实现](../common/solidworks/README.md) |
| 工作区与产物路径 | [公共路径机制](../common/paths/README.md) |

这些说明只定义实际API及已验证使用边界。项目物理设计和资格仍由提供者维护，机器输入以相邻合同为准。

## 研究、参考资料与历史

| 要找的内容 | 入口及用途 |
|---|---|
| 发表主张、实验计划、阶段合同与证据矩阵 | [oa-TOF发表研究](../projects/single_reflection_oa_tof_mass_analyzer/docs/publication/README.md)；仅该项目实际维护此类研究，不要求其他项目复制模板 |
| 书、论文与供应商手册 | [外部参考资料](references/README.md)；只保存来源定位，应用假设写回知识所有者 |
| 已完成全仓审计与迁移 | [审计索引](AUDITS.md) |
| 项目研究、旧方案和负结果 | 所属项目README的历史入口；[组装历史索引](../integrations/docs/history/README.md) |
| 某次运行的原始输入、结果、图表和日志 | 所属artifacts run的manifest及summary；不复制进当前指导或理论 |

普通编辑通过Git固定提交追溯。历史索引可以维护，冻结记录按当时身份解释；实际移动或退役遵循
[历史规则](LIFECYCLE.md#history-冻结条件)，不能把过期“当前步骤”重新当作执行指令。

# RF 多极杆—单反射 oaTOF 集成

本目录定义从 RF 多极杆交接状态到单反射 oaTOF 单飞运行的活动集成边界。它是当前架构入口，不记录
历史性能叙事、已退役 campaign 或逐次调试结论；这些材料位于 [`HISTORY.md`](HISTORY.md)。
参数的唯一 authority、消费者和失效域见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 所有权与入口

- 多极杆项目拥有杆内几何、RF 驱动、源粒子与 `handoff` 状态；oaTOF 项目拥有下游几何、脉冲和分析。
- 本集成只拥有跨组件状态绑定、活动 campaign 的生命周期、单飞适配与运行证据链。
- [`workflows/family_source_closure/prepare.py`](../workflows/family_source_closure/prepare.py) 只准备并验证已授权输入；
  [`execute.ps1`](../workflows/family_source_closure/execute.ps1) 只执行生命周期注册表明确允许的 campaign。
  未注册、退役或历史 campaign 必须失败关闭。
- [`runtime/run_single_flight.ps1`](../runtime/run_single_flight.ps1) 是单飞 SIMION 的唯一运行入口；项目或分析脚本
  不得复制其 PA cache、FLY2、粒子重编号或资源预算实现。

## 运行边界

商业求解器默认按 campaign 串行调度。粒子相互独立、无碰撞、无空间电荷且 campaign 显式授权时，单个
SIMION 运行可调用共享批处理；批内结果必须恢复全局粒子 ID 并合并为一个来源 run。不得在外层 campaign
并发之上再启动嵌套并发。

仓库级 [`common/simion/resource_scheduler.py`](../../../common/simion/resource_scheduler.py) 仅为已授权请求
规划 RF/静电批次：它综合粒子数、每批 CPU、可用内存、预留内存、已观测的同资源身份峰值及并发上限。
没有匹配历史时，首次运行只能采用单批 bootstrap；观测到峰值后才可为同一资源身份提高并发。

每个 run 必须冻结 `run_config.json`、`summary.json` 和 `run_manifest.json`。缓存只用于完全相同的冻结身份，
且不可替代来源 run。功能成功不自动证明数值收敛、跨求解器等价、参数最优或 Formal 资格。

三区 N=1 路径 smoke 只证明已冻结路径可贯通；其授权 receipt 绑定一个具名后继行的完整行 SHA、
科学身份、粒子顺序摘要和实际粒子数。新合同可授权任意正整数人口，旧 `N100` receipt 仍只授权其原
`N=100` 后继。两者都不构成分辨率、工程资格或 Formal 声明。

## 配置、验证与历史

活动配置位于 [`config/`](../config/)；公共 schema 和文件身份工具位于
[`common/contracts/`](../../../common/contracts/README.md)。修改活动运行器、合同、资源策略或 campaign 后，应运行
项目门禁及仓库级集成门禁。历史文档中的数字、状态和链接均不构成活动授权。

当前唯一活动 campaign 是 `connector_gap_field_matrix_compact_auto_replay_v2.json`。此前 23 个已发布的逐 gap/field
合同保留原始字节和 receipt，但已退出 lifecycle registry：它们由该 compact replay 完整替代，且不应因后续运行
policy（内存、并发、超时或保留）更新而重新成为可执行 authority。

实验 campaign 可继续使用完整行，也可用扁平 authoring：`experiments.shared` 声明共同控制，
`variation_axes` 列出允许变化的字段，`rows` 只列行身份和 `overrides`。准备阶段先展开为完整冻结行，
再执行既有 schema 与授权校验；任何未声明的字段变化都失败关闭。这样同一合同可顺序执行多个 gap 或
其他已授权参数点，而不会复制共享输入。

已发布 campaign 如仅改变 authoring 布局，可用 `published_authoring_identity` 保留旧 receipt 的 raw 文件 SHA；
它同时冻结完整的、已展开 campaign 科学语义 SHA。只有二者严格匹配时才接受该旧 SHA；物理、数值、资格或
任一展开行的变化都会使 source-binding 检查失败。执行策略另由 runtime binding 和每次 run receipt 冻结，
不属于 campaign 科学身份。这不是通用兼容或结果复用 fallback。

对已注册 campaign，`execute.ps1 -AllExperiments` 按展开后的 `sequence` 逐行调用同一单实验入口；它不在
campaign 层并行商业求解器，任一行失败即停止。`PrepareOnly` 仍要求逐行显式审阅目录，避免覆盖审阅产物。

## 审查与 dry-run

公开入口可用 `execute.ps1 -ExperimentId BEFORE -SemanticDiffAgainst AFTER` 比较同一 campaign 的两条**已展开**实验行；
它内部调用 `prepare.py --semantic-diff-experiment-json`，输出稳定 JSON：
每个字段的旧/新值及其审查类别（物理/场、数值/资源、采样、资格、运行控制或证据）。这是读操作，不参与
schema 验证、cache 命中、handoff 兼容性或资格决策；这些仍由已冻结的 resolved contract 与实际执行边界决定。
在不启动求解器的情况下，可用 `execute.ps1 -ValidateOnly` 对某一行生成并校验其完整 resolved connection 与
composition plan。

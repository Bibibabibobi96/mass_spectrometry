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
没有匹配历史时，运行器默认先执行一次限时、`RESOURCE_CALIBRATION_ONLY` 的真实进程探针，记录峰值后终止
探针进程树，并在**同一次**运行中重规划正式批波次。该策略属于公共调度器而非 campaign、功能或科学合同；
这些合同只能提供安全资源身份，不得关闭校准。探针输出不属于科学或数值证据。
探索的 inline 网格或 trajectory-quality 覆盖使用**已解析数值**而非原 profile ID 匹配画像；因此旧 profile
的峰值不会为不同离散量授权并发，新的组合先以单批 bootstrap 建立自己的观测。

每个 run 必须冻结 `run_config.json`、`summary.json` 和 `run_manifest.json`。缓存只用于完全相同的冻结身份，
且不可替代来源 run。功能成功不自动证明数值收敛、跨求解器等价、参数最优或 Formal 资格。

活动 runtime binding v4 只冻结连接专属的物理/运行合同；共享的
`family_runtime_implementation.json` 由运行时统一解析。authorized/Formal 路径校验每个实现脚本 SHA；
exploration 仅允许实现内容与注册表漂移，并把期望与实际 SHA 写入 run config/receipt，仍关闭角色、路径、
哈希格式和所有物理/输入合同。故一次共享实现更新不再要求逐连接复制同一 implementation binding 或改写其
物理合同；新 prepared plan 仍冻结所选 binding 的原始 SHA。
归档 v2/v3 binding 仅用于历史证据读取，不是活动 authoring 输入。

三区 N=1 路径 smoke 只证明已冻结路径可贯通；其授权 receipt 绑定一个具名后继行的完整行 SHA、
科学身份、粒子顺序摘要和实际粒子数。新合同可授权任意正整数人口，旧 `N100` receipt 仍只授权其原
`N=100` 后继。两者都不构成分辨率、工程资格或 Formal 声明。

## 配置、验证与历史

活动配置位于 [`config/`](../config/)；公共 schema 和文件身份工具位于
[`common/contracts/`](../../../common/contracts/README.md)。修改活动运行器、合同、资源策略或 campaign 后，应运行
项目门禁及仓库级集成门禁。历史文档中的数字、状态和链接均不构成活动授权。

活动 campaign 只由 v6
[`rf_multipole_oatof_experiment_campaign.schema.json`](../config/schemas/rf_multipole_oatof_experiment_campaign.schema.json)
校验。v1–v6 的旧结构只由同目录 `archive/` 下的归档读取 schema 校验，供历史证据审阅与回归使用；
它不被执行入口、活动发现或 resolved-plan 编译器接受。

当前唯一活动 campaign 是 `connector_gap_field_matrix_compact_auto_replay_v2.json`。此前 23 个已发布的逐 gap/field
合同保留原始字节和 receipt，但已退出 lifecycle registry：它们由该 compact replay 完整替代，且不应因后续运行
policy（内存、并发、超时或保留）更新而重新成为可执行 authority。

活动单飞来源仅接受 `continuous_frontend` 与 `pre_pulse_restart`。已归档的 staged Grid2 合同及其逐粒子证据
仍可按归档索引校验，但不再是现行 schema 或运行器可重放的输入。

活动 resolved source contract 仅接受 family v2：它显式按 `comsol` 或 `simion` 记录来源 branch，且运行时只
消费所选 branch。早期 v1 source contract 与其 adapter 仅是历史证据格式，不在活动 schema 或重放入口中保留兼容分支。

实验 campaign 可继续使用完整行，也可用扁平 authoring：`experiments.shared` 声明共同控制，
`variation_axes` 列出允许变化的字段，`rows` 只列行身份和 `overrides`。准备阶段先展开为完整冻结行，
再执行既有 schema 与授权校验；任何未声明的字段变化都失败关闭。这样同一合同可顺序执行多个 gap 或
其他已授权参数点，而不会复制共享输入。

已发布 campaign 如仅改变 authoring 布局，可用 `published_authoring_identity` 保留旧 receipt 的 raw 文件 SHA；
它同时冻结完整的、已展开 campaign 科学语义 SHA。只有二者严格匹配时才接受该旧 SHA；物理、数值、资格或
已注册 campaign 的任一展开行变化都会使 source-binding 检查失败。执行策略另由 runtime binding 和每次 run receipt 冻结，
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

普通探索不必预先登记为活动 authority：将 repository-managed campaign 标为 `"status": "exploration"`，并显式传入
`-Exploration -ValidateOnly`、`-Exploration -PrepareOnly -OutputDirectory ...`，或在准备完可审阅合同后使用
`-Exploration -SolverAuthorized` 执行非正式模拟。该路径仍执行 schema、来源 artifact、单位/frame/clock、粒子和
composition-plan 校验；它不以活动 campaign SHA 或 source-binding 刷新拒绝新的参数组合。探索运行保留普通的缓存、
SHA、manifest 与失败记录，但不能 `FinalizeOnly`、发布正式结果或产生资格结论。

探索的粒子数没有 schema 人为上限；它必须是正整数，并与冻结 source、ordered particle IDs 和分析分母一致。
实际并发由资源调度器按粒子数、CPU 和可用内存决定，不改变 handoff 的科学身份。

下游网格、反射区 cell、trajectory quality 与每周期 RF 步数可选择任一已登记的
`single_flight_*_profile_id`。探索合同还可在
`single_flight_numerical_overrides` 中直接给出正的 `trajectory_quality`、`rf_steps_per_period`，以及
前端/overlay/reflectron 的 cell；prepare 会把最终数值冻结进 `ResolvedExecutionProfile`。这不会修改默认
profile、上游 handoff 或正式资格；正式 campaign 仍以其预登记 profile 为准。

探索若复用一个已冻结的 post-pulse restart source，仍须验证该 source 的 manifest、checkpoint、pulse schedule、
粒子身份和所声明的变化轴；但不必为了只扫描加速场 profile 而附带正式资格专用的 source `z--vz` 理论工作点。
该理论闭合仍是 active/authorized restart 的失败关闭要求。

## 开放任务

- **Windows 路径容量治理（跨工作流）**：公共 `New-RunPackage` 已为采用短 execution junction 的外部求解器
  入口生成结构化容量报告，并在创建 artifact 前以 Windows 传统 API 的 259 字符兼容上限检查 package 核心路径和调用方
  明确声明的预期相对路径；超限 fixture 给出可操作诊断。该上限是兼容性基线，不是对 SIMION、COMSOL 或 MATLAB 的
  未证实专属限制。下一步应逐入口登记深层生成输入/输出，报告其实际绝对路径与已证实的工具限制。短根只能改变进程
  看到的路径表示，不能改变 `run_id`、冻结的相对 artifact 引用、manifest 的真实目标路径、SHA 或科学身份。关闭条件是：
  在启用 Windows 与 Git 长路径支持的干净工作站上，活动 campaign 和至少一个非单飞外部工具入口通过同一公共 preflight；
  各入口不再各自创建未登记的临时 junction、复制或缩短科学/证据文件名。

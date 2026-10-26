# 当前执行身份与失效域

本页只描述活动集成的机器合同边界。当前状态见[INTEGRATION](INTEGRATION.md)，操作见[RUNNING](RUNNING.md)。历史 campaign、完成结果和被替代的执行路径位于
[`HISTORY.md`](HISTORY.md)，不构成当前授权。

## 参数权威与影响范围

| 参数 | 作者权威 | 影响与隔离边界 |
|---|---|---|
| 几何、间隙、坐标 | [连接配置](../config/connection_profiles.json)及两端 port 合同 | 改变下游布局、PA、结果；不改变无关 campaign 的运行控制 |
| 源状态、人口、时钟 | 上游 manifest 及 campaign 的 source/population 声明 | 改变 handoff、初态和结果；不绑定 batch、并发、内存、retention |
| 脉冲前 checkpoint | manifest 绑定的 restart receipt | 决定消费者初态和结果；不反写 producer 后续数值 profile |
| 场、网格、轨迹精度、dt | campaign 的具名数值 profile | 改变消费者结果、数值资格及 cache；不改变已冻结上游 handoff |
| 分析与资格 | 预注册分析与资格合同 | 改变分析和声明；不改变 solver 输入、几何、handoff |
| batch、资源、timeout、retention | 公共执行策略 | 改变调度、运行收据及资源证据；不改变 campaign、PA 或物理 handoff 身份 |
| 正式 campaign 授权 | [生命周期注册](../config/diagnostics/lifecycle_registry.json) | 注册路径和状态决定正式启动资格；保留历史字节，探索不能正式发布 |

Python prepare 将几何交给 resolved connection、源与人口交给各自 resolver，再由 adapter 消费。
脉冲前 restart 由 `materialize_manifest_bound_pre_pulse_restart.py` 物化；下游数值选择来自
`single_flight_*_profile_id`。分析器只消费冻结输入并发布 result receipt。

公共 resource scheduler 经 `resolved_engineering_budget.json` 向 runner 传递预算，campaign 不覆盖
该策略。只有 manifest 核验的单批画像可估算并发，无画像时从单批 bootstrap 开始；画像包含已解析的
grid、reflectron/overlay cell、trajectory quality 与 RF 步数。公开 `execute.ps1` 和 prepare
复核正式授权并冻结 resolved row、来源身份与 execution receipt。
细网格、局部域与 overlay refine 共用首批观测、预算重规划和任务交接；各自保留 PA 身份、
进程规格及完成回执，首批记录只交接一次，观测与后续 wave 始终处于同一重任务阶段。


单飞行分辨率分析从冻结的 `single_flight_initial_global_state.csv` 读取唯一的正 `mass_amu`，不由
PowerShell 或恢复路径另行默认。混合质量需要显式的目标物种分析合同；在该合同存在前，分析会拒绝而不以任意质量计算。

## 生成物与身份

`prepare.py` 将 authoring campaign 展开为完整冻结 experiment，生成 resolved connection、composition plan、
resolved source/population contract 和 engineering budget。冻结的 composition plan 中
`execution_steps[0].arguments` 是唯一执行参数运输；adapter 拒绝重复键、未知字段并复核输入身份与 SHA。
不再生成同义 `resolved_execution_plan.json` 或维护双格式回放分支。
正常发布复核 execution receipt 中 composition plan、resolved connection 与 engineering budget 的原始 SHA；
缺失或不一致时拒绝发布，恢复路径继续由已发布 manifest 绑定来源。
`resolved_engineering_budget.json` 记录完整 SIMION dispatch plan；其 batch 决策必须与 adapter 接收的
批次数一致，但它不是物理 handoff 或 PA content identity。
这些 preparation 生成 JSON 经过同一私有 UTF-8/LF 写入边界；它不重排默认对象字段，也不改变内容哈希、
schema 或任一 resolved contract 的语义。

原始文件 SHA 用于来源、manifest、生成物闭合和审计。跨组件可用性由 schema、单位、frame、clock/event、
粒子身份和明确的字段投影决定；不能仅因无因果的 provenance 或 consumer numerics 差异拒绝合法 checkpoint。
已支持的 manifest-bound restart 会记录 producer/consumer dt，而不是要求两者相同。

下游网格、轨迹质量、最大飞行时间和空间窗口只由冻结的 `ResolvedExecutionProfile` 输入 runner；
runner 不提供会绕过该合同的逐项数值覆盖入口。

分辨率资格由 Python 分析器在显式分析/晋升合同中判定；单飞 runner 不含未被公开 workflow 消费的资格开关。

MATLAB/COMSOL的direct-KDE仅作本地可视化；资格指标由Python发布。历史数值对照见
[全仓参考收口](../../../docs/history/20260911__reference-documentation-consolidation.md)，不在接口合同中重复。

仅服务于本 integration 的 `rf_oatof_*` campaign、resolved plan 与 receipt Schema 均同置于
`config/schemas/`；它们表达该项目的理论审计与运行证据结构，不属于跨项目公共合同。

## 执行路径

```text
registered campaign + lifecycle authority, or explicit exploration campaign
  -> Python prepare / resolved artifacts
  -> PowerShell lifecycle + process orchestration
  -> SIMION runner / raw exports
  -> Python analysis, manifest and qualification receipts
```

对于正式 campaign，生命周期 registry 在两个 authoring 边界复核：`execute.ps1` 保护公开请求入口，
`prepare.py` 保护直接 Python 制备入口且先于源 artifact 读取。adapter、发布与恢复只消费 run-local immutable
frozen experiment、resolved inputs 和 execution receipt，不重新读取作者文件。作者文件的格式化或后续编辑不会
改变已准备运行；冻结来源、candidate、人口及执行输入仍以 SHA 绑定。探索 campaign 不进入正式发布路径。

PowerShell 不定义几何、粒子分布、统计公式或正式阈值；它只读取已解析合同、执行外部进程、保留日志并传递
失败状态。Lua/GEM 只实现已解析的 SIMION 几何与 callback，不拥有实验选择政策。

单飞 runner 为避免 Windows 求解器路径深度限制，使用公共运行包创建的短 execution junction 作为其运行时
目录。该 junction 仅是进程路径表示，目标始终是最终`artifacts/.../runs/<run_id>`；manifest在写入前解析到
真实artifact路径，终态后清理junction。因此它不属于物理、handoff、cache或资格身份，也不改变任何冻结输入
或产物发布位置。

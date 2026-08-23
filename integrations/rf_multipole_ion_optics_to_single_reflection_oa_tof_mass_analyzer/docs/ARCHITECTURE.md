# 当前执行身份与失效域

本页只描述活动集成的机器合同边界。历史 campaign、完成结果和被替代的执行路径位于
[`HISTORY.md`](HISTORY.md)，不构成当前授权。

| 参数类别 | 唯一 authoring authority | resolver / consumer | 失效域 | 不应影响 |
|---|---|---|---|---|
| 几何、连接间隙、坐标/单位/frame | `config/connection_profiles.json` 与两端 port 合同 | Python `prepare.py` → resolved connection → adapter / SIMION | 下游布局、PA basis、结果与证据 | 无关 campaign 的运行控制 |
| 源状态、粒子 ID、species、charge、质量、clock/event | 上游 manifest 和 campaign 的 source / population 声明 | Python source resolver → resolved source/population contract | handoff、下游粒子初态、结果 | batch、并发、内存、retention |
| 脉冲前 checkpoint | manifest-bound restart receipt | `materialize_manifest_bound_pre_pulse_restart.py` → single-flight runner | consumer 初态和消费者结果 | producer 的后续数值 profile |
| 下游 field、mesh/grid、trajectory quality、dt | campaign 的 `single_flight_*_profile_id` | Python prepare → runner arguments → SIMION | 仅消费者数值结果、数值资格和对应 cache | 已冻结的 upstream handoff 状态 |
| 分析与 qualification | campaign preregistration / analysis contract | Python 分析器和 result receipt | analysis result、资格声明 | solver 输入、几何和 particle handoff |
| batch、CPU、内存、timeout、retention | execution policy 与 `single_flight_batch_memory_policy` | Python resource scheduler → `resolved_engineering_budget.json` → runner | dispatch、运行 receipt 和资源使用证据 | campaign/PA/物理 handoff identity |
| 活动 campaign 授权 | `config/diagnostics/lifecycle_registry.json` | `execute.ps1`、prepare、adapter | 是否可启动；campaign SHA 绑定 | 历史 JSON 原始字节与历史结果 |

## 生成物与身份

`prepare.py` 将 authoring campaign 展开为完整冻结 experiment，生成 resolved connection、composition plan、
resolved source/population contract 和 engineering budget。`resolved_engineering_budget.json` 记录完整 SIMION
dispatch plan；其 batch 决策必须与 adapter 接收的批次数一致，但它不是物理 handoff 或 PA content identity。

原始文件 SHA 用于来源、manifest、生成物闭合和审计。跨组件可用性由 schema、单位、frame、clock/event、
粒子身份和明确的字段投影决定；不能仅因无因果的 provenance 或 consumer numerics 差异拒绝合法 checkpoint。
已支持的 manifest-bound restart 会记录 producer/consumer dt，而不是要求两者相同。

## 执行路径

```text
campaign + lifecycle authority
  -> Python prepare / resolved artifacts
  -> PowerShell lifecycle + process orchestration
  -> SIMION runner / raw exports
  -> Python analysis, manifest and qualification receipts
```

PowerShell 不定义几何、粒子分布、统计公式或正式阈值；它只读取已解析合同、执行外部进程、保留日志并传递
失败状态。Lua/GEM 只实现已解析的 SIMION 几何与 callback，不拥有实验选择政策。

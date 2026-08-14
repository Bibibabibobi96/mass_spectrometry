# RF–oaTOF schema-v3 脉冲与粒子总体单权威收口（2026-08-14）

> `DOC_STATUS: CURRENT_IMPLEMENTATION_RECORD`

## 目标与边界

本轮只收口 single-flight 实验中脉冲时刻和粒子总体的机器权威，不改变源物理、加速器/反射器设计、
PA、网格、时间步、轨迹质量或资源门禁，也未启动 SIMION。旧 schema-v1/v2 campaign 继续可读、可审计，
但不再允许以 `SolverAuthorized` 执行 single-flight；需建立 schema-v3 successor 后才能进入 prepare。

旧链路的问题是同一事实可同时来自 campaign、prepare/adapter 参数、runner 默认值和分析器命令行：
脉冲时刻、执行粒子数、eligible/population 分母及 bootstrap 设置可能形成双重权威。schema-v3 将它们
改为两份经 schema 验证并以 SHA-256 绑定的 resolved contract，后续组件只消费合同，观测文件只作
一致性复核，不能反向补缺省值。

## schema-v3 单权威链

```text
campaign.single_flight_pulse_schedule_policy
  -> prepare: derive_pulse_schedule（唯一编译器）
  -> resolved_single_flight_pulse_schedule.json
  -> runner: pulse_effective_time_us

campaign.single_flight_population + 冻结源表
  -> prepare: compile_resolved_population_contract（唯一编译器）
  -> resolved_population_contract.json
  -> adapter / runner / analyzer
```

脉冲合同只保留 `pulse_base_time_us`、`pulse_offset_us`、`pulse_effective_time_us` 三个时钟字段；不再保留
历史 `derived_pulse_time_us` 或 runner/settings fallback。总体合同唯一冻结：总体模式、源角色和表绑定、
执行 N、有序粒子 ID SHA、选择算法和 seed、population/eligible 分母、bootstrap 次数和 seed，以及
postselection policy。生产链不再接受这些量的独立 CLI 覆盖。

schema-v3 single-flight 行还强制显式声明 `architecture_generation_id`、`source_profile_id`、
`field_overlay_id`、`source_release_mode`、`single_flight_pulse_schedule_policy` 和
`single_flight_population`。实现内部仅为读取历史 v1/v2 记录保留对前三项的可选解析；v3 schema 的
`required` 列表在执行前已把它们强制为显式事实，因此不存在新的隐式权威。

当前总体合同支持并逐模式测试六种规范身份：

| population mode | 用途 |
|---|---|
| `staged_three_stage` | 既有三阶段流程 |
| `continuous_injection_full_population` | 连续入口释放全部冻结总体 |
| `resolved_layout_pulse_ideal_linear_z_vz` | 由布局和脉冲解析的理想线性 `z-vz` 源 |
| `pre_pulse_restart` | 冻结 pulse-state restart |
| `pulse_eligible_conditional` | 明确有 selection receipt 的条件诊断 |
| `first_100_rows_in_frozen_file_order` | 冻结文件顺序的确定性前 100 行 |

除 `pulse_eligible_conditional` 必须满足 `eligible >= executed` 外，其余模式只要求声明总体可容纳执行
粒子；例如连续入口总体允许执行 1000、detector-blind eligible 为 695，分析器不得把 695 反向解释为
执行总体。

独立审查后进一步把六种模式收紧为判别式合同；任一行只能采用下表唯一组合，跨行替换任一字段都由
campaign schema和resolved-contract schema失败关闭。`input_role`不硬编码到模式，因为它属于冻结源
manifest的角色身份；编译器仍要求声明值与实际源表逐字一致。

| population mode | execution strategy | source release | table binding | selection algorithm | postselection |
|---|---|---|---|---|---|
| `staged_three_stage` | `staged_three_stage` | 禁止/不适用 | `staged_upstream_source` | `all_rows_in_frozen_file_order` | `prohibited` |
| `continuous_injection_full_population` | `simion_single_flight` | `continuous_frontend` | `source_contract_particle_source` | `all_rows_in_frozen_file_order` | `prohibited` |
| `resolved_layout_pulse_ideal_linear_z_vz` | `simion_single_flight` | `continuous_frontend` | `prepared_materialized_particle_source` | `all_rows_in_frozen_file_order` | `prohibited` |
| `pre_pulse_restart` | `simion_single_flight` | `pre_pulse_restart` | `experiment_pre_pulse_source_state` | `all_rows_in_frozen_file_order` | `prohibited` |
| `pulse_eligible_conditional` | `simion_single_flight` | `continuous_frontend` | `experiment_single_flight_particle_source` | `all_rows_in_frozen_file_order` | `pulse_eligibility_only` |
| `first_100_rows_in_frozen_file_order` | `simion_single_flight` | `continuous_frontend` | `prepared_deterministic_prefix` | `first_100_rows_in_frozen_file_order` | `prohibited` |

single-flight runner只从resolved population读取`source_release_mode`，adapter不再把campaign/frozen值作为
runner参数重复传递；这些历史值只用于与resolved contract交叉校验。run config也不再复制该字段作为
参数权威。runner对六种mode逐项穷举：`staged_three_stage`明确拒绝进入single-flight，未知mode没有
continuous fallback而直接失败关闭。

## 正式 schema-v3 successors

两份新 campaign 不覆盖或改写既有发布物：

1. `canonical_source_architecture_accelerator_field_matrix_n1000_v3_successor_campaign`：24 行，覆盖
   理想 1 mm、理想 2.2 mm、真实八极杆束，短/长焦及 RR/II/IR/RI。run ID 从
   `20260814_152844__sim__cross__matrix-ideal1mm-short-rr__n1000` 连续到
   `20260814_152907__sim__cross__matrix-realoct-long-ri__n1000`。
2. `canonical_long_full_domain_restart_affine_width_numerics_n1000_v3_successor`：5 行，使用明确的
   full-domain restart 命名，覆盖 1/1.5/2.2 mm 和 2.2 mm 的 dt/T.Qual 数值对照。run ID 从
   `20260814_152908__sim__cross__long-full-domain-restart-affine-1mm-q8-dt160__n1000` 到
   `20260814_152912__sim__cross__long-full-domain-restart-affine-2p2mm-q108-dt160__n1000`。

29 行均冻结 N=1000 的有序粒子 ID SHA-256
`0DE41D33D8E41EE4A69E898BCBCC42F7C9E65F7CDCE1239A00DEF95EF7DD206B`。全部 run ID 分别通过
官方 `artifact_naming` 合同，UTC 时间戳无重复；全仓文本和相关 artifacts 目录未发现身份碰撞。第二组
不再沿用会误导物理语义的历史 `Arm8` 可执行名称，`Arm8` 只保留在 claim-limit lineage 中。

## 验证收据

在未启动求解器的条件下完成：

- 两份 successor 的 campaign source bindings 刷新后 `--check` 通过；repository-text bindings 由
  官方刷新器单向更新并通过 `--check`。
- 29/29 行经唯一公开入口 `execute.ps1 -ValidateOnly` 通过，证明 schema、源绑定、脉冲编译、总体编译、
  prepare/adapter 失败关闭和 run plan 串联闭合。
- 初始实现聚焦回归55/55、integration全量328/328通过；独立审查收紧判别式与release单权威后，聚焦
  回归59/59、integration全量332/332通过。
- 仓库 `common/verify_changed.ps1` L1 最终 PASS，其中 common contracts 178/178、integration 328/328，
  其余直接依赖项目静态门禁全部 PASS；CLOC 2.10 delta 门禁 PASS。独立审查收紧后相对 HEAD 增加
  4504 CLOC：production 4048、tests 456，其中 JSON 3808 行主要是两份声明式campaign及判别式schema，
  不是第二套运行逻辑。

这些验证只授予 schema-v3 执行准备链的实现证据，不产生新的物理结果，也不把 29 个 successor 标记为
已运行。后续真模拟仍需按资源门禁和实验先后顺序单独授权。

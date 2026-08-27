# C1：S1 三点 connector-gap 残差—传输率合同

> `STATUS: PLANNED / DETECTOR_BLIND_SOURCE_ONLY / EXECUTE_SIMION_SERIALly`

## 目标

在同一个 S1 多极杆入口母群中，检验 `gap=0 / 51.2 / 102.4 mm`
是否形成预期的**条件轴向随机残差降低—完整母群传输下降**权衡。此合同只建立 C1
源侧证据；不得由 detector、FWHM、分辨率、优化器或 C2/C3 输出选择脉冲时刻。

## 冻结对象与唯一变量

- 根母 cohort：既有 S1 多极杆入口 `N=5000`。每个臂均从这同一有序的 5000 ID 独立释放、贯通
  多极杆—connector—OA 前端；不得把一个 gap 的 terminal handoff 幸存者预先作为另一 gap 的输入。
  不创建 N=100 子样本，也不把共同存活 ID 当作传输分母。选择 5000 的原因是历史 102.4 mm
  通过率约为 1%；其预期约 50 个幸存者，N=1000 预期约 10 个，不足以稳定估计长 gap 的条件残差。
- 臂：`rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm`、
  `rf_octupole_to_single_reflection_oatof_direct_mating_gap_51p2mm`、
  `rf_octupole_to_single_reflection_oatof_direct_mating_gap_102p4mm`。
- 不变项：S1 entrance source SHA、RF 波形/相位、多极杆、前端孔径与场 profile、三区 Candidate、数值
  profile、质量和完整母群 ID 顺序。
- 唯一物理变量：连接器长度及其由 connection profile 明示的、连续接地屏蔽几何。

## 每臂的固定执行顺序

1. 先由现有 integration pulse 机制按冻结身份复用已有的验证时刻；若没有完全相同身份的 receipt，
   则用同一 `multipole_handoff_ballistic_centroid_v1` 确定性派生每臂时刻。两者是本实验唯一的时刻
   机制，禁止另行以时间窗、detector 或峰宽重选时刻。
2. 以该时刻运行一次真实 PA、RF、全 5000-ID 连续飞行。三臂必须统一采用
   `integration_fixed_pulse`，或统一采用与各自 resolved pulse epoch 逐项绑定的
   `pulse_disabled_time_series`；不得混用，也不得把后者称为 pulse-on checkpoint。由该统一模式的
   OA 前状态建立源侧模型与完整命中/损失账本。多极杆内损失、connector/前端损失、加速器前缺失和
   pulse 不适格必须分开记录。
3. 三臂均完成后，按请求中冻结的粒子 ID hash 分区划分 development/validation/optimization/locked-test；
   每臂只用 development 拟合、validation 选阶，且仅用共同 locked IDs 计算配对残差。共同 ID 仅是
   因果诊断；传输率一律相对 5000 入口母群报告。旧的 900 terminal-handoff 分母只可作为历史条件诊断，
   不进入本合同的主结果。

## C1 门槛与结论

| 判据 | PASS_CONTINUE | INCONCLUSIVE_REVISE |
| --- | --- | --- |
| 三臂 pulse-on 连续飞行 | 都成功，且 pre-pulse checkpoint、解析脉冲时刻与 manifest 相互绑定 | 任一臂无可用状态、或飞行失败；不得用扫窗取代该负结果 |
| ID 与分母 | 三臂入口 ID hash 相同，且每臂均从 5000 起算并保留完整损失分类 | 预先固定 terminal-handoff 幸存者、或共同存活者替代了母群分母 |
| 残差比较 | 报告各相邻 gap 对实际共同 locked-ID 数、有效样本量和 bootstrap CI；据此判定其是否足以支持条件残差比较 | 样本不足或模型选择不稳定 |
| 机制方向 | 长 gap 的条件残差变化与传输变化均以 CI 报告；不要求单调才记录负结果 | 无法把脉冲时序失配与几何效应区分 |

`PASS_CONTINUE` 只表示三点的 detector-blind 源侧 trade-off 已被量化，可作为 C2 的冻结输入。
不支持“gap 最优”“分辨率改善”“三区优越”或论文性能主张。若某个臂的条件残差没有下降，但 pulse
确认和分母闭合，结论应保留为有效负结果，而非重选 detector 最优时刻。

## 与 C2/C3 的依赖

- C2 必须读取本合同冻结的三臂 source model、协方差、尾部、发射度、适格率和 loss census；不得使用
  历史 gap×field 的峰宽表替代。
- C3 的独立轴场积分器与该合同物理上独立，但真实 SIMION 运行与本合同共用商业求解器、PA cache 和
  artifact 生命周期，故外层运行严格串行。C3 的纯 Python/静态诊断可以并行准备。

## 三臂发布入口

三臂都成功后，使用唯一分析器
`python -m projects.single_reflection_oa_tof_mass_analyzer.analysis.analyze_paper1_connector_gap_residual --triplet-request <request.json>`
（从仓库根目录执行）发布 C1 的五件套。
request 必须精确列出 `0/51.2/102.4 mm`、同一 `N=5000`母群、状态表及其成功 receipt/manifest，并把
`required_checkpoint_kind`固定为三臂共同的单一模式。可接受的模式只有：

- `integration_fixed_pulse`：每臂的成功 summary/manifest 直接绑定`pre_pulse_state`与
  `pulse_effective_time_us`；
- `pulse_disabled_time_series`：只在三臂都采用该模式，且每臂都提供
  `resolved_pulse_epoch_state_equivalence_v1`时接受。该证据必须把所选 sample 的时间、RF grid origin
  和 receipt census 逐一绑定到同一 run-local `resolved_single_flight_pulse_schedule.json`的
  `pulse_effective_time_us`，并核验 source、RF、pre-pulse field、Candidate 和数值身份。

后者在产物中只能标为`PRE_PULSE_EQUIVALENT_TIME_SERIES`，绝不可写为 fixed pulse。分析器会核验三臂的
同源 source/ID、几何、Candidate 和数值身份，逐臂保留完整母群分母，并只比较相邻臂的 common locked-ID
轴向残差。

## C1-v2：低传输长 gap 的盲分区修订

`C1-v1` 已作为不可覆盖的 `INCONCLUSIVE_REVISE` 证据保留：三臂均成功且 51.2/102.4 mm 有 116 个共同
预脉冲 ID，但 v1 的固定 15% locked-test 配额只分到 17 个，低于合同的 32 个最低样本量。这是**分区设计
与已知长 gap 低传输不匹配**，不是残差方向、FWHM 或 detector 结果的失败。

因此 C1-v2 只允许对完全相同、已冻结的三臂 pre-pulse 状态做一次 detector-blind 重分析；不重跑轨迹，
不读取 detector 数据，也不覆盖 v1 的五件套。v2 request 必须使用 `schema_version: 2` 并精确声明：

```json
{
  "cohort_partition": {
    "role": "detector_blind_hash_partition",
    "development_upper_fraction": 0.40,
    "validation_upper_fraction": 0.55,
    "optimization_upper_fraction": 0.65,
    "locked_test_upper_fraction": 1.00
  }
}
```

这给出 `40% / 15% / 10% / 35%` 的四个角色。选择依据仅为长 gap 预注册的最低建模样本量
（development ≥8、validation ≥4）和相邻共同 locked ID ≥32；不得根据任何残差、峰宽、命中、优化或
detector 结果选择边界或 salt。v2 仍只支持 source-side C1 结论；后续 C2/C4 必须注册自己的冻结 cohort，
不得把 v2 的 locked-test 重用为后续 detector 预测测试。

若三臂混用两种模式、time-series sample 不在其 resolved pulse epoch、RF/field/numerical/source identity
不一致，或实际 receipt/manifest 不满足所声明模式，发布器必须写出`INCONCLUSIVE_REVISE`及失败原因；
不得把 time-series sample 改名为 fixed-pulse checkpoint。成功发布目录只含
`stage_contract.md`、`stage_manifest.json`、`stage_report.md/json`和`stage_conclusion.md`。

## 当前状态

- 0 mm（`...gap0...n5000__r09`）与 51.2 mm（`...gap51p2...n5000__r03`）已各自完成
  N=5000 的 `continuous_frontend` detector-blind time-series 运行；102.4 mm
  （`...gap102p4...n5000__r02`）也已完成。三臂均通过统一 `PRE_PULSE_EQUIVALENT_TIME_SERIES`、resolved epoch
  和 frozen-identity 核验。
- C1-v1 五件套已发布为 `INCONCLUSIVE_REVISE`，唯一失败原因是 51.2/102.4 mm 的 common locked-test ID 为
  17，低于 32；其余输入与完整 5000-ID 分母均保留为负结果证据。
- 下一步：按本节 C1-v2 的固定盲分区重新发布**独立**五件套。历史 23 臂 gap×field 结果始终为
  `DEVELOPMENT_ONLY`，不进入统计输入；用户现有的 0 mm、N=1000 terminal-handoff 文件保持不改。

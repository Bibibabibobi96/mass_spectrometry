# Paper 1：connector gap 配对源残差合同

> `STATUS: ACTIVE_EXPLORATION / DETECTOR_BLIND_SOURCE_ONLY / REAL_FIELD_PULSE_CONFIRMATION_REQUIRED`

三点 `0 / 51.2 / 102.4 mm` 的后继执行顺序、完整母群分母与 C2/C3 依赖现由
[`C1 triplet contract`](stage_c1_connector_gap_triplet_contract.md)唯一规定；本文保留已发生的双臂
证据与其可用边界，不把历史结果升级为三臂结论。

## 问题

检验“连接器加长是否改变 OA 脉冲前的不可预测轴向残差”，而不是重用历史 gap×field 峰宽趋势。这里的
`gap`仅指多极杆终端到 oaTOF 前端的连接器长度；它会改变交接后的漂移、边缘场、孔径损失和到达脉冲面
的相空间，不能被视为下游分析器不变时必然无关的几何量。

## 冻结对照

- **0 mm 对照：** S1 terminal-octupole 的 N=1000 母 cohort，900 个 transmitted terminal handoff。
- **51.2 mm 实验：** 完全相同的 S1 母 cohort 和 900 个 transmitted terminal handoff。
- 唯一物理改变为连接 profile；上游 S1 的 N=1000 母表、source SHA、RF source、布局、场 profile、数值
  profile、三分区候选和脉冲策略必须相同。
- 每臂首先由既有 `multipole_handoff_ballistic_centroid_v1` 给出**弹道种子时刻**，而非把该无场外推值
  误作真实前端场中的最终脉冲时刻。随后必须复用 integration 已有的
  `auto_detector_blind_discovery_and_confirmation_v1`：以完整冻结 handoff ID、真实前端/加速器 PA 和
  固定 RF 时间网格物化脉冲前状态，按既有的 `pulse_eligible_count → transverse_bore_count → source-region
  moments → 与种子距离` 次序选择一个候选，并在 pulse-on run 中确认。整个选择过程禁止读取 detector、
  峰宽、分辨率或下游传输结果。

调度器必须按仓库公共策略决定正式批并行度；该合同不携带 CPU、内存或并发覆盖。900 是 S1 已冻结的全部
transmitted terminal handoff 数，不是为加速而缩小的统计样本；完整 N=1000 母分母仍保留。

## 判定方法

`analyze_paper1_connector_gap_residual.py`仅读取每臂由成功 run manifest 和 summary 绑定的
`pre_pulse_state` checkpoint：

1. 以同一 source particle ID hash 划分 development、validation、optimization、locked test；
2. 每臂在 development 拟合 `v_z(z)` 的 1/2/3 次模型，以 validation 选择次数；
3. 仅对两臂都存活的 locked IDs 比较平方残差；paired bootstrap 给出二臂 MSE 差的 95% CI；
4. 同时报告每臂母群、900 handoff、OA 前观测与缺失数，并验证两臂的 handoff particle-ID hash 相同。
   共同 ID 只服务因果诊断，绝不可作为 FWHM/传输的
   共同幸存者筛选。

若 CI 不能支持方向或共同 locked IDs 少于32，结论为`INCONCLUSIVE_REVISE`；若支持残差降低，也只支持
“该冻结 S1、两 gap、无碰撞独立粒子链中的 detector-blind source residual 改变”。它不是 gap 最优、J2/J3
优势或投稿性能结论。之后才可决定是否把该源条件纳入修订后的 C2，而非直接进入 C3。

## 弹道种子失配与真实场确认

下列固定脉冲运行保留以审计“把弹道种子错误地当作最终脉冲”这一失配；它们是
`DEVELOPMENT_ONLY`，不进入配对残差分析，也不能排除任何 gap。当前固定种子配置为：

- [`paper1_s1_connector_gap0_fixed_pulse_n1000.json`](../../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_s1_connector_gap0_fixed_pulse_n1000.json)
- [`paper1_s1_connector_gap51p2_fixed_pulse_n1000.json`](../../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_s1_connector_gap51p2_fixed_pulse_n1000.json)

两者均已完成 direct fixed-pulse 运行并通过只分析恢复的 manifest 复核，但不能作为最终脉冲的运行
身份。最终脉冲只接受 manifest-bound、真实场 detector-blind candidate-confirmation receipt。

## 2026-08-26 直接 integration 脉冲结果

| 臂 | 恢复后的成功运行 | integration 脉冲时刻 | 900 handoff 后的 OA 脉冲前状态 | 脉冲适格数 | 检测器命中 |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 mm | `20260826_011500__analysis__simion__recovered-single-flight__n900__r02` | 45.5649582037 µs | 875 | 875 | 873 |
| 51.2 mm | `20260826_011600__analysis__simion__recovered-single-flight__n900` | 57.3440193779 µs | 4 | 0 | 0 |

两个 run 均使用同一 S1 母 cohort、同一 900 transmitted handoff ID hash
`A7148D0914CC2B30C2911C0CC91A0D310772EA1842075824498A24729D6ED84A`。51.2 mm 的 4 个
脉冲前状态均在横向 bore 外；其余 896 个在脉冲前缺失，且 105 个虽记录到 grid1 前向事件但没有任何粒子
到达 intermediate2、出口或 detector。这是完整母 cohort 的实际损失账本，不是共同幸存者筛选。

**结论：`INCONCLUSIVE_REVISE`（仅针对“把弹道种子直接用作最终脉冲”的错误用法）。**
该臂的脉冲适格数为零，因此这一次 run 不能形成 development/validation/locked-test 残差模型；它不构成
长 gap 无效、更不能反证“长 gap 降低条件随机残差”。正确后继是使用已有的 detector-blind real-field
confirmation，而不是重设计连接器或把无效种子推进 C2/C3。

### 2026-08-25—26 真实场脉冲确认

51.2 mm 的真实 `N=900` 脉冲前子运行已成功物化时间序列：前 177/321 个时刻仍有粒子存活。
修正后的 selector 确认全部 177 个仍存活样本的 `pulse_eligible_count=0` 且`source_region_count=0`，
因而以 `real-field pulse screen has no pulse-eligible states` 失败关闭。此结果不表示残差改善、恶化或无效，
只表示当前 gap、时间窗、pulse-anchor 与空间捕获窗口组合不具备本合同要求的可选择 OA 前状态。
失败父 run 和成功子 run 均保留在 artifacts；未将共同幸存者、下游 detector 或峰宽用于绕过该条件。

`20260825_235102__analysis__python__paper1-s1-gap51p2-pre-pulse-publication-replay__n1000`是在修复
“尾部全损失不能阻断早期样本”后生成的诊断 replay；它暴露上述零可捕获状态缺口，不能作为成功候选证据。

结论：初始窄网格为`INCONCLUSIVE_REVISE`，原因是其覆盖范围不足；这不是对 gap 的物理否定。后继只可
使用同一 integration 的全母 cohort、真实场、detector-blind confirmation 路径；不得由 detector 或峰宽
回选脉冲。

上述结论只适用于最初的窄时间窗，不能外推到 51.2 mm gap 本身。2026-08-26 的修订窗口以同一
S1 母 cohort、同一真实 PA 和同一 RF 步长，扫描 `46.5485648325` 至 `58.8440193779 us`（2165 个
时刻，步长约 `5.682 ns`），覆盖 ballistic seed 的上游传播时间。它在不读取 detector、FWHM 或
分辨率的前提下找到候选时刻 `54.0656102870 us`：screening 分母为 900 个已交接粒子（上游来源母分母
仍为 1000），候选时刻有 76 个存活且横向 bore 合格的粒子，其中 16 个位于注册的 source region。该结果只证明“这个长 gap 存在可选择的
OA 脉冲前状态”；不证明随机残差变小、聚焦改善或传输合格。

本次也暴露并修复了两个证据链缺口：确认网格必须允许整体落在 ballistic seed 上游，且
`pre_pulse_time_series_states.csv` 与大型候选选择 receipt 都被列为紧凑保留中的必留 child→parent
证据。旧 `001500` 父运行的同类状态表已按旧规则删除，所以受审计的只读重放正确拒绝了它；首次
`002000` 尝试也因重用 child run ID 而安全失败，两份失败父记录均保持失败，未被改写为成功。

以相同冻结输入建立的重试链
`20260826_002000__sim__cross__paper1-s1-gap51p2-real-field-window-pre-pulse__n1000__r01` 及其
N=900 child 均已成功通过 manifest 复核。候选时刻的 76/900 粒子全部处于加速器 bore 且脉冲适格，
其中 16 个在注册 source region；候选比弹道种子早 `3.2784090909 µs`。这证明原固定种子是时序失配，
不证明残差已经降低。它是本合同当前有效的 51.2 mm **候选确认前驱**；下一步以同源 0 mm 的相同
real-field confirmation 建立另一臂，再对两个已确认脉冲的预脉冲状态进行配对残差分析。

## 机制主张与边界

本合同采用的机制先验是：在同一完整母 cohort、相同入口接受定义和各 gap 自己的真实场 detector-blind
确认脉冲下，较长连接器提供额外传播距离，使纵向相关及高阶残差在可抽取截面上重新组织；对本架构，
正确选择的脉冲切片预期具有更小的条件随机残差，而进入加速器且满足该切片条件的粒子数会降低。历史
23 臂 `gap×field` 工作支持这一机制，但其已恢复的汇总没有保留统一母 cohort、共同 ID 配对和完整条件
残差统计，故不得用其中直接 FWHM 的方向替代该机制或作为投稿证据。本合同的任务是以新的配对、盲选
脉冲运行量化残差收益及其完整母 cohort 的传输/损失代价；无粒子进入冻结的 integration 脉冲时刻只
表示该脉冲合同没有覆盖可用切片，C1 应记录为 `INCONCLUSIVE_REVISE`，不能单独反证长 gap 机制，也
不得在同一合同中通过扫窗重选时刻。它不主张完整六维相空间体积无碰撞地减少，
不主张任意脉冲时刻都改善，也不把历史结果直接升级为投稿性能证据。

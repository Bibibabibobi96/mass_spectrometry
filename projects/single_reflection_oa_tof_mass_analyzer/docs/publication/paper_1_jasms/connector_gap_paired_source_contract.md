# Paper 1：connector gap 配对源残差合同

> `STATUS: SUPERSEDED_TWO_ARM_CONTRACT / DETECTOR_BLIND_SOURCE_ONLY`

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

## 历史证据与后继

双臂脉冲种子失配、窗口修复和候选确认过程已冻结到
[状态沿革](../../history/20260911__publication-status-consolidation.md#connector_gap_paired_source_contract)。
这些证据仅用于解释本合同的前驱与失败边界；新工作按三臂合同进入，不沿用旧文中的“下一步”。

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

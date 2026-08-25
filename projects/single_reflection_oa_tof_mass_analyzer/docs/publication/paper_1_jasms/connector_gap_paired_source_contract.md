# Paper 1：connector gap 配对源残差合同

> `STATUS: ACTIVE_EXPLORATION / DETECTOR_BLIND_SOURCE_ONLY`

## 问题

检验“连接器加长是否改变 OA 脉冲前的不可预测轴向残差”，而不是重用历史 gap×field 峰宽趋势。这里的
`gap`仅指多极杆终端到 oaTOF 前端的连接器长度；它会改变交接后的漂移、边缘场、孔径损失和到达脉冲面
的相空间，不能被视为下游分析器不变时必然无关的几何量。

## 冻结对照

- **0 mm 对照：** 已冻结 S1 terminal-octupole N=1000 pulse-disabled pre-pulse screen。
- **51.2 mm 实验：**
  [`paper1_s1_connector_gap51p2_pre_pulse_n1000.json`](../../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_s1_connector_gap51p2_pre_pulse_n1000.json)。
- 唯一物理改变为连接 profile；上游 S1 的 N=1000 母表、source SHA、RF source、布局、场 profile、数值
  profile、三分区候选和脉冲策略必须相同。
- 每臂只运行 OA 脉冲前 `frontend + accelerator` 时间序列；禁止 detector crossing、峰宽、优化和候选结论。

调度器必须按仓库公共策略决定正式批并行度；该合同不携带 CPU、内存或并发覆盖。900 是 S1 已冻结的全部
transmitted terminal handoff 数，不是为加速而缩小的统计样本；完整 N=1000 母分母仍保留。

## 判定方法

`analyze_paper1_connector_gap_residual.py`仅读取每臂 detector-blind 选定时刻的状态和其 receipt：

1. 以同一 source particle ID hash 划分 development、validation、optimization、locked test；
2. 每臂在 development 拟合 `v_z(z)` 的 1/2/3 次模型，以 validation 选择次数；
3. 仅对两臂都存活的 locked IDs 比较平方残差；paired bootstrap 给出二臂 MSE 差的 95% CI；
4. 同时报告每臂母群、screened、OA 前观测与缺失数。共同 ID 只服务因果诊断，绝不可作为 FWHM/传输的
   共同幸存者筛选。

若 CI 不能支持方向或共同 locked IDs 少于32，结论为`INCONCLUSIVE_REVISE`；若支持残差降低，也只支持
“该冻结 S1、两 gap、无碰撞独立粒子链中的 detector-blind source residual 改变”。它不是 gap 最优、J2/J3
优势或投稿性能结论。之后才可决定是否把该源条件纳入修订后的 C2，而非直接进入 C3。

## 2026-08-25 执行结果：不适格，未作残差比较

51.2 mm 的真实 `N=900` 脉冲前子运行已成功物化时间序列，但在冻结的 321 个采样时刻中没有存活粒子。
受治理的 publication replay 因而以 `real-field pulse candidate has no alive states` 失败关闭；这不表示
残差改善、恶化或无效，只表示当前 gap、时间窗和 pulse-anchor 组合不具备本合同要求的可选择 OA 前状态。
失败父 run 和成功子 run 均保留在 artifacts；未将共同幸存者、下游 detector 或峰宽用于绕过该条件。

结论：本臂为`INCONCLUSIVE_REVISE`。在重订能够覆盖该连接器传播时间的 detector-blind 时间窗之前，
不得运行 `analyze_paper1_connector_gap_residual.py`、不得用此 gap 修订 C2，也不得据此进入 C3。

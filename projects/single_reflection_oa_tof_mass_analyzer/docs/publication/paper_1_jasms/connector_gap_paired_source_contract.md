# Paper 1：connector gap 配对源残差合同

> `STATUS: ACTIVE_EXPLORATION / DETECTOR_BLIND_SOURCE_ONLY`

## 问题

检验“连接器加长是否改变 OA 脉冲前的不可预测轴向残差”，而不是重用历史 gap×field 峰宽趋势。这里的
`gap`仅指多极杆终端到 oaTOF 前端的连接器长度；它会改变交接后的漂移、边缘场、孔径损失和到达脉冲面
的相空间，不能被视为下游分析器不变时必然无关的几何量。

## 冻结对照

- **0 mm 对照：** 已冻结 S1 terminal-octupole N=1000 pulse-disabled pre-pulse screen。
- **51.2 mm 实验：** 冻结 exploration 输入仅保存在其失败父 run 的
  `inputs/frozen_campaign_experiment.json`；未提交一个可被误重放的活动配置。
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

## 2026-08-25—26 执行结果：时间窗已修订，仍未作残差比较

51.2 mm 的真实 `N=900` 脉冲前子运行已成功物化时间序列：前 177/321 个时刻仍有粒子存活。
修正后的 selector 确认全部 177 个仍存活样本的 `pulse_eligible_count=0` 且`source_region_count=0`，
因而以 `real-field pulse screen has no pulse-eligible states` 失败关闭。此结果不表示残差改善、恶化或无效，
只表示当前 gap、时间窗、pulse-anchor 与空间捕获窗口组合不具备本合同要求的可选择 OA 前状态。
失败父 run 和成功子 run 均保留在 artifacts；未将共同幸存者、下游 detector 或峰宽用于绕过该条件。

`20260825_235102__analysis__python__paper1-s1-gap51p2-pre-pulse-publication-replay__n1000`是在修复
“尾部全损失不能阻断早期样本”后生成的诊断 replay；它暴露上述零可捕获状态缺口，不能作为成功候选证据。

结论：本臂为`INCONCLUSIVE_REVISE`。在重订能够覆盖该连接器传播时间的 detector-blind 时间窗之前，
不得运行 `analyze_paper1_connector_gap_residual.py`、不得用此 gap 修订 C2，也不得据此进入 C3。

上述结论只适用于最初的窄时间窗，不能外推到 51.2 mm gap 本身。2026-08-26 的修订窗口以同一
S1 母 cohort、同一真实 PA 和同一 RF 步长，扫描 `46.5485648325` 至 `58.8440193779 us`（2165 个
时刻，步长约 `5.682 ns`），覆盖 ballistic seed 的上游传播时间。它在不读取 detector、FWHM 或
分辨率的前提下找到候选时刻 `54.0656102870 us`：screening 分母为 900 个已交接粒子（上游来源母分母
仍为 1000），候选时刻有 76 个存活且横向 bore 合格的粒子，其中 16 个位于注册的 source region。该结果只证明“这个长 gap 存在可选择的
OA 脉冲前状态”；不证明随机残差变小、聚焦改善或传输合格。

本次也暴露并修复了两个证据链缺口：时间窗允许整体落在 ballistic seed 上游，且
`pre_pulse_time_series_states.csv` 与大型候选选择 receipt 都被列为紧凑保留中的必留 child→parent
证据。旧 `001500` 父运行的同类状态表已按旧规则删除，所以受审计的只读重放正确拒绝了它；首次
`002000` 尝试也因重用 child run ID 而安全失败，两份失败父记录均保持失败，未被改写为成功。

以相同冻结输入建立的重试链
`20260826_002000__sim__cross__paper1-s1-gap51p2-real-field-window-pre-pulse__n1000__r01` 及其
N=900 child 均已成功通过 manifest 复核。它是本合同当前有效的 51.2 mm 臂；下一步可建立同源 0 mm
臂，再把两侧的预脉冲状态输入配对残差分析。

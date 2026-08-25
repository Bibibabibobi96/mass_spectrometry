# Paper 1：connector gap 配对源残差合同

> `STATUS: ACTIVE_EXPLORATION / DETECTOR_BLIND_SOURCE_ONLY / FIXED_INTEGRATION_PULSE`

## 问题

检验“连接器加长是否改变 OA 脉冲前的不可预测轴向残差”，而不是重用历史 gap×field 峰宽趋势。这里的
`gap`仅指多极杆终端到 oaTOF 前端的连接器长度；它会改变交接后的漂移、边缘场、孔径损失和到达脉冲面
的相空间，不能被视为下游分析器不变时必然无关的几何量。

## 冻结对照

- **0 mm 对照：** S1 terminal-octupole 的 N=1000 母 cohort，900 个 transmitted terminal handoff。
- **51.2 mm 实验：** 完全相同的 S1 母 cohort 和 900 个 transmitted terminal handoff。
- 唯一物理改变为连接 profile；上游 S1 的 N=1000 母表、source SHA、RF source、布局、场 profile、数值
  profile、三分区候选和脉冲策略必须相同。
- 每臂的唯一取样时刻是该臂冻结 `resolved_single_flight_pulse_schedule.json` 的
  `pulse_effective_time_us`。它由既有 `multipole_handoff_ballistic_centroid_v1` integration 机制解析；
  不做 RF 时间窗扫描、不执行 pulse-disabled screen、也不由 detector、峰宽或传输结果选择时刻。

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

## 已废止的时间窗诊断记录

下列记录保留以审计此前的 pulse-disabled time-series 探索和它暴露的实现问题；它们均为
`DEVELOPMENT_ONLY`，不再是本合同的输入，也不进入 paired residual analysis。当前有效运行配置为：

- [`paper1_s1_connector_gap0_fixed_pulse_n1000.json`](../../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_s1_connector_gap0_fixed_pulse_n1000.json)
- [`paper1_s1_connector_gap51p2_fixed_pulse_n1000.json`](../../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_s1_connector_gap51p2_fixed_pulse_n1000.json)

两者均已完成 direct fixed-pulse 运行并通过只分析恢复的 manifest 复核，但未产生可比较的残差样本。

## 2026-08-26 直接 integration 脉冲结果

| 臂 | 恢复后的成功运行 | integration 脉冲时刻 | 900 handoff 后的 OA 脉冲前状态 | 脉冲适格数 | 检测器命中 |
| --- | --- | ---: | ---: | ---: | ---: |
| 0 mm | `20260826_011500__analysis__simion__recovered-single-flight__n900__r02` | 45.5649582037 µs | 875 | 875 | 873 |
| 51.2 mm | `20260826_011600__analysis__simion__recovered-single-flight__n900` | 57.3440193779 µs | 4 | 0 | 0 |

两个 run 均使用同一 S1 母 cohort、同一 900 transmitted handoff ID hash
`A7148D0914CC2B30C2911C0CC91A0D310772EA1842075824498A24729D6ED84A`。51.2 mm 的 4 个
脉冲前状态均在横向 bore 外；其余 896 个在脉冲前缺失，且 105 个虽记录到 grid1 前向事件但没有任何粒子
到达 intermediate2、出口或 detector。这是完整母 cohort 的实际损失账本，不是共同幸存者筛选。

**结论：`FAIL_STOP`（仅针对“以 51.2 mm gap 作为固定 integration 脉冲的配对残差臂”）。**
该臂的脉冲适格数为零，无法形成 development/validation/locked-test 残差模型；因此不能声称大 gap 降低
随机残差，也不能以其支持 J2/J3、聚焦改善或投稿性能。该失败不否定历史时间窗探索中“某些时刻存在
可选择状态”的诊断现象，但两者不可替代：后者是 `DEVELOPMENT_ONLY`，而本文的主合同禁止按窗口选择时刻。
在重新设计连接器/入口几何或重新预注册可物理解释的脉冲契约前，不得将这个长 gap 推进到 C2/C3。

### 2026-08-25—26 时间窗探索

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

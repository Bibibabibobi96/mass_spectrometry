# Paper 1 阶段 1：探测器盲源合同

> `STATUS: DEVELOPMENT_ONLY / PROSPECTIVE_C1_REBUILD_REQUIRED`

## 术语（本页及后续报告的唯一含义）

- **阶段 1：探测器盲源侧识别**：只以 OA 提取脉冲前的粒子状态建立条件源模型；机器阶段 ID 为
  `C1`。`C1`不是物理量，也不是源工况名称。
- **终端八极杆源工况**：RF 八极杆末端直接连接 OA-TOF 前端的来源条件；历史机器短名为 `S1`。
- **分段六极杆源工况**：具有分段轴向加速电极的 RF 六极杆来源条件；历史机器短名为 `S2`。

面向读者的结论、图题和普通叙述必须使用上述全称。`C1`、`S1`、`S2`只可出现在既有 run ID、
文件名、schema 字段或首次已经给出全称的括号中，不能单独承担科学含义。

本阶段已实现确定性ID cohort分配、affine/受限二次条件均值候选、shrinkage残差协方差和detector-blind
validation选择。阶段 1 分析还会报告条件分箱协方差、残差主模态bootstrap稳定性、二维横向发射度和脉冲适格率。
输入读取器只接受同一`instrument_time_us`、明确OA pre-pulse事件、完整六维状态和逐粒子
`pulse_eligibility`的冻结表；它保留全表，不会静默丢弃不适格粒子。

## 当前资格与重新进入条件

历史同步筛查证明两种源工况曾能被探测器盲地读取并建立稳定条件模型；该阶段结果现在仅为
`DEVELOPMENT_ONLY`，不能作为新 J2/J3 的锁定输入。历史输入拒绝、时序修复、完整母群损失、模型选择
与关闭经过见[冻结状态沿革](../../history/20260911__publication-status-consolidation.md#stage_c1_source_contract)。

新的阶段 1 只有在两份独立母cohort的 source assessment 均显式标为`PROSPECTIVE`时才可为`PASS_CONTINUE`；
任何历史或重放输入都会得到`INCONCLUSIVE_REVISE`。51.2 mm 终端八极杆源工况的新母群应首先完成该重建，再作为新的受约束源加权聚焦预测
主工况输入。无论资格如何，阶段 1 都不说明两源条件模型相同，也不支持受约束源加权聚焦预测、新增控制方向增量价值、任何优化、探测器性能、分辨率、
传输率或三区优越性结论。

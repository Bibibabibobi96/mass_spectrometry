# Paper 1 C1：探测器盲条件源合同

> `STATUS: INCONCLUSIVE_REVISE / INPUT_CONTRACT_BLOCKED`

本阶段已实现确定性ID cohort分配、affine/受限二次条件均值候选、shrinkage残差协方差和detector-blind
validation选择。输入读取器只接受同一`instrument_time_us`、明确OA pre-pulse事件和完整六维状态的冻结表。

## 已审查资产

- S1终端八极杆N=5000状态表记录的是杆内`source`/`rod_exit`事件，且不含OA共同pre-pulse
  `instrument_time_us`字段；它不能被重新标记为OA pre-pulse source。
- S2分段杆handoff表具有canonical六维状态和时钟，但事件是`canonical_handoff`，不是OA提取前检查点；
  用它拟合条件模型会混淆上游出口与分析器脉冲时刻。

## C1结论

`INCONCLUSIVE_REVISE`：实现和输入拒绝门禁已通过，但当前S1/S2没有两个可哈希、共同脉冲时刻的OA
pre-pulse source cohort，因而不能选择模型、冻结协方差、生成locked split或形成J2/J3科学结论。

## 唯一后续动作

在现有source-to-detector集成链为S1和S2各生成一次`pre_pulse_state` checkpoint，至少包含
`particle_id,event,instrument_time_us,x/y/z_mm,vx/vy/vz_m_per_s,pulse_eligibility`，并由run manifest冻结。
不得通过改名现有rod_exit或canonical_handoff表绕过此要求。完成后重跑C1；在C1为`PASS_CONTINUE`前，
阶段2及任何三维优化均不得启动。

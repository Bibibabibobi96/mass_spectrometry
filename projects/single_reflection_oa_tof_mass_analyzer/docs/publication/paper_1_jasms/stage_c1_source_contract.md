# Paper 1 C1：探测器盲条件源合同

> `STATUS: INCONCLUSIVE_REVISE / INPUT_CONTRACT_BLOCKED`

本阶段已实现确定性ID cohort分配、affine/受限二次条件均值候选、shrinkage残差协方差和detector-blind
validation选择。C1分析还会报告条件分箱协方差、残差主模态bootstrap稳定性、二维横向发射度和脉冲适格率。
输入读取器只接受同一`instrument_time_us`、明确OA pre-pulse事件、完整六维状态和逐粒子
`pulse_eligibility`的冻结表；它保留全表，不会静默丢弃不适格粒子。

## 已审查资产

- S1终端八极杆的原始N=5000状态表仍是杆内`source`/`rod_exit`，不能重新标记；但连续单飞run
  `20260822_130100__sim__simion__rf-oatof-single-flight-gap3p2__n850`已产生850行、共同
  `instrument_time_us=47.4513344586562`的`pre_pulse_state`。它可作为`DEVELOPMENT_ONLY`的S1输入，
  不能升级为锁定或N≥1000证据。
- S2分段杆当前的canonical handoff表具有六维状态和时钟，但事件是`canonical_handoff`，不是OA提取前
  检查点。历史COMSOL连接run虽记录了离子分别抵达OA入口的时间，却明确`oa_extraction_pulse=false`且
  `pre_pulse_stage_passed=false`；它不是同一脉冲时刻的快照。两者都不得用于C1模型。

## C1结论

`INCONCLUSIVE_REVISE`：实现和输入拒绝门禁已通过，且S1已有可用开发cohort；但S2尚无可哈希、共同
脉冲时刻的OA pre-pulse cohort。因此不能比较两个源条件、冻结跨源协方差/模态排序、生成锁定split或形成
J2/J3科学结论。

## 唯一后续动作

保持S1只作开发证据；在现有source-to-detector集成链为S2生成一次`pre_pulse_state` checkpoint，至少包含
`particle_id,event,instrument_time_us,x/y/z_mm,vx/vy/vz_m_per_s,pulse_eligibility`，并由run manifest冻结。
不得通过改名现有rod_exit、canonical_handoff或异时OA-entry表绕过此要求。随后按ID哈希冻结四个cohort，
只用development/validation选择模型并检查条件协方差和模态排序稳定性。C1为`PASS_CONTINUE`前，阶段2及
任何三维优化均不得启动。

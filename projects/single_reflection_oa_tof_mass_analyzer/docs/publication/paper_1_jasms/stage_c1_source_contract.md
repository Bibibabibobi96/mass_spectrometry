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
- 已存在的S2终端分段杆SIMION run
  `20260731_210400__sim__simion__hex-segmented-oatof-terminal-h15-n100`也不能直接接入：其**实验计划**声明
  `oatof_shield_terminal`，但实际冻结的`multipole_resolved_design.json`记录
  `downstream_terminal.terminal_profile_id=oatof_shield_entry_gap1mm`；本集成的连续飞行连接合同要求前者。
  这是历史计划与实际资产不一致，不是分段杆固有的下游限制。两种端件的接口几何不同，因而不得通过更改
  selector、文件名或manifest字段把该run升级为连续前端输入。它仍可保留为`DEVELOPMENT_ONLY`的上游分段杆
  传输记录。

## C1结论

`INCONCLUSIVE_REVISE`：实现和输入拒绝门禁已通过，且S1已有可用开发cohort；但S2尚无可哈希、共同
脉冲时刻的OA pre-pulse cohort。因此不能比较两个源条件、冻结跨源协方差/模态排序、生成锁定split或形成
J2/J3科学结论。

## S1开发集检查（不可升级为C1结论）

以固定salt `paper1-c1-v1`对S1共同预脉冲表进行一次纯源侧检查：源表SHA256为
`C06620E8EE4064EA65A9377C935B4867049D0B83B3893C7D17C911084B6480B7`，850/850粒子标为eligible；
development/validation/optimization/locked-test分别为424/173/147/106。仅使用development拟合、
validation选择后，受限二次模型优于仿射模型，五个残差主模态的最小bootstrap方向对齐为0.998637，
按卡方0.975阈值的尾部比例为0。这个结果只说明**S1的开发数据可以被当前C1分析接口读取和稳定诊断**；
它不使用optimization或locked-test，也不能证明跨源稳定性、J2预测力或论文主张。

## 唯一后续动作

保持S1只作开发证据；保持S2的分段杆、RF和轴向电位契约不变，只以`oatof_shield_terminal`端件和当前连接
几何重新编译其上游连续前端，再在同一source-to-detector run中生成一次`pre_pulse_state` checkpoint，至少包含
`particle_id,event,instrument_time_us,x/y/z_mm,vx/vy/vz_m_per_s,pulse_eligibility`，并由run manifest冻结。
不得通过改名现有rod_exit、canonical_handoff、异时OA-entry表或`oatof_shield_entry_gap1mm`端件记录绕过此
要求。随后按ID哈希冻结四个cohort，只用development/validation选择模型并检查条件协方差和模态排序稳定性。
C1为`PASS_CONTINUE`前，阶段2及任何三维优化均不得启动。

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

首个上游重生成输入由
[`20260825__paper1_s2_segmented_standard_terminal_n100.json`](../../../../../common/multipole/campaigns/20260825__paper1_s2_segmented_standard_terminal_n100.json)
预注册：它固定S2的六极分段杆、2→5 eV轴向能量契约、H15数值设置和100粒子母cohort，只将下游端件固定为
当前`oatof_shield_terminal`。该run的唯一角色是产生可连续接入的上游handoff；它本身不支持聚焦、收敛或
论文主张。

该重生成已成功完成，run ID为`20260825_090000__sim__simion__paper1-s2-segmented-standard-terminal__n100`：
冻结resolved design的端件为`oatof_shield_terminal`，100个母粒子中92个产生`handoff/transmitted`，另有8个
上游损失。后续连续前端必须保持100为总分母，并单列这8个损失；92个handoff不是共同命中后挑选出来的峰宽
样本。该结果只修复S2输入的端件可追溯性，仍不构成同一OA脉冲时刻的`pre_pulse_state`，故C1结论保持
`INCONCLUSIVE_REVISE`。

为避免把100粒子功能档误作C1统计证据，同一冻结S2契约已按N=1000母样本重跑，run ID为
`20260825_103000__sim__simion__paper1-s2-segmented-standard-terminal__n1000`。其上游primary arm为
770/1000 transmitted，零轴向对照为572/1000；所有损失仍属于完整母cohort分母。该run只提供可追溯的
N=1000连续前端输入和损失分类，不是共同OA pre-pulse状态，也不改变本阶段的`INCONCLUSIVE_REVISE`结论。

## 2026-08-25 S2连续前端筛查：负结果登记

全母cohort S2筛查`20260825_174500__sim__cross__paper1-s2-segmented-pre-pulse__n1000__r04`的SIMION child
`20260825_174500__sim__simion__rf-oatof-single-flight-gap0__n1000__r04`，在仓库默认资源调度器完成20秒
资源校准后，按4个并行批次各250个粒子完成。四个stdout日志各有250条`status2`，总计1000个粒子；全部在
合同采样窗`45.83769809501819`--`47.66114791320001` µs前发生`Splat`，没有任何
`pre_pulse_time_series_state` TRACE。因此观测状态行数为0，既不能估计条件协方差，也不能从共同命中子集
构造峰宽改善。

本轮首先因运行配置遗漏`pre_pulse_time_series_contract_sha256`而在materialization处失败；修复已作为
`c8e6fee`提交。该实现缺陷不改变原始飞行事实：即使合同哈希被保留，本轮也没有可物化的存活状态。初始
全局状态位于OA全局`x≈-170.11` mm，采样窗前粒子已到达/撞击前端—加速区；这表明当前
`continuous_frontend`契约没有提供在提取前保持该源包的物理边界或适当的提取时序。它不是S2分段杆本身的
性能结论。

### 本轮声明边界

- `claims_supported`：默认调度器可以在实测峰值后以4个独立SIMION进程并行完成N=1000；当前S2
  `continuous_frontend`时间—边界合同在既定采样窗内产生0个OA pre-pulse存活状态。
- `claims_prohibited`：S2源协方差、发射度、尾部或模态排序；S1/S2比较；J2/J3预测；任何分辨率、传输率或
  三区优越性结论。

### 修订门槛

下一次S2 C1运行前，必须冻结并验证一个**可到达的OA提取前源合同**：它要么在来源端保留真实的保持/门控
物理直至预脉冲时刻，要么以有manifest的终端状态在OA入口重新启动，并把新脉冲时刻、状态事件和完整母
cohort损失账本一起冻结。仅把采样窗提前、过滤已撞壁粒子，或将终端handoff重命名为`pre_pulse_state`
都不满足该门槛。通过该门槛并得到S1、S2均有足量共同采样时刻状态之前，C1继续为
`INCONCLUSIVE_REVISE`，阶段2禁止启动。

## 2026-08-25 S2连续前端筛查：完整终端普查（r05）

同一冻结合同的重试 child
`20260825_174500__sim__simion__rf-oatof-single-flight-gap0__n1000__r05`保留了每一个粒子的
`pre_pulse_screening_terminal`记录。默认调度器先完成20秒资源校准、终止校准进程树并重新规划，随后以4个
250粒子SIMION进程完成全部1000个母cohort粒子。原始日志的终端普查为1000个唯一粒子、1000个`Splat`、0个
`window_complete`和0条预脉冲状态行；没有共同命中筛选。

终端时刻为33.009596--45.755457 µs（均值42.531614 µs），均早于首个合同采样点
45.83769809501819 µs；终端坐标集中在全局`x=-59.843111` mm、`z=-61.552189` mm（均值，横向`y`均值
-0.026042 mm）。这把故障位置限定为当前连续前端的前端—加速区接口/时序，而不是分段杆的下游聚焦性能，
也不授权把粒子移到更早采样点来构造源状态。

首次r05包装运行在SIMION完成后因两个**后处理身份解析**缺陷而标记失败：短执行别名清理后未回退到运行目录内
冻结的particle-row map，以及同一cache SHA的大小写表示不一致。提交`12938a0`和`84b5d66`以回归测试修复这两点。
随后以新 recovery run
`20260825_174500__analysis__simion__paper1-s2-pre-pulse-recovery__n1000__r01`只对原始、已冻结的r05
stdout日志和run-local输入执行确定性materialization，得到成功receipt（状态行0、完整1000粒子终端普查）；
没有重新发射粒子、改动场、采样窗或合同。原始r05的`summary.json`已经恢复并再次匹配其失败manifest哈希。
该恢复仅用于冻结负结果，不能把r05升级为任何聚焦或分辨率证据。

### r05声明边界

- `claims_supported`：完整母cohort在当前S2连续前端合同下均在OA预脉冲窗前损失；损失发生的时空范围已被
  逐粒子终端记录限定；默认调度器的校准—终止—重规划策略实际产生4个并行SIMION批次。
- `claims_prohibited`：S2条件源模型或发射度；S1/S2比较；J2/J3；任何峰宽、传输率、分辨率或三区结构优越性。

因此C1维持`INCONCLUSIVE_REVISE / INPUT_CONTRACT_BLOCKED`。下一步不是继续运行同一合同，而是先设计并冻结
可到达的OA提取前保持/门控或manifest-bound restart物理合同，再从完整母cohort重新生成预脉冲状态。

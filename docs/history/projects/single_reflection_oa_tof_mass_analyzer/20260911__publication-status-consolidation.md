# Paper 1 文档状态与已完成过程冻结

DOC_STATUS: ARCHIVED_READ_ONLY

> 只读历史快照；记录整治前叙述，不覆盖当前合同、证据矩阵或 PROJECT。

本次只整理文档；未重新计算、改变门槛、更新原始 run 或提高证据资格。旧文中的“当前”“下一步”按来源时点解释。

## stage_c1_source_contract

来源：`docs/publication/paper_1_jasms/stage_c1_source_contract.md`，整治前版本 `45a6741550aae5cbb009615896d16ef6d20618a2`。

## Paper 1 阶段 1：探测器盲源合同

> `STATUS: DEVELOPMENT_ONLY / PROSPECTIVE_C1_REBUILD_REQUIRED`

### 术语（本页及后续报告的唯一含义）

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

### 已审查资产

- 终端八极杆源工况的原始N=5000状态表仍是杆内`source`/`rod_exit`，不能重新标记；但连续单飞run
  `20260822_130100__sim__simion__rf-oatof-single-flight-gap3p2__n850`已产生850行、共同
  `instrument_time_us=47.4513344586562`的`pre_pulse_state`。它可作为`DEVELOPMENT_ONLY`的终端八极杆源工况输入，
  不能升级为锁定或N≥1000证据。
- 分段六极杆源工况当前的canonical handoff表具有六维状态和时钟，但事件是`canonical_handoff`，不是OA提取前
  检查点。历史COMSOL连接run虽记录了离子分别抵达OA入口的时间，却明确`oa_extraction_pulse=false`且
  `pre_pulse_stage_passed=false`；它不是同一脉冲时刻的快照。两者都不得用于阶段 1 模型。
- 已存在的分段六极杆源工况终端分段杆SIMION run
  `20260731_210400__sim__simion__hex-segmented-oatof-terminal-h15-n100`也不能直接接入：其**实验计划**声明
  `oatof_shield_terminal`，但实际冻结的`multipole_resolved_design.json`记录
  `downstream_terminal.terminal_profile_id=oatof_shield_entry_gap1mm`；本集成的连续飞行连接合同要求前者。
  这是历史计划与实际资产不一致，不是分段杆固有的下游限制。两种端件的接口几何不同，因而不得通过更改
  selector、文件名或manifest字段把该run升级为连续前端输入。它仍可保留为`DEVELOPMENT_ONLY`的上游分段杆
  传输记录。

### 阶段 1 结论

`INCONCLUSIVE_REVISE`：实现和输入拒绝门禁已通过，且终端八极杆源工况已有可用开发cohort；但分段六极杆源工况尚无可哈希、共同
脉冲时刻的OA pre-pulse cohort。因此不能比较两个源条件、冻结跨源协方差/模态排序、生成锁定split或形成
受约束源加权聚焦预测和新增控制方向增量价值的科学结论。

### 终端八极杆源工况开发集检查（不可升级为阶段 1 结论）

以固定salt `paper1-c1-v1`对终端八极杆源工况共同预脉冲表进行一次纯源侧检查：源表SHA256为
`C06620E8EE4064EA65A9377C935B4867049D0B83B3893C7D17C911084B6480B7`，850/850粒子标为eligible；
development/validation/optimization/locked-test分别为424/173/147/106。仅使用development拟合、
validation选择后，受限二次模型优于仿射模型，五个残差主模态的最小bootstrap方向对齐为0.998637，
按卡方0.975阈值的尾部比例为0。这个结果只说明**终端八极杆源工况的开发数据可以被当前阶段 1 分析接口读取和稳定诊断**；
它不使用optimization或locked-test，也不能证明跨源稳定性、受约束源加权聚焦预测力或论文主张。

### 唯一后续动作

保持终端八极杆源工况只作开发证据；保持分段六极杆源工况的分段杆、RF和轴向电位契约不变，只以`oatof_shield_terminal`端件和当前连接
几何重新编译其上游连续前端，再在同一source-to-detector run中生成一次`pre_pulse_state` checkpoint，至少包含
`particle_id,event,instrument_time_us,x/y/z_mm,vx/vy/vz_m_per_s,pulse_eligibility`，并由run manifest冻结。
不得通过改名现有rod_exit、canonical_handoff、异时OA-entry表或`oatof_shield_entry_gap1mm`端件记录绕过此
要求。随后按ID哈希冻结四个cohort，只用development/validation选择模型并检查条件协方差和模态排序稳定性。
阶段 1为`PASS_CONTINUE`前，阶段 2及任何三维优化均不得启动。

首个上游重生成输入由
[`20260825__paper1_s2_segmented_standard_terminal_n100.json`](../../../../common/multipole/campaigns/20260825__paper1_s2_segmented_standard_terminal_n100.json)
预注册：它固定分段六极杆源工况的六极分段杆、2→5 eV轴向能量契约、H15数值设置和100粒子母cohort，只将下游端件固定为
当前`oatof_shield_terminal`。该run的唯一角色是产生可连续接入的上游handoff；它本身不支持聚焦、收敛或
论文主张。

该重生成已成功完成，run ID为`20260825_090000__sim__simion__paper1-s2-segmented-standard-terminal__n100`：
冻结resolved design的端件为`oatof_shield_terminal`，100个母粒子中92个产生`handoff/transmitted`，另有8个
上游损失。后续连续前端必须保持100为总分母，并单列这8个损失；92个handoff不是共同命中后挑选出来的峰宽
样本。该结果只修复分段六极杆源工况输入的端件可追溯性，仍不构成同一OA脉冲时刻的`pre_pulse_state`，故阶段 1 结论保持
`INCONCLUSIVE_REVISE`。

为避免把100粒子功能档误作阶段 1 统计证据，同一冻结分段六极杆源工况契约已按N=1000母样本重跑，run ID为
`20260825_103000__sim__simion__paper1-s2-segmented-standard-terminal__n1000`。其上游primary arm为
770/1000 transmitted，零轴向对照为572/1000；所有损失仍属于完整母cohort分母。该run只提供可追溯的
N=1000连续前端输入和损失分类，不是共同OA pre-pulse状态，也不改变本阶段的`INCONCLUSIVE_REVISE`结论。

### 2026-08-25 分段六极杆源工况连续前端筛查：负结果登记

全母cohort的分段六极杆源工况筛查（run ID：`20260825_174500__sim__cross__paper1-s2-segmented-pre-pulse__n1000__r04`）的SIMION child
`20260825_174500__sim__simion__rf-oatof-single-flight-gap0__n1000__r04`，在仓库默认资源调度器完成20秒
资源校准后，按4个并行批次各250个粒子完成。四个stdout日志各有250条`status2`，总计1000个粒子；全部在
合同采样窗`45.83769809501819`--`47.66114791320001` µs前发生`Splat`，没有任何
`pre_pulse_time_series_state` TRACE。因此观测状态行数为0，既不能估计条件协方差，也不能从共同命中子集
构造峰宽改善。

本轮首先因运行配置遗漏`pre_pulse_time_series_contract_sha256`而在materialization处失败；修复已作为
`c8e6fee`提交。该实现缺陷不改变原始飞行事实：即使合同哈希被保留，本轮也没有可物化的存活状态。初始
全局状态位于OA全局`x≈-170.11` mm，采样窗前粒子已到达/撞击前端—加速区；这表明当前
`continuous_frontend`契约没有提供在提取前保持该源包的物理边界或适当的提取时序。它不是分段六极杆源工况本身的
源工况性能结论。

#### 本轮声明边界

- `claims_supported`：默认调度器可以在实测峰值后以4个独立SIMION进程并行完成N=1000；当前分段六极杆源工况
  `continuous_frontend`时间—边界合同在既定采样窗内产生0个OA pre-pulse存活状态。
- `claims_prohibited`：分段六极杆源工况的源协方差、发射度、尾部或模态排序；两种源工况比较；受约束源加权聚焦预测或新增控制方向增量价值；任何分辨率、传输率或
  三区优越性结论。

#### 修订门槛

下一次分段六极杆源工况的阶段 1 运行前，必须冻结并验证一个**可到达的OA提取前源合同**：它要么在来源端保留真实的保持/门控
物理直至预脉冲时刻，要么以有manifest的终端状态在OA入口重新启动，并把新脉冲时刻、状态事件和完整母
cohort损失账本一起冻结。仅把采样窗提前、过滤已撞壁粒子，或将终端handoff重命名为`pre_pulse_state`
都不满足该门槛。通过该门槛并得到两种源工况均有足量共同采样时刻状态之前，阶段 1 继续为
`INCONCLUSIVE_REVISE`，阶段2禁止启动。

### 2026-08-25 分段六极杆源工况连续前端筛查：完整终端普查（r05）

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

#### r05声明边界

- `claims_supported`：完整母cohort在当前分段六极杆源工况连续前端合同下均在OA预脉冲窗前损失；损失发生的时空范围已被
  逐粒子终端记录限定；默认调度器的校准—终止—重规划策略实际产生4个并行SIMION批次。
- `claims_prohibited`：分段六极杆源工况条件源模型或发射度；两种源工况比较；受约束源加权聚焦预测或新增控制方向增量价值；任何峰宽、传输率、分辨率或三区结构优越性。

因此阶段 1 维持`INCONCLUSIVE_REVISE / INPUT_CONTRACT_BLOCKED`。下一步不是继续运行同一合同，而是先设计并冻结
可到达的OA提取前保持/门控或manifest-bound restart物理合同，再从完整母cohort重新生成预脉冲状态。

### 2026-08-25 分段六极杆源工况 terminal-handoff 时相负结果

新的分段六极杆源工况连续交接筛查 parent run
`20260825_223400__sim__cross__paper1-s2-segmented-handoff-pre-pulse__n1000`保留母cohort 1000：其中914个
`handoff/transmitted`进入OA single-flight child
`20260825_223400__sim__simion__rf-oatof-single-flight-gap0__n914`，86个上游损失仍计入完整分母。默认调度器在短资源校准后将914个物理交接粒子规划为4个正式SIMION批次；child本身成功完成，但321个预脉冲采样时刻记录到0行状态，914个粒子全部`Splat`。

这一次的终端位置揭示了先前仅凭“到不了采样窗”无法区分的根因。冻结的handoff表中离子以
`v_x=3052.21`--`3133.64 m/s`沿OA全局`x`正向传播；冻结OA accelerator再沿全局`z`正交提取，这正是OA几何本身，并非错误。由handoff状态作的弹道核对显示束团中心在`39.557698 µs`附近穿过提取中心，而914条终端记录中788条在`x=-54 mm`附近撞击，弹道到该壁的中位时刻约`44.384479 µs`。本轮screening却围绕陈旧的`46.746789 µs` anchor采样，因此所有样本均发生在束团离开后。故当前负结果是**预脉冲采样时相没有绑定到已解析的束团中心时刻**，不是分段六极杆、正交x→z结构、相空间或峰宽结论。

对应的冻结阶段证据输入为[`c1_s2_handoff_axis_topology_negative.json`](../publication/paper_1_jasms/stage_evidence/c1_s2_handoff_axis_topology_negative.json)。

#### 更新后的唯一后续动作

保持524 Da Formal OA资产不变。将pre-pulse RF时间栅格的中心强制绑定到本次运行的`resolved_single_flight_pulse_schedule.json`，即由冻结handoff表和目标提取中心确定的时刻；campaign只继续描述窗口宽度、RF步长和禁止输出。随后以完整母cohort重新生成分段六极杆源工况的预脉冲状态。不得以任意手动提前采样、过滤撞壁粒子或重命名handoff事件代替这个可追溯的时相绑定。在此之前阶段 1 继续为`INCONCLUSIVE_REVISE`，阶段 2 禁止启动。

### 2026-08-25 分段六极杆源工况 terminal-handoff：同步筛查与单源阶段 1 诊断

同步screen parent `20260825_223900__sim__cross__paper1-s2-segmented-handoff-pre-pulse__n1000`及其SIMION child
`20260825_223900__sim__simion__rf-oatof-single-flight-gap0__n914`成功闭合。筛查栅格仅由冻结的
`resolved_single_flight_pulse_schedule.json`导出；detector-blind selector在321个样本中选择第97个，即
`39.19406205683414 µs`，相对解析seed为`-0.363636 µs`。它不读取探测器、到达时间、峰宽或候选控制量。

完整母cohort仍为1000，914个终端handoff进入OA；所选样本中828个保持存活、827个pulse-eligible，故172个
未观测/损失粒子始终保留在母分母（86个上游损失加86个OA预脉冲损失）。阶段 1 读取器现显式区分母cohort与
实际筛查子cohort，拒绝两者身份不闭合；不会把914当成1000或把828当成共同命中样本。分段六极杆源工况单源诊断以固定
`paper1-c1-v1` ID哈希划分为development/validation/optimization/locked-test = 418/171/138/101；只用前两者
选择模型。仿射条件模型被选中，尾部比例为0.0023923，六个残差主模态的bootstrap 95%下界为
0.99909--1.0。这只证明分段六极杆源工况输入已可由阶段 1 接口稳定、探测器盲地读取，不是跨源可重复性、受约束源加权聚焦预测、新增控制方向增量价值或性能结论。

对应五件套阶段证据为`paper1_stage_evidence/C1/20260825_223900__s2_handoff_synchronised_source`（路径中的`C1`和`s2`是既有机器目录/运行标识）。这一记录保留
当时的单源`INCONCLUSIVE_REVISE`状态；后续终端八极杆源工况同步证据与它共同构成当前阶段 1 关闭证据。

### 2026-08-25 终端八极杆源工况同步筛查与阶段 1 关闭

终端八极杆源工况已用新成功的上游r03源run重新生成同步真实PA筛查。其900个`handoff/transmitted`粒子保持完整1000粒子母分母；
由冻结handoff的弹道质心解析脉冲种子`45.56495820366112 µs`，并以detector-blind选择器选中第148个采样点
`45.49109456729749 µs`。该点有875个预脉冲状态，125个未观测/损失粒子仍在母分母；没有探测器、到达时间、
峰宽或控制量参与选择。终端八极杆源工况选择受限二次条件模型，分段六极杆源工况选择仿射条件模型；这表明源条件不同，不能被表述为模型相等。

以同一salt `paper1-c1-v1`，终端八极杆源工况的development/validation/optimization/locked-test为429/178/156/112，
分段六极杆源工况为418/171/138/101。两源均只以development/validation选择模型，所有残差主模态bootstrap 95%方向对齐下界
均大于0（实际最小值分别为0.9991307和0.9990477）。两份完整协方差分箱、模型、发射度、尾部、来源SHA和
母cohort损失账本由最终五件套阶段证据冻结于
`paper1_stage_evidence/C1/20260825_220400__s1_s2_synchronised_source`（路径中的缩写为既有机器标识）。

#### 历史阶段 1 结论与当前资格

上述`PASS_CONTINUE`是历史阶段 1 的开发诊断结论：两种不同RF源工况曾提供可哈希、同步、detector-blind的
OA预脉冲状态，且各自条件残差模型和主模态在隔离cohort下稳定可识别。根据当前 Paper 1 证据治理，它们只可标记
为`DEVELOPMENT_ONLY`，不可作为新的受约束源加权聚焦预测或新增控制方向增量价值的锁定输入，也不自动授权三维工作。

新的阶段 1 只有在两份独立母cohort的 source assessment 均显式标为`PROSPECTIVE`时才可为`PASS_CONTINUE`；
任何历史或重放输入都会得到`INCONCLUSIVE_REVISE`。51.2 mm 终端八极杆源工况的新母群应首先完成该重建，再作为新的受约束源加权聚焦预测
主工况输入。无论资格如何，阶段 1 都不说明两源条件模型相同，也不支持受约束源加权聚焦预测、新增控制方向增量价值、任何优化、探测器性能、分辨率、
传输率或三区优越性结论。

## stage_c3_j3_real_field_contract

来源：`docs/publication/paper_1_jasms/stage_c3_j3_real_field_contract.md`，整治前版本 `45a6741550aae5cbb009615896d16ef6d20618a2`。

### 已完成的 N=1 功能门槛

2026-08-26，S1的五个预注册物理点`-2h,-h,0,+h,+2h`均以
`multipole_handoff_ballistic_centroid_v1`解析的固定脉冲时刻`45.56495820366112 µs`完成真实PA单飞。
每个点都保留1000离子母分母、明确的上游粒子ID 1、独立PA身份、完整事件链及成功的父/子manifest；
五点均为`1 → grid1 → intermediate2 → accelerator exit → reflectron → detector`，检测器`1/1`。
这只关闭N=1贯通门槛：它既不比较五点TOF，也不支持导数、峰宽、传输或J3主张。C3仍须完成同一五点的
N=100中心差分、事件拓扑稳定性和独立轴场积分器比较后才能形成阶段结论。

N=100的正式campaign是[`paper1_c3_j3_s1_fixed_pulse_derivative_n100.json`](../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_c3_j3_s1_fixed_pulse_derivative_n100.json)。其执行cohort由`first_n_transmitted_terminal_handoffs_in_source_particle_id_order`唯一指定，ID序列哈希已冻结；五点共享现有`multipole_handoff_ballistic_centroid_v1`脉冲计划，不含时间窗扫描。

首次`−2h` N=100运行（`20260826_081000__sim__cross__paper1-c3-j3-s1-fixed-pulse-derivative-m2__n100`）的原始三批飞行与checkpoint已完成，但在空间图后处理时被错误要求存在上游source-region diagnostic 而失败。terminal-handoff continuation 的合法起点没有该checkpoint，因此这不是场、粒子事件或物理`FAIL_STOP`；原run按失败证据保留。修复后的重跑必须使用新的run ID，且仍使用同一五点、cohort、固定pulse与母cohort分母。

五点N=100的当前闭合状态是：`−2h`以`20260826_082000__sim__simion__rf-oatof-single-flight-gap0__n100__r02`成功，`−h`的原始N=100行因一个已损坏的前端PA cache generation而在飞行前失败，保留为非物理失败证据；`−h`以`20260826_083000__sim__simion__rf-oatof-single-flight-gap0__n100__r02`重建并重新校验缓存后成功，`0,+h,+2h`三个原登记行也均成功。五点均为100个固定source ID启动、98个在固定pulse时刻合格且98个完整到达探测器，所有登记的下游事件均为98。

独立轴场积分器只能重算从`pre_pulse_state`到`local_accelerator_exit`的传播，不能与完整 detector TOF 混合比较。因此配对分析器也按同一段计算：`±h`与`±2h`中心差分均值分别为`1.5042704087e-4`与`1.5042704087e-4 ns/h`，步长平台相对误差`1.1568e-11`，98个共同粒子的事件拓扑不变。该结果只证明真实PA局部差分和事件拓扑稳定；独立导出轴场积分器尚未提供同段参考导数，因此当前机器结论仍为`INCONCLUSIVE_REVISE`，不得进入C4。

## connector_gap_paired_source_contract

来源：`docs/publication/paper_1_jasms/connector_gap_paired_source_contract.md`，整治前版本 `45a6741550aae5cbb009615896d16ef6d20618a2`。

### 弹道种子失配与真实场确认

下列固定脉冲运行保留以审计“把弹道种子错误地当作最终脉冲”这一失配；它们是
`DEVELOPMENT_ONLY`，不进入配对残差分析，也不能排除任何 gap。当前固定种子配置为：

- [`paper1_s1_connector_gap0_fixed_pulse_n1000.json`](../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_s1_connector_gap0_fixed_pulse_n1000.json)
- [`paper1_s1_connector_gap51p2_fixed_pulse_n1000.json`](../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_s1_connector_gap51p2_fixed_pulse_n1000.json)

两者均已完成 direct fixed-pulse 运行并通过只分析恢复的 manifest 复核，但不能作为最终脉冲的运行
身份。最终脉冲只接受 manifest-bound、真实场 detector-blind candidate-confirmation receipt。

### 2026-08-26 直接 integration 脉冲结果

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

#### 2026-08-25—26 真实场脉冲确认

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

## stage_c1_connector_gap_triplet_contract

来源：`docs/publication/paper_1_jasms/stage_c1_connector_gap_triplet_contract.md`，整治前版本 `45a6741550aae5cbb009615896d16ef6d20618a2`。

### 当前状态

- 0 mm（`...gap0...n5000__r09`）与 51.2 mm（`...gap51p2...n5000__r03`）已各自完成
  N=5000 的 `continuous_frontend` detector-blind time-series 运行；102.4 mm
  （`...gap102p4...n5000__r02`）也已完成。三臂均通过统一 `PRE_PULSE_EQUIVALENT_TIME_SERIES`、resolved epoch
  和 frozen-identity 核验。
- C1-v1 五件套已发布为 `INCONCLUSIVE_REVISE`，唯一失败原因是 51.2/102.4 mm 的 common locked-test ID 为
  17，低于 32；其余输入与完整 5000-ID 分母均保留为负结果证据。
- 下一步：按本节 C1-v2 的固定盲分区重新发布**独立**五件套。历史 23 臂 gap×field 结果始终为
  `DEVELOPMENT_ONLY`，不进入统计输入；用户现有的 0 mm、N=1000 terminal-handoff 文件保持不改。

## evidence_matrix

整治前矩阵，含已过时的 C1/C3 资格；当前状态已由阶段合同裁决，不得沿用本节的旧 PASS 或待办。

## Paper 1：JASMS当前证据矩阵

> `STATUS: LIVE_INDEX / NO_RESULT_COPY`
>
> `LAST_REVIEW: 2026-08-27`

本表只索引当前证据和缺口，不复制run数字、manifest清单或history叙事。`SUPPORTED`表示证据满足该
claim的完整投稿要求；目前没有主claim达到`SUPPORTED`。

### 1. 基础能力

| 能力 | 当前证据 | 状态 | 投稿用途与限制 |
|---|---|---|---|
| N=2双区精确时间和焦面 | [独立加速器理论](../../../orthogonal_accelerator/docs/theory/oaaccelerator_time_focus.md)及测试 | `PROJECT_ORACLE` | 经典基础，不是创新 |
| affine `z-v_z`耦合 | [局部加速器理论](../../../orthogonal_accelerator/docs/theory/affine_phase_space_time_focus.md)、[下游连接](../theory/z_vz_linear_phase_space_coupling.md)及测试 | `PROJECT_ORACLE` | 已知相关聚焦特例 |
| 二级reflectron精确时间 | [`dual_stage_reflectron.md`](../theory/dual_stage_reflectron.md)及测试 | `PROJECT_ORACLE` | 经典基础，不是创新 |
| 一维整机耦合 | [`oatof_oaaccelerator_coupling.md`](../theory/oatof_oaaccelerator_coupling.md)及测试 | `PROJECT_ORACLE` | 参考面和低阶闭合基础 |
| N=3、`A1–A4`、`Γ3` | [局部三区公式](../../../orthogonal_accelerator/docs/theory/three_zone_accelerator_ideal_theory.md)、[整机联合理论](../theory/three_zone_accelerator_ideal_theory.md)及测试 | `PROJECT_ORACLE / PROVISIONAL` | 三区不是创新；100 Th理论身份 |
| 524 Da N=1000双求解器Formal | [`PROJECT.md`](../PROJECT.md)与机器合同 | `FORMAL_REFERENCE` | 理想项目基线；不是RF observed source的Paper 1闭环 |
| C0理论与声明闭合 | [`stage_c0_theory_closure.md`](../publication/paper_1_jasms/stage_c0_theory_closure.md) | `PASS_CONTINUE / THEORY_ONLY` | 不含source cohort、直接粒子或性能证据 |

### 2. 主claim证据

| Claim | 已有直接证据 | 当前等级 | 主要缺口 |
|---|---|---|---|
| J1：切向closure与条件厚度分离 | [`20260817 observed-source归因`](20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md) | `PRIOR_ART_OVERLAP / DIAGNOSTIC_FRAMEWORK` | N=100、单设计、post-hoc移植；且非线性相关与finite spread已有先例，不能独立承担新颖性 |
| J2：focusability projector预测残差floor | `paper1_stage_evidence/C2/20260825_144300__total_variance_j2_j3_revision/stage_conclusion.md`、51.2 mm历史功能对照、[`当前J2-0复现`](../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/paper1_stage_evidence/J2_0/20260826_214700__s1_gap51p2_current_condition_reproduction/stage_conclusion.md)及`C1_CONNECTOR_GAP_TRIPLET` N=5000 source-only evidence | `AXIAL_TOTAL_OBJECTIVE_INCONCLUSIVE_REVISE / CURRENT_FUNCTIONAL_REPRODUCTION_PASS / GAP_HYPOTHESIS_SUPPORTED` | 当前J2-0确认了低残差51.2 mm工况下按仿射`z-vz`关系重算工作点的功能性改善，且未改变完整母群检测数；但它不是“source-weighted vs unweighted projector”比较，不能被升级为J2成功。下一步按[`J2真实场公平pilot合同`](../publication/paper_1_jasms/j2_real_3d_pilot_contract.md)以同一候选池、预算和锁定角色检验预测力；完整6D、真实场、峰形和传输检验仍缺 |
| J3：第三区的独立高阶控制方向及其有限束宽价值 | `runs/20260817_122700__analysis__python__three-zone-t5/stage_receipt.json`显示：在两区已闭合`D1/D2`后，三区保留的`Γ3`方向可把冻结1D、2.2 mm轴向束宽的`σ_t`从0.816 ns降至0.182 ns；`paper1_stage_evidence/C2_J3/20260826_015500__ideal_axial_direction_v2/stage_conclusion.md`以当前哈希冻结的理论合同，在两种冻结源条件下通过导数、步长、零空间及 locked improve/zero/worsen 排序门槛；C3真实PA的五点N=1路径均已贯通 | `IDEAL_AXIAL_PASS_CONTINUE / C3_N1_FUNCTIONAL_ONLY / HIGH_OBVIOUSNESS_RISK` | N=1不支持导数或性能。仍须完成N=100五点中心差分、事件拓扑稳定性、独立轴场积分器、完整6D传输/峰形、多质量与公平结构比较 |
| J4：source-weighted优于未加权closure | solver-free two/three比较与`Γ3` | `PRIOR_ART_OVERLAP / LOCAL_SCALAR_ONLY` | 相同预算A–D公平重优化和blind test全部缺；只能作为J2/J3次级结果 |
| J5：诊断决定改分析器还是改源 | 历史结论提出下一阶段问题 | `PRIOR_ART_OVERLAP / HYPOTHESIS_ONLY` | 至少两源工况的事前决策和独立验证缺失；一般source/analyzer权衡已知 |

### 3. 先行工作门禁

| 门禁 | 当前证据 | 状态 | 仍需关闭 |
|---|---|---|---|
| 定向论文与引用链预审 | [`2026-08-25审计`](../publication/prior_art_search_audit_20260825.md)及[`逐式claim chart`](../publication/prior_art_equation_claim_chart_20260825.md) | `FOUR_LOCAL_MAIN_TEXTS_REVIEWED` | 2015/2026 SI、其他closest-work全文、扩展引用链与独立专家复核 |
| 专利族预审 | 同上，覆盖SVCF、RF guide/conditioner、OA guide mode、spatial-temporal correlation和upstream conditioner代表族 | `PRELIMINARY_LANDSCAPE_COMPLETE` | 具体conditioner逐权利要求、continuation/法域状态和专业FTO |
| J2/J3同构先例 | 定向检索及四份本地主文本均未发现完整同构组合；Yefchak 1989进一步加重J3明显性风险 | `NO_DIRECT_HIT / NOT_CLEARANCE` | 剩余正文/SI、引文扩展与领域专家独立复核 |

### 4. 当前真实源相关证据

| 证据 | 已证明 | 未证明 |
|---|---|---|
| [`三区完成结果快照`](20260823__three-zone-completed-results-snapshot.md) | 一维三区理论、N=100真实PA和固定设计源敏感性已完成 | N≥1000、条件模型、可补偿性、COMSOL/CAD和工程资格 |
| [`observed横向敏感性`](20260817__three-zone-observed-transverse-sensitivity.md) | 同一N=100 ID下横向恢复是较小但可测增量 | 横向普遍不重要、连续真实handoff或统计稳定性 |
| [`observed z-vz归因`](20260817__three-zone-zvz-nonlinearity-fixed-energy-source-sensitivity.md) | 固定设计中observed-affine残差主导首尾顺序退化 | 该残差不可补偿、是光滑高阶曲线或可推广到其他工况 |
| RF→OA integration observed authority | S1的N=1000母cohort/900 handoff同步真实PA筛查提供875个所选时刻状态；S2的N=1000母cohort/914 handoff筛查提供828个所选时刻状态。两源均由冻结脉冲计划和detector-blind selector选择，且母分母与损失账本保留 | [`C1 source contract`](../publication/paper_1_jasms/stage_c1_source_contract.md)为`PASS_CONTINUE`：只证明两源各自可稳定识别；它不比较模型相等性，也不升级为J2/J3或性能结论 |
| S1 connector-gap pre-pulse residual | `C1_CONNECTOR_GAP_TRIPLET` N=5000、real-field pulse-equivalent source-only stage保留完整母cohort分母；0→51.2 mm和51.2→102.4 mm分别使用137和34个共同locked pre-pulse ID，不能把两对残差拼成同一三点群体。各对RMS与来源见[机制证据及勘误](../publication/paper_1_jasms/connector_gap_working_point_mechanism_20260827.md) | 这是残差—传输权衡的探测器盲证据，不是J2、峰宽或分辨率结论。51.2 mm须独立重建C1 source receipt后作为首个J2主工况；102.4 mm仅为低传输边界对照，当前样本不足以单独承担锁定J2结论 |
| S1 51.2 mm历史`z-vz`理论工作点直接对照 | 同一77个pre-pulse restart粒子、同一全理想三区场与77/77检出：继承工作点 [`20260821_110000`](../../../../../artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260821_110000__sim__simion__rf-oatof-single-flight-gap51p2__n77/summary.json) 的直接FWHM为2.1105 ns、R=7423、2 modes；按`source_zvz_three_zone_theory_working_point_v1`重算的 [`20260821_110200`](../../../../../artifacts/projects/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/runs/20260821_110200__sim__simion__rf-oatof-single-flight-gap51p2__n77/summary.json) 为0.6731 ns、R=23271、1 mode | `HISTORICAL_FUNCTIONAL_SCREEN_ONLY`：FWHM降低68.1%、R提高3.14×，支持“`z-vz`关系调节可在低残差gap工况恢复有效聚焦”的既有功能性事实；原campaign未运行成对统计，且N=77、历史重启源/全理想场、无锁定角色，不能独自作为J2投稿证据 |
| S1 51.2 mm当前`z-vz`理论工作点复现 | [`J2-0 stage package`](../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/paper1_stage_evidence/J2_0/20260826_214700__s1_gap51p2_current_condition_reproduction/stage_report.json)绑定同一393个pre-pulse ID、106个pulse-eligible peak ID和两臂相同的211 detector crossings；继承工作点的直接FWHM/R为2.341 ns/6692，`source_zvz_three_zone_theory_working_point_v1`为0.711 ns/22023 | `CURRENT_FUNCTIONAL_REPRODUCTION / DEVELOPMENT_ONLY`：通过J2-0实施等价性门槛，排除了“当前restart、时钟或字段实现已丢失该已知机制”的解释；它不是J2预测器对比、锁定测试、跨源或多质量证据 |
| S1三间隙真实场工作点机制实验 | [脉冲相对时钟修正run](../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20260827_123019__analysis__python__connector-gap-pulse-clock-correction/run_manifest.json)重新派生既有六臂，不新增SIMION；固定同一N=5000母cohort、每间隙pulse与源状态，各臂使用全部检测命中且同gap命中ID相同。新R、峰宽和有符号成对收益区间见[机制报告](../publication/paper_1_jasms/connector_gap_working_point_mechanism_20260827.md)。旧`20260827_112500`报告的absolute-clock R和无符号差异区间被替代，原始轨迹和FWHM不变 | `MECHANISM_EXPERIMENT_PASS / MODEL_SPECIFIC`：支持针对当前源重调工作点的收益及其与源条件变化的关联；不隔离所有gap依赖变量，不给出普遍残差阈值。继承点是旧理想源工作点，调压复用已有算法，不是同预算经典方法重优化对照。51.2 mm为主证据，102.4 mm为低传输边界；不支持算法首创、source-weighted优越性或多源/多质量推广 |
| C2 ideal axial total-objective revision | 两源的解析/有限差分`g`、`G`步长平台、两区零控制、三区改善/零效/恶化的锁定排序均闭合；目标同时含条件均值方差和条件厚度 | 对旧小-gap源条件的J2：`INCONCLUSIVE_REVISE`。它禁止把旧结果升级为J2成功，却不排除经独立C1确认的低残差gap工况；后者必须作为新的、预注册的真实场pilot。对预注册拆分的J3：`PASS_CONTINUE / IDEAL_AXIAL_ONLY`，只允许冻结一份C3_J3真实场局部导数合同；不允许借此恢复J2、FWHM、传输或普适结构优越性主张 |

### 5. 证据资格结论

当前仓库足以支持以下写作动作：

- 按收窄后的J2/J3中心问题写核心全文骨架、Introduction和claim-safe相关工作；
- 写Theory和Methods草案，但结果数字、摘要结论和新颖性措辞必须留空；
- 设计并预注册Paper 1 campaign；
- 把现有N=100结果作为hypothesis-generating历史证据。

当前仓库不足以支持：

- JASMS摘要中的定量focusability claim；
- 条件残差构成架构极限的结论；
- 三区对真实源优于二区的投稿结论；
- source-weighted设计优越性；
- “必须改源而不能改分析器”的普遍判断；
- 任何`first/novel`措辞。

### 6. 更新规则

新证据只有在以下字段齐全时加入本表：

```text
claim_id
source cohort and ordered-ID hash
field/geometry/numerics identity
particle count and mass/source condition
metric and denominator definition
run/history/manifest reference
independent validation
evidence level
known limitation
```

结果数字留在summary/history，本文只更新资格和引用。

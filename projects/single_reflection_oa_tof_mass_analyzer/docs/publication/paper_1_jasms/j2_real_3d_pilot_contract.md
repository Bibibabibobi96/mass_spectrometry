# Paper 1 J2：公平真实场 pilot 合同

> `STATUS: J2-0_PASS_CONTINUE / FAIR_J2_PILOT_DESIGN_FROZEN / SOLVER_NOT_AUTHORIZED_BY_THIS_DOCUMENT`

## 要回答的问题

J2 的可证伪问题不是“能否找到一个 source-weighted 点优于某个旧点”，而是：在**不读取锁定探测器结果**的前提下，
source-whitened、受约束预测器能否比未加权预测器更可靠地从同一真实 PA 候选池中选择低到达时间展宽的控制点。

这是一个新的、范围受限的 `J2_REAL_3D_PILOT`。它不覆盖历史 C2 的
`INCONCLUSIVE_REVISE`，也不把 J3 的局部控制方向改写为 J2 证据。

在进入该公平选择器比较前，必须先完成 `J2-0`：在当前 51.2 mm、同一冻结源状态下，复现已知的
“继承电压 vs 由该源的仿射 `z-vz` 关系推导三区工作点”的直接对照。该门槛不是要重新判断该机制是否
存在，而是确认当前源、时钟、字段和实现仍能重现它。历史配对已在同一 77 个 restart 粒子、同一全理想
三区场中给出直接 FWHM `2.1105 -> 0.6731 ns`、`R=7423 -> 23271` 和 `2 -> 1` modes；它是
`HISTORICAL_FUNCTIONAL_SCREEN_ONLY`，不能替代当前的锁定证据。

`J2-0` 的唯一物理变化必须是工作点：两臂共享母群体、所选 ID、pulse、几何、场 profile、数值身份和
检测定义；一臂消费继承电压，另一臂消费
`source_zvz_three_zone_theory_working_point_v1`。当前 N=5000 C1 time-series 输出需先被规范材料化为
manifest-bound restart（补全 canonical state、质量/电荷、ID 映射和完整 5000 母群损失账本），不得把
`pulse_disabled` CSV 直接伪装成 restart。J2-0 仅为 `DEVELOPMENT_ONLY`；通过后才授权下面的公平 J2
候选池，失败则首先排查当前源材料化/时钟/字段等价性，而不是反向否定历史机制。

### J2-0 当前复现结果

该前置门槛现已通过。冻结的 S1、51.2 mm、100 Th 工况以相同的393个 pre-pulse ID、同一脉冲时刻和
同一数值身份完成两臂真实场飞行；两臂各有106个 pulse-eligible peak样本、211个完整母cohort detector
crossings。将工作点从继承值替换为该源的 `source_zvz_three_zone_theory_working_point_v1` 后，直接 FWHM
由2.341 ns变为0.711 ns，质量分辨率由6692变为22023；完整的、hash-bound结果和禁止声明见
[`J2-0 stage package`](../../../../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/paper1_stage_evidence/J2_0/20260826_214700__s1_gap51p2_current_condition_reproduction/stage_conclusion.md)。
这只确认当前材料化、时钟、字段和分析实现没有丢失已知机制；它**不**比较 source-whitened J2与未加权
预测器，也不构成锁定测试或投稿证据。

## 冻结比较规则

- 首轮主工况是连续杆 S1 的 **51.2 mm connector gap**。其 C1 源模型只读对应 OA pre-pulse state，
  并以独立的 ID 哈希登记 development / validation / optimization / locked-test；不得复用小 gap 的
  条件协方差。0 mm 只作为高残差的负对照，102.4 mm 只作为低残差、低传输边界对照；两者均须在新 run
  中各自重建 C1 source receipt 后才可进入 J2 比较。S2 分段杆留作该首轮通过后的独立源迁移。
- 第一轮固定**三区**和同一个基准 Candidate。两区在已保持 D1/D2 的局部约束下没有可比较的剩余控制方向，
  因此它不用于这个“加权选择是否更好”的 pilot；两区/三区析因问题留给 C5。
- 两种选择器拥有完全相同的三个物理控制量、绝对边界、信赖域、初值、冻结脉冲、网格、tqual、时间积分、
  母cohort、K 个候选和真实 PA 评价预算。候选池必须在读取任何 detector result 前一次性发布；不得按任一
  选择器的中间结果增添候选。
- `development + validation` 只建立并冻结每个源的条件均值、协方差、白化尺度、约束 Jacobian 和秩容差。
  `optimization` 只允许计算两种预测分数及从同一 K 个候选各选一个；`locked_test` 仅在两点及预测顺序冻结后读取。
- 每个候选的真实场时间灵敏度必须由同一数值身份、同一局部初态的六个 canonical state `+/-`中心差分生成；
  收据绑定候选池 SHA、状态顺序、步长和数值身份。它可读取用于局部导数的单粒子到达时间，但不可读取任何
  ensemble FWHM、传输率、尾部、模式或 locked-test 结果。
- 每个真实 PA 候选运行完整冻结母cohort，保留逐事件 loss census。分析可按角色过滤到 optimization 或
  locked-test，但不得以共同 detector 命中交集替换母cohort分母。

## 预注册评价

对每个源分别报告：

1. 两种预测器在同一 K 候选上的优化角色排序相关及 bootstrap 区间；
2. 两者选择的候选在 locked-test 上的直接到达时间总方差、FWHM、分位宽、主峰/尾部及模式；
3. 完整母cohort 检测率、每类损失、约束残差、有效秩、条件数和活跃边界；
4. source-weighted 选择相对未加权选择的成对差与 bootstrap CI。

首轮的最小条件是 51.2 mm 主工况满足：预测排序的 bootstrap 下界大于零、source-weighted 所选点的 locked
总展宽优于未加权所选点、且改善没有降低完整母cohort检测率。随后才以 0 mm / 102.4 mm 判断该结论是否随
残差—传输权衡而消失或保留。任一主工况条件失败即为`INCONCLUSIVE_REVISE`，并保留负结果；不得再按
detector 结果调整候选池、边界或源模型。

## 样本量与阶段边界

- 已有 S1 N=5000 gap triplet 是 `DEVELOPMENT_ONLY`，只能说明 51.2 mm 可能跨过 J2 所需的残差门槛：
  0/51.2/102.4 mm 的 OA-pre-pulse observed counts 为 4558/393/117，不能升级为锁定 J2 证据。
- 51.2 mm 的 J2 pilot 先使用一份新冻结的 N=5000 母群；若它通过流程门槛，再以独立 N=5000 母群重复，
  合并前必须保持 run 间独立的 cohort 和 manifest。102.4 mm 若要承担 J2 结论，须先以独立母群把可用
  locked-test 状态提高到预注册下限；不得把低传输样本静默补成“等效 N”。不得直接缩放下游100 Th状态，
  也不得把 pilot 升级为多质量或 JASMS 证据。
- 独立 C3_J3 轴场参考仍可完成，但不应阻塞本 pilot 的纯合同、候选池和分析实现；商业 SIMION 实际运行按
  公共调度器串行。

## 声明边界

若 pilot 通过，只允许声明：在这两种冻结、无碰撞、独立粒子 RF→OA 源及本合同控制边界内，J2 的
source-weighted predictor/selection 比未加权选择具有预注册的预测力。禁止称其为物理下限、普适结构优越性、
实测源结论、Candidate/Formal资格或 JASMS-ready。

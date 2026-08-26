# C1：S1 三点 connector-gap 残差—传输率合同

> `STATUS: PLANNED / DETECTOR_BLIND_SOURCE_ONLY / EXECUTE_SIMION_SERIALly`

## 目标

在同一个 S1 多极杆入口母群中，检验 `gap=0 / 51.2 / 102.4 mm`
是否形成预期的**条件轴向随机残差降低—完整母群传输下降**权衡。此合同只建立 C1
源侧证据；不得由 detector、FWHM、分辨率、优化器或 C2/C3 输出选择脉冲时刻。

## 冻结对象与唯一变量

- 根母 cohort：既有 S1 多极杆入口 `N=5000`。每个臂均从这同一有序的 5000 ID 独立释放、贯通
  多极杆—connector—OA 前端；不得把一个 gap 的 terminal handoff 幸存者预先作为另一 gap 的输入。
  不创建 N=100 子样本，也不把共同存活 ID 当作传输分母。选择 5000 的原因是历史 102.4 mm
  通过率约为 1%；其预期约 50 个幸存者，N=1000 预期约 10 个，不足以稳定估计长 gap 的条件残差。
- 臂：`rf_octupole_oatof_shield_terminal_direct_mating_gap_0mm`、
  `rf_octupole_to_single_reflection_oatof_direct_mating_gap_51p2mm`、
  `rf_octupole_to_single_reflection_oatof_direct_mating_gap_102p4mm`。
- 不变项：S1 entrance source SHA、RF 波形/相位、多极杆、前端孔径与场 profile、三区 Candidate、数值
  profile、质量和完整母群 ID 顺序。
- 唯一物理变量：连接器长度及其由 connection profile 明示的、连续接地屏蔽几何。

## 每臂的固定执行顺序

1. 先由现有 integration pulse 机制按冻结身份复用已有的验证时刻；若没有完全相同身份的 receipt，
   则用同一 `multipole_handoff_ballistic_centroid_v1` 确定性派生每臂时刻。两者是本实验唯一的时刻
   机制，禁止另行以时间窗、detector 或峰宽重选时刻。
2. 以该时刻运行一次 pulse-on 的真实 PA、RF、全 5000-ID 连续飞行，并从同一 run 的
   `pre_pulse_state` checkpoint 建立源侧模型与完整命中/损失账本。多极杆内损失、connector/前端损失、
   加速器前缺失和 pulse 不适格必须分开记录。
3. 三臂均完成后，按粒子 ID hash 划分 development/validation/optimization/locked-test；每臂只用
   development 拟合、validation 选阶，且仅用共同 locked IDs 计算配对残差。共同 ID 仅是因果诊断；
   传输率一律相对 5000 入口母群报告。旧的 900 terminal-handoff 分母只可作为历史条件诊断，
   不进入本合同的主结果。

## C1 门槛与结论

| 判据 | PASS_CONTINUE | INCONCLUSIVE_REVISE |
| --- | --- | --- |
| 三臂 pulse-on 连续飞行 | 都成功，且 pre-pulse checkpoint、解析脉冲时刻与 manifest 相互绑定 | 任一臂无可用状态、或飞行失败；不得用扫窗取代该负结果 |
| ID 与分母 | 三臂入口 ID hash 相同，且每臂均从 5000 起算并保留完整损失分类 | 预先固定 terminal-handoff 幸存者、或共同存活者替代了母群分母 |
| 残差比较 | 报告各相邻 gap 对实际共同 locked-ID 数、有效样本量和 bootstrap CI；据此判定其是否足以支持条件残差比较 | 样本不足或模型选择不稳定 |
| 机制方向 | 长 gap 的条件残差变化与传输变化均以 CI 报告；不要求单调才记录负结果 | 无法把脉冲时序失配与几何效应区分 |

`PASS_CONTINUE` 只表示三点的 detector-blind 源侧 trade-off 已被量化，可作为 C2 的冻结输入。
不支持“gap 最优”“分辨率改善”“三区优越”或论文性能主张。若某个臂的条件残差没有下降，但 pulse
确认和分母闭合，结论应保留为有效负结果，而非重选 detector 最优时刻。

## 与 C2/C3 的依赖

- C2 必须读取本合同冻结的三臂 source model、协方差、尾部、发射度、适格率和 loss census；不得使用
  历史 gap×field 的峰宽表替代。
- C3 的独立轴场积分器与该合同物理上独立，但真实 SIMION 运行与本合同共用商业求解器、PA cache 和
  artifact 生命周期，故外层运行严格串行。C3 的纯 Python/静态诊断可以并行准备。

## 当前状态

- 0 mm 与 51.2 mm 的既有记录只分别证明固定种子或 detector-blind 候选窗口的局部事实；它们从已传输
  terminal handoff 继续，故仅可作条件诊断，不能替代本合同的 5000-ID 三臂 pulse-on confirmation。
- 102.4 mm 尚未建立同版本的 real-field detector-blind candidate；历史 23 臂 gap×field 结果均为
  `DEVELOPMENT_ONLY`，不进入本合同的统计输入。
- 下一步：冻结一个三臂 N=5000 `continuous_frontend` exploration（用户现有的 0 mm、N=1000
  terminal-handoff 文件保持不改），依上述顺序串行执行并发布 C1 三件套。

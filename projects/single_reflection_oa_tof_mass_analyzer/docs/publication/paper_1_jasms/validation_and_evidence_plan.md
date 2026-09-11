# Paper 1：JASMS 研究与证据计划

本文统一维护科学问题、文章结构、工作包和关闭条件；当前执行资格只见
[evidence_matrix.md](evidence_matrix.md)，候选主张与允许措辞只见
[claim 注册表](../prior_art_claim_registry.md)，跨稿数据与公开边界只见
[重叠防火墙](../overlap_and_claim_firewall.md)。

候选题目：*Source-Conditioned Control-Subspace Analysis of an Orthogonal-Acceleration Time-of-Flight Mass Spectrometer*。
这是工作题目，不能用标题暗示尚未完成的预测验证。目标期刊及其投稿要求应在真正投稿前按
[官方作者指南](https://researcher-resources.acs.org/publish/author_guidelines?coden=jamsef)复核。

## 独立科学问题

真实RF多极杆输出不是无厚度的单值`z-v_z`曲线。Paper 1回答：

1. 沿条件均值流形的局部高阶closure实际消除了什么？
2. 有限条件厚度通过哪些source-to-detector时间模态产生残差峰宽？
3. 保持已有聚焦和工程约束后，分析器还能控制多少残差？
4. 新增场区是否提供真正独立、与未解决残差重叠的控制方向？
5. 何时应继续优化分析器，何时必须改变源条件分布？

## 主张与模型边界

J1 为归因框架，J2/J3 为待验证的候选中心，J4/J5 只作为后果；不将经典聚焦、场区数或数学工具本身声称为创新。
公式与局部适用域见[条件可聚焦性理论](../../theory/conditional_phase_space_focusability.md)。

## 成功判据

Paper 1成功不是得到一个高`R`候选，而是同时证明：

1. 条件厚度对真实峰宽有独立且可重复的贡献；
2. 残差模态归因能通过消融或源工况变化验证；
3. 受约束focusability能预测局部重新优化收益和新增控制方向价值；
4. 结论在公平架构比较、多质量、三维场和独立求解路径中保持；
5. 峰宽收益没有由粒子损失、后筛选或不公平预算制造。

## WP0：先行工作与claim冻结

当前先行工作证据及缺口只查 [claim 注册表](../prior_art_claim_registry.md)。

### 动作

- 保存已核对正文的哈希，继续获取2015/2026 SI及其他closest-work全文；
- 逐式比较source模型、有限spread、整机时间映射和优化判据；
- 检索多区OA、相空间调理、RF→OA接口和自动优化专利族；
- 为J1–J5填写closest work、相同点、差异和允许措辞。

### 关闭条件

- 每个主claim都有可审查的全文/专利记录；
- 没有依赖摘要或“未搜到”形成的`first`措辞；
- 若发现等价先行工作，先重构claim再进入实现。

### WP0后立即执行的最小杀伤试验

在大规模3D或公平架构campaign前，只复用冻结observed source完成：

1. 条件模型与source covariance；
2. 完整时间灵敏度`g`与约束null space；
3. source-whitened projector/QP和bootstrap；
4. 对既有two/three-zone局部扰动预注册收益排序；
5. 至少两种source condition的小型locked direct-particle检验。

若预测方向、floor或新增控制方向收益不能跨工况闭合，J2/J3直接`NO_GO`，不启动WP3/WP4昂贵矩阵。

## WP1：冻结真实条件源

### 输入要求

至少两种物理独立source condition，例如不同RF幅值、DC梯度、压力/冷却或提取相位。每个粒子在共同
pre-pulse时刻保存：

```text
particle_id, mass_to_charge, charge
x, y, z, vx, vy, vz
rf_phase, absolute_time, pulse_epoch
eligibility and source condition
```

动能若由速度重算，不作为独立拟合变量重复加入。

### Cohort

- source-model training；
- model-selection validation；
- analyzer-optimization cohort；
- 完全锁定的blind test。

标准统计结论的locked test每工况至少N=1000；优选一个N=5000母cohort或多个独立N=1000重复。较小
样本必须是同一种子母样本的声明前缀。

### 分析

- 多维条件均值与异方差；
- affine、受限非线性和非参数候选；
- shrinkage/regularization及有效样本量；
- 残差尾部、多模态和bootstrap；
- 固定单位、无量纲尺度和cohort hash。

### 关闭条件

- 模型选择完全detector-blind；
- locked test在模型冻结后才启封；
- 条件模型及不确定度在至少两种工况可重复；
- source authority可由manifest和有序粒子ID重建。

## WP2：到达时间灵敏度与focusability实现

### 动作

- 在现有解析oracle上实现多变量`g`和设计响应`∂g/∂θ`；
- 建立缩放、constraint null space、stacked source weighting、projector、SVD和有界QP；
- 明确pseudoinverse、rank、bootstrap和信赖域策略；
- 对损失粒子保存census，不以共同命中交集替代母cohort性能。

### 独立验证

- analytic或automatic differentiation；
- 多步长中心差分；
- projector与直接least-squares/QP；
- 局部预测与exact particle perturbation；
- 参数缩放、rank tolerance和条件模型重采样敏感性。

### 关闭条件

- 两条真正独立导数路径在预注册容差内一致；
- projector/QP和约束残差闭合；
- direct particle结果给出可复现的线性信赖域；
- 模态排序不由任意单位或单个bin选择决定。

## WP3：公平架构与目标比较

对同一training/optimization source分别充分优化：

```text
A. fully reoptimized two-zone baseline
B. fully reoptimized three-zone design
C. source-weighted constrained design
D. unweighted D1/D2/D3 closure control
```

冻结：

- 几何、长度、孔径、电压、场强和折返裕量；
- detector和命中/损失定义；
- 粒子ID、质量点和source condition；
- 优化预算、初始化政策和停止条件；
- 峰算法和bootstrap；
- 数值profile。

每个方案必须在自身允许参数空间中充分重优化。禁止用affine源上的三区最优点直接承受observed源，再
把性能下降解释为架构原则失败。

### 关闭条件

- 所有方案有相同预算和失败记录；
- 结果在blind test而不是训练目标上比较；
- 报告Pareto前沿，不只比较新方案最好点与baseline默认点；
- 峰形改善没有依靠更低传输或不同后处理。

## WP4：模型层级和求解器独立性

### 最低矩阵

| 因子 | 最低水平 |
|---|---|
| Source |
| Source condition | 至少2种 |
| Accelerator | two-zone、three-zone、source-weighted、unweighted control |
| Reflectron | 局部闭式对照、整机耦合优化 |
| Field | ideal segmented、真实轴线场、3D SIMION |
| Independent check | 关键COMSOL或独立field/trajectory implementation |
| Mass | 至少3个代表质量点 |
| Envelope | 至少3个源宽/残差水平 |
| Statistics |

### 关闭条件

- 一维oracle与三维事件时间导数的偏差有量化边界；
- 主claim不依赖单一SIMION网格或同一Python核心；
- 至少一个关键工况完成网格、时间步和粒子统计检查；
- 坐标、时钟、探测面、粒子ID和FWHM定义跨路径一致。

## WP5：模态消融和预测检验

### H1检验

保持条件均值流形不变，按预注册比例缩放条件残差，检查`D1/D2/D3`与direct peak的分离。

### H2检验

沿冻结无量纲残差子空间做受控消融；比较`q_k`排序、预测方差和direct-particle峰宽。近简并模态按
子空间整体消融。

### H3/H4检验

比较projector预测、有限步长重优化和direct trajectory；新增场区的`a_perp/DeltaJ`必须在独立source
condition上预测收益或无收益。

### H5检验

使用至少两种source condition，在启封最终结果前登记“改分析器、source-weighted重优化或改源”的
预测，并用独立运行验证。

## WP6：统计和报告

必须报告：

- direct FWHM和population sigma；
- 50%、90%及1–99%分位宽；
- main-mode和tail fraction；
- 完整母cohort命中率与损失分类；
- detector位置/角度包络；
- bootstrap区间；
- source-model和optimization seed敏感性；
- active constraints、rank、singular values和条件数；
- 负结果和失败边界。

不允许只报告最高质量分辨率或只在共同命中交集上报告性能。

## 投稿门槛

| 门槛 | 关闭判据 |
|---|---|
| Novelty | WP0全文claim chart完成，J2/J3允许措辞冻结，具体IP另行审查 |
| Source | 两工况、detector-blind、locked N≥1000 |
| Focusability | WP2全部独立校核通过 |
| Fair baseline | A–D充分重优化和blind Pareto比较 |
| 3D independence | 多质量3D SIMION + 关键独立路径 |
| Statistics | 直接峰、尾部、传输和CI完整 |
| Generality | 至少两源工况、三质量和多个场模型 |

门槛的当前状态只查证据矩阵；本计划不维护第二份状态表。任一主claim所需门槛未关闭时，不进入JASMS投稿冻结。

## 文章结构

### Introduction

1. OA-TOF峰宽受完整源相空间而非独立标量宽度控制；
2. 已有space–velocity correlation和coupled focusing的贡献；
3. 真实RF源的条件厚度、异方差和尾部；
4. 局部高阶closure与有限分布最优之间的缺口；
5. 本文的可证伪问题、方法和证据范围。

### Theory

- pulse-relative时钟和共同pre-pulse源；
- 多维条件流形与厚度；
- total variance和高阶适用边界；
- N-zone OA、dual-stage reflectron与统一参考面；
- 受约束focusability、残差模态和新增控制方向；
- 有限孔径和传输边界。

### Methods

- source authority、cohort split和detector-blind模型选择；
- analytic/AD/finite-difference导数交叉校核；
- two-zone、three-zone、unweighted和source-weighted公平优化；
- ideal、轴线场、3D SIMION和独立COMSOL/实现；
- 峰提取、bootstrap、损失census和盲化test。

### Results

1. exact oracle与三维导数一致性；
2. affine薄源的局部closure；
3. observed条件厚度、异方差和残差模态；
4. predicted variance/floor与direct-particle结果；
5. 充分重优化的架构比较；
6. 多质量和多source condition稳健性；
7. 新增场区何时有用、何时无用；
8. 分析器优化与source conditioning的决策图。

### Discussion

- 与1974/1994/1996/2005/2006/2010/2015/2016/2017/2024/2026工作的明确差异；
- 局部projector和协方差近似的边界；
- 非高斯、孔径、脉冲、空间电荷和实验源推断限制；
- 对oa-TOF源接口和分析器设计的可推广启示。

### Conclusions

结论应落在受约束、source-conditioned的设计判据，而不是最高分辨率纪录：

> High-order closure along a source manifold is effective only to the extent that the remaining conditional source modes have weak timing projection or lie within the feasible control subspace of the complete analyzer.

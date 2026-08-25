# OA-TOF先行工作与候选claim注册表

> `STATUS: WORKING SCIENTIFIC REVIEW / NOT_LEGAL_ADVICE`
>
> `REVIEW_DATE: 2026-08-25`

本表用于科学新颖性和投稿措辞治理，不是完整文献综述、专利FTO或法律意见。任何`first`、`novel`、
`unprecedented`必须先完成全文、引用链、专利族和公司IP审查。目前没有任何候选claim处于已确认
`GREEN`状态。

## 1. 风险等级

| 等级 | 含义 | 稿件处理 |
|---|---|---|
| `RED_KNOWN` | 已有明确理论、论文或专利 | 只能作为背景、复现或实现 |
| `ORANGE_OVERLAP` | 已有高度接近思想 | 必须精确定义差异，不用宽泛新颖性措辞 |
| `YELLOW_CANDIDATE` | 未确认相同完整组合，但构件已知 | 系统检索和独立证据后再决定claim |
| `GREEN_EVIDENCED` | 差异已核查且项目证据完整 | 才可考虑强claim，仍需编辑/IP审查 |
| `INTERNAL_IP` | 可能可专利或应保密 | 先申请或内部审查 |

## 2. 已确认的先行工作边界

| 内容 | 状态 | 代表来源 | 禁止性结论 |
|---|---|---|---|
| 双区/多场空间聚焦 | `RED_KNOWN` | Wiley & McLaren 1955, DOI `10.1063/1.1715212` | 不能声称首次多区或多场聚焦 |
| reflectron与多级速度聚焦 | `RED_KNOWN` | Mamyrin 1973；Doroshenko & Cotter 1999, DOI `10.1016/S1044-0305(99)00067-7` | 不能声称首次二级reflectron或整机能量聚焦 |
| 空间—速度相关聚焦 | `RED_KNOWN` | Colby & Reilly 1996, DOI `10.1021/ac950716q` | 不能声称首次考虑位置—速度相关 |
| oa-TOF相关相空间 | `RED_KNOWN` | Papanastasiou & McMahon 2006, DOI `10.1016/j.ijms.2006.04.014`；2005 thesis DOI `10.83056/mmu.32482788` | 不能声称首次线性、非线性相关或有限到达时间展宽 |
| coupled space/velocity focusing | `RED_KNOWN` | Cai et al. 2015, DOI `10.1007/s13361-015-1206-y` | 不能声称首次联合空间和速度聚焦 |
| 高阶reflectron联合聚焦 | `ORANGE_OVERLAP` | Cai & Wang 2026, DOI `10.1021/jasms.5c00167` | 场区数、高阶导数和联合调参本身不足以构成新意 |
| phase space/emittance/matching | `RED_KNOWN/ORANGE_OVERLAP` | charged-particle optics与beam matching文献 | 不能把Liouville、辛映射或相空间匹配本身称为新理论 |
| 协方差、PCA、投影、SVD、KKT、Pareto | `RED_KNOWN` | 标准统计、线性代数和优化 | 不能把数学工具本身称为发明 |

核心来源入口：

- <https://pubs.acs.org/doi/10.1021/ac950716q>
- <https://doi.org/10.1016/j.ijms.2006.04.014>
- <https://repository.mmu.ac.uk/articles/thesis/Space_velocity_correlation_in_orthogonal_time-of-flight_mass_spectrometry/32482788>
- <https://pubs.acs.org/doi/10.1007/s13361-015-1206-y>
- <https://www.sciencedirect.com/science/article/pii/S1044030599000677>
- <https://pubs.acs.org/doi/10.1021/jasms.5c00167>

## 3. Paper 1候选claim

### 3.1 J1：条件均值流形与有限条件厚度的功能分离

- 状态：`YELLOW_CANDIDATE / STRONG_PRIOR_ART_CONTEXT`
- 候选表述：在完整oa-TOF映射中，区分沿条件均值流形的高阶时间closure和有限条件厚度的残差时间投影。
- 必须证明的差异：共同pre-pulse经验源、多变量条件分布、完整OA—reflectron映射、直接粒子验证，以及
  tangent和residual贡献的受控分离。
- 最大风险：2005 thesis已讨论非线性分布和有限arrival-time spread；全文逐式比较尚未完成。

### 3.2 J2：受约束focusability projector

- 状态：`YELLOW_CANDIDATE`
- 候选表述：在保持低阶和工程约束后，source-whitened时间灵敏度落在可行分析器控制子空间之外的分量
  给出局部一阶残差参考下界。
- 已知构件：加权最小二乘、null space、projector、beam matching。
- 必需证据：多个源工况、质量和三维场中，projector预测与公平重新优化的direct-particle floor闭合。
- 禁止表述：发明projector/SVD优化。

### 3.3 J3：残差模态与新增控制方向的重叠

- 状态：`YELLOW_CANDIDATE`
- 候选表述：新增场区只有在保持旧约束后增加独立source-weighted控制方向，并与未解决残差时间方向
  重叠时，才稳定改善有限源峰宽。
- 与`Γ3`区别：`Γ3`只针对单个`D3`标量；J3针对真实源metric下的未控制时间方向。
- 风险：一般控制理论存在等价controllability表述；价值必须来自oa-TOF物理结论和验证。

### 3.4 J4：source-weighted设计优于未加权导数closure

- 状态：`YELLOW_CANDIDATE`
- 必需证据：fully reoptimized baseline、相同预算和边界、独立locked test、直接峰形、尾部和传输。
- 风险：按分布优化可能被视为常规目标函数替换；必须形成有预测力的criterion和跨工况定量结论。

### 3.5 J5：由focusability选择改分析器还是改源

- 状态：`YELLOW_CANDIDATE`
- 必需证据：至少两种源工况，诊断须事前预测不同最优干预，再由独立仿真或实验验证。
- 潜在价值：把一次失败解释升级为可推广的研发决策规则。

## 4. Paper 2候选claim

### 4.1 A1：实际active phase-space conditioner

- 状态：`INTERNAL_IP / YELLOW_CANDIDATE`
- 已知重叠：ion-beam conditioning、emittance matching、RF guides/coolers和相关专利。
- 要求：先做patentability与FTO；公开前冻结可披露范围。

### 4.2 A2：conditioner—OA—reflectron联合稳健设计

- 状态：`YELLOW_CANDIDATE`
- 不能只靠把三个模块放进同一个optimizer；必须证明分步充分重优化仍无法达到相同前沿，并说明联合设计
  如何利用Paper 1识别的mode mismatch。

### 4.3 A3：实验性移动分析性能前沿

- 状态：`YELLOW_CANDIDATE -> GREEN only after prototype evidence`
- 必需证据：同输入、尺寸、电压、detector和采集时间下的prototype A/B、归一化输入通量、占空比、
  灵敏度、稳定性和真实分析终点。

## 5. 正式检索任务

Paper 1投稿前至少完成：

1. 1996、2006、2015、2026核心工作的全文逐式比较；
2. 2005 thesis中非线性分布、finite spread和oa-TOF实验章节审查；
3. 核心论文的引用与被引链；
4. multistage/multizone OA、phase-space conditioner、RF multipole→OA、自动调谐和波形补偿专利族；
5. conference proceedings、学位论文、厂商技术论文和近五年JASMS/IJMS/Analytical Chemistry；
6. 每个claim填写最接近论文、最接近专利、相同点、差异、物理意义、所需证据和允许措辞。

“快速检索未发现”不能等价为“首次”。

## 6. 当前允许和禁止的措辞

允许：

> We formulate and test a source-distribution-aware focusability analysis for a complete orthogonal-accelerator–dual-stage-reflectron system, separating closure along the conditional mean source manifold from the timing projection of finite conditional thickness.

只有证据完成后才允许：

> The constrained control-subspace analysis quantitatively predicted the residual timing floor and the incremental benefit of an additional analyzer control direction across independent source conditions and three-dimensional field models.

当前禁止：

- first consideration of phase-space correlation in oa-TOF；
- novel OA–dual-stage-reflectron architecture；
- first third-order focusing with a three-zone accelerator；
- universal or fundamental resolution limit；
- random residual is intrinsically unfocusable。

## 7. 当前新颖性结论

当前工作不是因与前人重复而整体失去投稿资格，但经典OA、reflectron、`z-v_z`、多区和高阶closure部分
本身没有新颖性。尚可能具有新颖性的窄边界是：完整oa-TOF中条件厚度与切向closure的受约束分离、
source-weighted可行控制子空间对真实残差的预测，以及该诊断对“改分析器还是改源”的可证伪决策能力。

这些仍是候选贡献。若全文审查发现2005/2006或其他工作已经给出等价条件残差分解和架构控制子空间
判据，或者本项目不能用独立真实源和三维公平重优化证明预测力，Paper 1就不具备当前JASMS主张下的
投稿条件，应缩小claim、补充新方法或改投定位更偏实现/计算的期刊。

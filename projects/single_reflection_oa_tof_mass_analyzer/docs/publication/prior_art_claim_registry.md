# OA-TOF先行工作与候选claim注册表

> `STATUS: WORKING SCIENTIFIC REVIEW / NOT_LEGAL_ADVICE`
>
> `REVIEW_DATE: 2026-08-25`

本表用于科学新颖性和投稿措辞治理，不是完整文献综述、专利FTO或法律意见。任何`first`、`novel`、
`unprecedented`必须先完成全文、引用链、专利族和公司IP审查。目前没有任何候选claim处于已确认
`GREEN`状态。2026-08-25定向检索的证据、claim碰撞和查询边界冻结在
[`prior_art_search_audit_20260825.md`](prior_art_search_audit_20260825.md)。

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
| 一维space/velocity关系与最低时间分辨 | `RED_KNOWN` | Stein 1974, DOI `10.1016/0020-7381(74)80008-2` | 不能把空间/速度分解或宽泛“基本极限”写成新理论 |
| phase-space time focusing与体积守恒 | `RED_KNOWN` | Stein 1994, DOI `10.1016/0168-1176(93)03934-E` | 不能把Liouville、相空间体积或一般下界写成新理论 |
| reflectron与多级速度聚焦 | `RED_KNOWN` | Mamyrin 1973；Doroshenko & Cotter 1999, DOI `10.1016/S1044-0305(99)00067-7` | 不能声称首次二级reflectron或整机能量聚焦 |
| 空间—速度相关聚焦 | `RED_KNOWN` | Colby & Reilly 1996, DOI `10.1021/ac950716q` | 不能声称首次考虑位置—速度相关 |
| oa-TOF相关相空间 | `RED_KNOWN` | Papanastasiou & McMahon 2006, DOI `10.1016/j.ijms.2006.04.014`；2005 thesis DOI `10.83056/mmu.32482788` | 不能声称首次线性、非线性相关或有限到达时间展宽 |
| 多场高阶focus的实际收益受初始速度限制 | `RED_KNOWN` | Yildirim et al. 2010, DOI `10.1016/j.ijms.2009.12.014` | 不能把“新增场区对真实spread可能无收益”本身写成首次发现 |
| coupled space/velocity focusing | `RED_KNOWN` | Cai et al. 2015, DOI `10.1007/s13361-015-1206-y` | 不能声称首次联合空间和速度聚焦 |
| RF/碰撞池到OA的自然相关与整机导数优化 | `ORANGE_OVERLAP` | SCIEX ASMS 2016 N-geometry poster | 不能声称首次把RF源相关、OA与reflectron联合优化 |
| RF/DC gas-cell phase-space conditioning | `RED_KNOWN/ORANGE_OVERLAP` | Waters ASMS 2017 TP391；相关ion-guide专利族 | 宽泛active conditioner和resolution—sensitivity权衡不是新意 |
| 轨迹数据驱动的高阶focus条件搜索 | `RED_KNOWN` | Kambarova et al. 2024, DOI `10.1088/2631-8695/ad1c0a` | 导数、有限差分、数值focus-order搜索本身不是新方法 |
| 高阶reflectron联合聚焦 | `ORANGE_OVERLAP` | Cai & Wang 2026, DOI `10.1021/jasms.5c00167` | 场区数、高阶导数和联合调参本身不足以构成新意 |
| phase space/emittance/matching | `RED_KNOWN/ORANGE_OVERLAP` | charged-particle optics与beam matching文献 | 不能把Liouville、辛映射或相空间匹配本身称为新理论 |
| 协方差、PCA、投影、SVD、KKT、Pareto | `RED_KNOWN` | 标准统计、线性代数和优化 | 不能把数学工具本身称为发明 |

核心来源入口：

- <https://pubs.acs.org/doi/10.1021/ac950716q>
- <https://www.sciencedirect.com/science/article/pii/0020738174800082>
- <https://doi.org/10.1016/j.ijms.2006.04.014>
- <https://repository.mmu.ac.uk/articles/thesis/Space_velocity_correlation_in_orthogonal_time-of-flight_mass_spectrometry/32482788>
- <https://pubs.acs.org/doi/10.1007/s13361-015-1206-y>
- <https://www.sciencedirect.com/science/article/pii/S1387380610000047>
- <https://sciex.com/content/dam/SCIEX/pdf/posters/asms2016_431_Tue_Loyd_Haufler.pdf>
- <https://support.waters.com/Select/cIMS/Posters_and_Publications/Conference_Posters/ASMS_2017/TP391_A_high_performance_OA-ToF_mass_spectrometer_for_accurate_mass_measurement_of_mobility_separated_ions>
- <https://doi.org/10.1088/2631-8695/ad1c0a>
- <https://www.sciencedirect.com/science/article/pii/S1044030599000677>
- <https://pubs.acs.org/doi/10.1021/jasms.5c00167>

## 3. Paper 1候选claim

### 3.1 J1：条件均值流形与有限条件厚度的功能分离

- 状态：`ORANGE_OVERLAP / FRAMEWORK_NOT_STANDALONE_NOVELTY`
- 候选表述：在完整oa-TOF映射中，区分沿条件均值流形的高阶时间closure和有限条件厚度的残差时间投影。
- 必须证明的差异：共同pre-pulse经验源、多变量条件分布、完整OA—reflectron映射、直接粒子验证，以及
  tangent和residual贡献的受控分离。
- 最大风险：Stein 1974/1994、1996 SVCF、2005 thesis和2006 OA工作已覆盖space/velocity关系、相空间、
  非线性分布和有限arrival-time spread。J1只能服务J2/J3的定义与归因，不能单独承担首创新颖性。

### 3.2 J2：受约束focusability projector

- 状态：`YELLOW_CANDIDATE`
- 候选表述：在保持低阶和工程约束后，source-whitened时间灵敏度落在可行分析器控制子空间之外的分量
  给出局部一阶残差参考下界。
- 已知构件：加权最小二乘、null space、projector、beam matching。
- 必需证据：多个源工况、质量和三维场中，projector预测与公平重新优化的direct-particle floor闭合。
- 禁止表述：发明projector/SVD优化。

### 3.3 J3：残差模态与新增控制方向的重叠

- 状态：`YELLOW_CANDIDATE / HIGH_OBVIOUSNESS_RISK`
- 候选表述：新增场区只有在保持旧约束后增加独立source-weighted控制方向，并与未解决残差时间方向
  重叠时，才稳定改善有限源峰宽。
- 与`Γ3`区别：`Γ3`只针对单个`D3`标量；J3针对真实源metric下的未控制时间方向。
- 风险：一般控制理论存在等价controllability表述，2010 multi-field负结果和2016 SCIEX整机导数优化
  也已给出接近物理语境；价值必须来自source-weighted增量判据的事前、跨工况预测。

### 3.4 J4：source-weighted设计优于未加权导数closure

- 状态：`ORANGE_OVERLAP / SECONDARY_RESULT_ONLY`
- 必需证据：fully reoptimized baseline、相同预算和边界、独立locked test、直接峰形、尾部和传输。
- 风险：1996 SVCF、2015 comprehensive all-ion calculation和2024 numerical focus search使按有限分布优化
  本身接近常规目标替换；只能作为J2/J3预测得到验证的结果，不能作为独立方法claim。

### 3.5 J5：由focusability选择改分析器还是改源

- 状态：`ORANGE_OVERLAP / SECONDARY_TRIAGE_RESULT`
- 必需证据：至少两种源工况，诊断须事前预测不同最优干预，再由独立仿真或实验验证。
- 潜在价值：把一次失败解释升级为工况条件化的预测结果。一般的source-conditioning与analyzer权衡
  已被论文、厂商材料和专利明确讨论，不是新的设计原则。

## 4. Paper 2候选claim

### 4.1 A1：实际active phase-space conditioner

- 状态：`RED_KNOWN_AS_BROAD_CLAIM / INTERNAL_IP_IF_TOPOLOGY_SPECIFIC`
- 已知重叠：ion-beam conditioning、emittance matching、RF guides/coolers、RF/DC gas cell、beam expander、
  periodic lens、spatial-temporal correlation和多个active专利族。
- 要求：功能级“conditioner”不能作为新颖性；选定具体拓扑、波形或控制律后再做patentability与FTO，
  公开前冻结可披露范围。

### 4.2 A2：conditioner—OA—reflectron联合稳健设计

- 状态：`ORANGE_OVERLAP`
- 不能只靠把三个模块放进同一个optimizer；必须证明分步充分重优化仍无法达到相同前沿，并说明联合设计
  如何利用Paper 1识别的mode mismatch。

### 4.3 A3：实验性移动分析性能前沿

- 状态：`YELLOW_CANDIDATE -> GREEN only after prototype evidence`
- 必需证据：同输入、尺寸、电压、detector和采集时间下的prototype A/B、归一化输入通量、占空比、
  灵敏度、稳定性和真实分析终点。

## 5. 检索状态与剩余关闭任务

2026-08-25已完成一轮定向论文、引用链、厂商资料和专利族预审，结果见
[`prior_art_search_audit_20260825.md`](prior_art_search_audit_20260825.md)。它已足以否决J1、J4、J5和A1
的宽泛新颖性表述，但不等于WP0或法律FTO关闭。

Paper 1投稿前仍至少完成：

1. 人工取得并保存2005 thesis、1989、2015和2026正文/SI，完成逐式claim chart；
2. 对J2/J3做引文向前/向后补搜，并让领域专家独立复核等价表述；
3. 对未来具体conditioner按独立权利要求逐元件比较continuation、同族、法域和有效状态；
4. 由公司/专利律师完成patentability/FTO；
5. J2/J3经locked direct-particle预测验证后，按实证差异冻结最终允许措辞。

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

当前工作不是因与前人重复而整体失去投稿资格，但经典OA、reflectron、`z-v_z`、非线性相关、有限
arrival-time spread、多区、高阶closure、RF源条件化和一般source/analyzer权衡本身均没有足够新颖性。

当前最强且仍未发现同构先例的窄边界是J2/J3：对共同pre-pulse实测源进行source whitening，在保持
既有聚焦与工程约束后的可行分析器控制子空间中，定量预测完整OA—dual-stage-reflectron的残差floor和
新增控制方向收益。J1只作为框架，J4/J5只作为J2/J3的受验证后果。

这些仍是候选贡献，不是已确认创新。若关键全文给出等价组合，或J2/J3不能在至少两种独立真实源、
locked test和direct-particle公平重优化中产生事前预测力，Paper 1就不具备当前JASMS主张下的投稿条件，
应重构方法、缩小claim或改投定位更偏实现/计算的期刊。

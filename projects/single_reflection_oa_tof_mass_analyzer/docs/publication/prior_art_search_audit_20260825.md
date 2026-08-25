# OA-TOF投稿先行工作与专利族预审（2026-08-25）

> `DOC_STATUS: COMPLETED_TARGETED_PRESCREEN / MANUAL_FULL_TEXT_AND_LEGAL_REVIEW_OPEN`
>
> `SCOPE: SCIENTIFIC_NOVELTY_AND_PRELIMINARY_PATENT_LANDSCAPE / NOT_LEGAL_ADVICE`

本文冻结2026-08-25完成的一轮定向检索、引用链审查和专利族预审。它回答“当前工作是否因前人工作
重复而失去JASMS投稿可能性”，并为下一步实现设置停止条件。活动claim状态仍只由
[`prior_art_claim_registry.md`](prior_art_claim_registry.md)维护；本文是本轮检索的日期化证据和推理记录。

## 1. 结论先行

当前工作的宽泛表述与前人工作显著重合，但尚未因此整体失去JASMS投稿可能性：

- `z-v_z`相关、非线性相关分布、有限到达时间展宽、space/velocity coupled focusing、多场高阶closure、
  RF/碰撞池到OA的束流条件化，以及“分析器还是源”的一般权衡均已有明确论文、会议材料或专利先例；
- J1只能作为物理组织框架，J4与J5不能作为独立的新颖性主claim；
- 本轮检索没有发现把**共同pre-pulse实测源协方差、完整OA—reflectron时间灵敏度、低阶与工程约束的
  可行控制子空间、source whitening和锁定测试中的直接粒子收益预测**组合成同一OA-TOF方法的先例；
- 因此Paper 1应以J2/J3的定量预测能力为主，J1为定义与归因，J4/J5为被验证的设计后果；“未发现”
  不是新颖性证明，只有完成关键全文逐式核查和blind direct-particle验证后才可升级claim；
- Paper 2的宽泛“active phase-space conditioner”已被拥挤的RF ion-guide、beam conditioning、
  spatial-temporal correlation和upstream conditioner专利覆盖。未来只能围绕明确拓扑、波形、控制律和
  实验Pareto前沿另做IP/FTO审查，不能从功能名称推导可专利性。

当前判定：`JASMS_PATH_REMAINS / NOT_SUBMISSION_READY / CLAIM_REWRITE_REQUIRED`。

## 2. 检索范围、证据等级与限制

本轮覆盖：

- 经典space/velocity/time focusing与phase-space动力学；
- OA-TOF相关源分布、非线性、有限spread和virtual source；
- multizone/high-order focusing和数值自动寻找focus条件；
- RF multipole/collision cell到OA的束流形成、调理和resolution—sensitivity权衡；
- 相关论文的引用与被引链；
- 美国、PCT及代表性同族专利的说明书、独立权利要求、优先权和Google Patents显示状态；
- conference poster、厂商技术材料和截至2026-08-25可检索的近期论文。

证据等级：

| 等级 | 本文含义 |
|---|---|
| `PRIMARY_FULL_OR_SECTIONED` | 官方全文、开放全文或可检索的完整章节/权利要求已审查 |
| `PRIMARY_ABSTRACT_PLUS_EXTRACTS` | 官方摘要及关键引言、理论或结论摘录已审查，未完成逐式全文核对 |
| `REPOSITORY_RECORD` | 学位库摘要/元数据已审查，正文尚未本地取得 |
| `DISCOVERY_ONLY` | 只用于扩展检索，不据此作排他性结论 |

明确限制：

1. 2005 thesis的官方9.71 MB下载端点在本次环境未能成功取得；库记录与搜索索引显示了正文关键段落，
   但280页正文的逐式比较仍未关闭；
2. 2015 JASMS正文、2026 JASMS正文/SI和部分付费IJMS文章仍需保存可审查副本并完成逐式对照；
3. Google Patents法律状态是平台提示，不是法律结论；本轮不是claim construction、validity或FTO意见；
4. 关键词检索没有同构结果只支持“当前未发现”，不能支持`first`或`patentable`。

## 3. 核心论文逐项碰撞

| 工作 | 本轮审查到的内容 | 与当前工作的碰撞 | 证据等级 |
|---|---|---|---|
| Stein 1974, DOI [`10.1016/0020-7381(74)80008-2`](https://www.sciencedirect.com/science/article/pii/0020738174800082) | 给出所有一维恒定场TOF的space/velocity focusing关系、指出一维一阶双时间聚焦不可能，并导出最低时间分辨表达式 | “空间与速度贡献分离”及宽泛“基本极限”不是新概念；J1不得写成普遍或fundamental limit | `PRIMARY_ABSTRACT_PLUS_EXTRACTS` |
| Stein 1994, DOI [`10.1016/0168-1176(93)03934-E`](https://doi.org/10.1016/0168-1176(93)03934-E) | 从phase-space dynamics讨论time focusing与time resolution；后续综述明确引用非相关相空间体积守恒 | Liouville/phase-space volume、一般下界和相空间投影不能作为本项目原创理论 | `PRIMARY_ABSTRACT_PLUS_EXTRACTS` |
| Yefchak, Enke & Holland 1989, *IJMSIP* 87, 313–330 | dynamic post-source acceleration模型联合考虑提取电压、场区长度和动态加速函数，目标为mass-independent space/energy focusing | 多场或动态场联合消除space/energy spread不是新颖性 | `DISCOVERY_ONLY`，待取得正文 |
| Colby & Reilly 1996, DOI [`10.1021/ac950716q`](https://pubs.acs.org/doi/10.1021/ac950716q) | 根据初始位置—速度函数关系消去一个变量，以时间展宽为目标优化仪器参数；计算和实验验证time-dependent extraction | 广义“利用相关源分布优化TOF”已知；J1/J4不能只靠相关性或分布目标成立 | `PRIMARY_ABSTRACT_PLUS_EXTRACTS` |
| Papanastasiou 2005 thesis, DOI [`10.83056/mmu.32482788`](https://repository.mmu.ac.uk/articles/thesis/Space_velocity_correlation_in_orthogonal_time-of-flight_mass_spectrometry/32482788) | 明确从线性分布扩展到非线性分布及其有限到达时间展宽；考虑finite initial spatial distributions、focal region、Taylor截断误差、reflecting geometry的virtual source | J1的“非线性+finite thickness/spread”宽泛表述高度重合；只有条件统计、完整实测源归因和控制子空间预测可能构成差异 | `REPOSITORY_RECORD`，逐式全文未关闭 |
| Papanastasiou & McMahon 2006, DOI [`10.1016/j.ijms.2006.04.014`](https://www.sciencedirect.com/science/article/abs/pii/S1387380606002478) | OA原型、两种源、两级加速、可变探测器位置；线性相关分布的一/二阶解析聚焦；指出真实情况为非线性分布，virtual source有限尺寸由初始空间和速度spread决定 | OA、相关源、source-dependent optimum、有限virtual source和非线性都不是新意 | `PRIMARY_ABSTRACT_PLUS_EXTRACTS` |
| Yildirim et al. 2010, DOI [`10.1016/j.ijms.2009.12.014`](https://www.sciencedirect.com/science/article/pii/S1387380610000047) | 系统设计multi-field高阶space focusing；数值和实验表明初始速度分散/turn-around可主导，使增加space-focus阶次在实际条件下无显著收益 | “新增场区未必改善真实源”已有物理先例；J3必须给出不同的source-weighted增量判据和事前预测 | `PRIMARY_FULL_OR_SECTIONED` |
| Cai et al. 2015, DOI [`10.1007/s13361-015-1206-y`](https://pubs.acs.org/doi/10.1007/s13361-015-1206-y) | 以所有关键离子而非两粒子简式联合优化空间/速度聚焦、提取区长度、电位与delay；提出对新设计和商业产品的综合优化 | J4的“finite-distribution/source-weighted优化”若只是换目标函数，很可能是routine extension | `PRIMARY_ABSTRACT_PLUS_EXTRACTS`，正文逐式未关闭 |
| SCIEX ASMS 2016, [N geometry poster](https://sciex.com/content/dam/SCIEX/pdf/posters/asms2016_431_Tue_Loyd_Haufler.pdf) | 从碰撞池到OA的传播自然按速度排序位置；显式利用space–velocity correlation、对速度的一/二阶导数、两反射镜、SIMION/Lorentz，并声称近全束流接受 | 与“RF/碰撞池真实源相关+整机导数优化+高接受度”的组合非常接近；不能声称首次把RF源相关带入OA-reflectron设计 | `PRIMARY_FULL_OR_SECTIONED` |
| Waters ASMS 2017, [TP391](https://support.waters.com/Select/cIMS/Posters_and_Publications/Conference_Posters/ASMS_2017/TP391_A_high_performance_OA-ToF_mass_spectrometer_for_accurate_mass_measurement_of_mobility_separated_ions) | RF-only quadrupole gas cell叠加轴向DC，调理/压缩phase space以兼顾灵敏度与TOF分辨率，并报告窄峰和高分辨率 | Paper 2宽泛“RF/DC conditioner提升OA性能”已有公开实现先例 | `PRIMARY_FULL_OR_SECTIONED` |
| Kambarova et al. 2024, DOI [`10.1088/2631-8695/ad1c0a`](https://doi.org/10.1088/2631-8695/ad1c0a) | 从数值轨迹数据寻找相对初始位置、角度、能量或速度的高阶TOF聚焦条件和焦面，并用相关分析检查更高阶 | 导数、数值轨迹、自动focus-order搜索本身不是新方法 | `PRIMARY_FULL_OR_SECTIONED` |
| Cai & Wang 2026, DOI [`10.1021/jasms.5c00167`](https://pubs.acs.org/doi/10.1021/jasms.5c00167) | 用coupled space/velocity focusing说明单级reflectron结合delayed extraction可实现二阶速度聚焦，优化完整几何和参数 | “单/多级reflectron、高阶导数、联合调参产生新focus条件”不能成为本稿核心 | `PRIMARY_ABSTRACT_PLUS_EXTRACTS`，正文/SI逐式未关闭 |

## 4. 引用链审查结果

引用链显示上述工作不是孤立的旧概念，而是连续演进的设计路线：

```text
Stein 1974/1994
  -> Colby & Reilly 1996 / US5504326-US5712479
  -> Papanastasiou thesis 2005 -> Papanastasiou & McMahon 2006
       -> Yildirim 2010
       -> sector-field OA-TOF 2017
  -> Cai 2015 -> Cai & Wang 2026

RF/collision cooling and beam conditioning patents
  -> SCIEX N-geometry 2016
  -> Waters RF/DC gas-cell conditioning 2017
  -> recent OA/MRTOF interface and spatial-temporal-correlation families
```

关键发现：

- 2006论文的参考链已包含Stein 1994、Colby 1996和2005 thesis；其被引链包含2010 multi-field工作和
  2017 OA sector-field二阶聚焦工作；
- ACS页面显示Colby 1996后续被2015、2024、2026工作直接引用，说明“相关分布+综合优化”是活跃主线；
- 2016 SCIEX和2017 Waters资料把这条理论路线落到ESI/QqTOF、RF/collision cell和高接受度实机语境；
- 因此稿件不能通过只引用Wiley–McLaren、Mamyrin和2006论文来建立差异；必须正面比较1996、2005、
  2010、2015、2016、2017、2024与2026。

## 5. 专利族预审

下表的“状态”只抄录检索日Google Patents显示并用于检索排序，不构成法律意见。

| 家族/代表号 | 优先权；显示状态 | 与当前计划的重叠 | 对claim的影响 |
|---|---|---|---|
| [`US5504326A / US5712479A`](https://patents.google.com/patent/US5712479A/en), *Spatial-velocity correlation focusing* | 1994-10-24；expired-lifetime | 位置是速度的函数、代入TOF方程消元、对电压/距离/delay优化最小时间展宽；说明书覆盖reflectron和非线性场 | J1/J4的宽泛source-manifold优化为`RED_KNOWN` |
| [`US6674071B2 / US20030136905A1`](https://patents.google.com/patent/US20030136905A1), *Ion-guide systems*；及[`US6700117B2`](https://patents.justia.com/patent/6700117) | 2001-12-06附近；历史授权族 | 明确指出OA分辨率取决于primary beam空间/速度分布；用碰撞气体、弱轴向梯度和离子导引形成小phase-space beam | A1“条件化小相空间束流”不是新颖功能 |
| [`US7161146B2`](https://patents.google.com/patent/US7161146B2/en), *Producing an ion beam from an ion guide* | 2005-01-24；检索日显示expired-fee-related | RF trapping逐段/连续减弱、轴向DC、降低出口发散，在相同灵敏度提高OA分辨率或相反 | 渐降RF/轴向DC conditioner是高风险既有拓扑 |
| [`US7772547B2`](https://patents.google.com/patent/US7772547B2/en), *MRTOF with OA* | 2005-10-11；active，显示至2028 | gas-filled RF guide、轴向速度周期调制、加速—减速、与OA同步形成well-conditioned flow | 同步RF guide/OA与轴向调理已知 |
| [`US9129790B2`](https://patents.google.com/patent/US9129790B2/en), *OA-TOF with ion guide mode* | 2013-03-14；active | OA区交替RF guide/DC extraction、delayed extraction利用初始位置—速度相关、有限分布和多电极电压 | Paper 2的RF-to-OA时序/场切换需拓扑级FTO |
| [`US11211238B2 / US20200365383A1`](https://patents.google.com/patent/US20200365383A1/en), *Multi-pass mass spectrometer* | 2017-08-06附近；active | OA内spatial-temporal correlation；上游RF/electrostatic通道脉冲加速、时变能量、Z依赖减速及二阶Z-focusing | A1/A2宽泛主动匹配和联合设计高度重合 |
| [`US11081332B2 / US20200168447A1`](https://patents.justia.com/patent/20200168447), *Ion guide within pulsed converters* | 2017族；active/granted | elongated OA中的RF/静电约束、脉冲时切场、有限phase-space混合 | OA内部conditioner/guide不是空白区 |
| [`WO2020021255A1 / GB2588292B`](https://patents.google.com/patent/WO2020021255A1), *Ion transfer interface for TOF MS* | 2018-07-27；PCT/国家阶段状态需法律核查 | emittance决定时间—能量spread平衡和TAT下限；碰撞阻尼、protruding RF guide、periodic lens保持小相空间到OA | source/interface—analyzer性能匹配是明确既有目标 |
| [`US11527398B2 / WO2020044003A1`](https://patents.google.com/patent/US11527398B2/en), *Pulsed accelerator for TOF* | 2018-08-30；active，显示至2039 | upstream conditioner控制轴向/横向速度spread比，beam expander/RF guide与倾斜OA共同降低turn-around | “由测得spread决定conditioner+OA参数”已有具体权利要求 |
| [`US8674292B2`相关族](https://patents.justia.com/patent/20120145889), *Simultaneous space and velocity focusing* | 2010-12-14；授权族 | 两场加速器、独立脉冲加速器、reflectron以及一/二阶space/velocity simultaneous focusing | 多场、脉冲、reflectron的联合高阶聚焦是已知组合 |

专利预审结论：Paper 1的数学诊断可能仍有科学发表空间，但并不自动产生可专利主题；Paper 2只有在
选定具体conditioner后，围绕独立权利要求逐元件制表、同族/continuation核查和法域状态核查，才能讨论
patentability或FTO。

## 6. Claim-by-claim碰撞判定

| Claim | 本轮判定 | 最近碰撞 | 可保留的窄边界 |
|---|---|---|---|
| J1 条件均值流形/有限条件厚度 | `ORANGE_OVERLAP` | Stein 1974/1994；1996 SVCF；2005 thesis；2006 OA nonlinear/finite spread | 共同pre-pulse经验RF源上的detector-blind条件统计、完整source-to-detector归因和与J2联立的验证框架；不作独立首创claim |
| J2 受约束source-whitened focusability projector | `YELLOW_CANDIDATE / STRONGEST` | 数学构件来自标准加权最小二乘、null-space、projector/SVD；本轮未发现OA-TOF同构组合 | 只主张其在完整OA-reflectron、实测源和工程约束下对direct-particle residual floor的定量预测，不主张数学工具发明 |
| J3 新控制方向与未解残差的重叠 | `YELLOW_CANDIDATE / HIGH_OBVIOUSNESS_RISK` | multi-field/high-order设计、2010负结果、2016 N-geometry和一般controllability | 预注册的source-weighted incremental criterion能在不同源工况事前预测“新增场区有用/无用” |
| J4 source-weighted优于unweighted closure | `ORANGE_OVERLAP` | 1996按相关分布优化、2015 all-essential-ion综合计算、2024 numerical focus search | 只能作为J2/J3预测的实验性结果；目标函数替换本身不是贡献 |
| J5 选择改分析器还是改源 | `ORANGE_OVERLAP` | RF guide/conditioner专利、2010速度spread主导、SCIEX/Waters工程路线 | 只能保留为被盲验证的、工况条件化的triage结果；一般权衡不是新原则 |
| A1 active conditioner | `RED_KNOWN_AS_BROAD_CLAIM / INTERNAL_IP_IF_SPECIFIC` | RF/DC ion guide、beam expander、periodic lens、spatial-temporal correlation等专利族 | 仅具体未披露拓扑、波形或控制律可能进入内部IP审查 |
| A2 conditioner—OA—reflectron联合设计 | `ORANGE_OVERLAP` | 多个active专利已联合源接口、OA和analyzer | 科学贡献必须是充分重优化后仍出现的新Pareto前沿及可解释机制，不能只把模块放进同一optimizer |
| A3 实验性移动分析前沿 | `YELLOW_CANDIDATE` | 产业资料已有高分辨/高接受度主张 | 只有同平台、同输入、同采集约束的prototype A/B和预定义分析终点可升级 |

## 7. JASMS的新颖性与投稿条件

### 7.1 当前仍可成立的中心贡献

建议把中心贡献冻结为：

> 对共同pre-pulse实测源建立条件统计，将完整OA—dual-stage-reflectron的时间灵敏度映射到保持既有
> 聚焦和工程约束后的可行控制子空间，并检验该source-conditioned投影能否在锁定粒子集上定量预测
> residual floor及新增控制方向的实际收益。

这不是“首次考虑相空间”，也不是“首次发现随机厚度不可聚焦”。它是一个受限、可证伪的预测方法。

### 7.2 当前不具备投稿条件的原因

- 2005 thesis、2015与2026核心全文/SI尚未逐式关闭；
- J2尚未实现，J3尚无事前预测；
- 只有N=100、单工况、post-hoc历史归因；
- two-zone/three-zone/source-weighted/unweighted尚未在相同预算下充分重优化；
- 没有两种独立源工况、locked N≥1000、三质量、三维独立路径、尾部/传输/不确定度闭环；
- 当前无法排除projector只是局部线性重述、不能预测有限粒子峰形。

### 7.3 何时因重复或证据失败而停止当前Paper 1

满足任一项就停止当前claim并重构或改投：

1. 关键全文出现与J2相同的source covariance whitening、constraint-nullspace投影和架构增量判据；
2. projector在training上闭合但不能在至少两种locked source condition预测direct-particle收益/无收益；
3. `a_perp`或预测floor对单位、rank tolerance、条件模型或局部步长不稳健；
4. 充分重优化后J2/J3相对标准finite-distribution optimization没有新增解释力或预测力；
5. 结论只能在单一私有几何、单质量或异常高`R`点成立；
6. 性能改善来自粒子损失、共同命中交集或不同优化预算。

## 8. 下一步顺序

当前不应先启动大规模3D campaign。顺序应为：

1. **关闭剩余全文。** 人工取得2005 thesis、2015正文、2026正文/SI和1989正文，完成逐式claim chart；
2. **冻结claim。** J2为唯一主方法claim，J3为主要物理检验，J1为框架，J4/J5为后果；冻结禁止措辞；
3. **最小solver-free杀伤试验。** 复用冻结observed source，实现条件模型、`g`、约束null space、
   projector/QP和bootstrap；对已有two/three-zone小扰动预注册收益排序；
4. **两工况小型blind验证。** 用未参与建模/优化的粒子ID检查预测方向、floor和active constraints；
5. **Go/No-go。** 只有步骤4显示稳定预测力，才创建正式Paper 1 campaign并进入公平重优化、多质量和3D；
6. **Paper 2保持Gate A。** 在J2/J3闭合和具体conditioner完成专业IP/FTO前，不披露拓扑、不采购、
   不启动联合大规模优化。

这一顺序允许理论和模拟继续补充，同时避免在核心claim可能被全文或最小盲测否决前投入昂贵计算。

## 9. 本轮代表性检索式

本轮组合使用标题、DOI、引文和以下概念组；结果用于发现，不是可复现的法律数据库检索式：

```text
"space velocity correlation" TOF / orthogonal acceleration
"correlated phase space distributions" cited by
nonlinear distribution finite arrival time spread orthogonal TOF
multi-field higher-order space focusing initial velocity dispersion
"focusability" orthogonal acceleration TOF
"control subspace" time-of-flight mass spectrometer source covariance
"source-weighted" focusing time-of-flight covariance
RF ion guide beam conditioning orthogonal TOF phase space
spatial-temporal correlation orthogonal accelerator patent
simultaneous space velocity focusing reflectron patent
```

对`focusability + OA-TOF`、`source covariance + feasible control subspace + TOF`、`source-weighted
projector + mass spectrometry`的定向检索未返回同构方法；该负结果只支持继续验证J2/J3，不支持强新颖性
措辞。

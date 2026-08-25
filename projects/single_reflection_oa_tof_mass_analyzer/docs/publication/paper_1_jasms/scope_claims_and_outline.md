# Paper 1：JASMS范围、候选主张与文章结构

> `TARGET: JOURNAL_OF_THE_AMERICAN_SOCIETY_FOR_MASS_SPECTROMETRY`
>
> `STATUS: CONCEPT_DEFINED / EVIDENCE_INCOMPLETE`

## 1. 目标和定位

建议题目：

> **Source-Conditioned Control-Subspace Analysis of an Orthogonal-Acceleration Time-of-Flight Mass Spectrometer**

备选：

> **Predicting the Incremental Value of Analyzer Controls for Finite Phase-Space Sources in Orthogonal-Acceleration TOF Mass Spectrometry**

JASMS当前scope包括质谱基础理论、仪器原理、设计、演示、建模和新算法：
<https://researcher-resources.acs.org/publish/author_guidelines?coden=jamsef>。理论论文不被形式上要求必须有
完整样机，但本稿若没有跨源工况、三维真实场和独立验证，就不足以证明对质谱领域具有普适物理意义。

## 2. 独立科学问题

真实RF多极杆输出不是无厚度的单值`z-v_z`曲线。Paper 1回答：

1. 沿条件均值流形的局部高阶closure实际消除了什么？
2. 有限条件厚度通过哪些source-to-detector时间模态产生残差峰宽？
3. 保持已有聚焦和工程约束后，分析器还能控制多少残差？
4. 新增场区是否提供真正独立、与未解决残差重叠的控制方向？
5. 何时应继续优化分析器，何时必须改变源条件分布？

## 3. 候选主张

候选claim及风险状态只以
[`prior_art_claim_registry.md`](../prior_art_claim_registry.md)为准；2026-08-25检索证据见
[`prior_art_search_audit_20260825.md`](../prior_art_search_audit_20260825.md)，四份本地全文逐式核对见
[`prior_art_equation_claim_chart_20260825.md`](../prior_art_equation_claim_chart_20260825.md)。定向查重已确认J1不能独立
承担首创新颖性，J4/J5只能作为后果。稿件拟集中在三个层级：

### 3.1 物理分解

区分：

$$
J_\mu^T\mathbf g=0
$$

描述的切向closure，与

$$
J_\perp=\mathbf g^T\Sigma_\varepsilon\mathbf g
$$

描述的有限条件厚度时间投影。该分解是定义和归因框架，不作为独立新颖性主张；其作用是给J2/J3提供
共同pre-pulse真实源、完整OA—drift—dual-stage-reflectron和三维detector event中的可计算输入。

### 3.2 架构条件化可聚焦性

在保持低阶与工程约束后，以source-whitened可行控制子空间预测局部一阶残差参考下界、有效rank和
新增方向收益。这是Paper 1当前唯一候选主方法claim；必须限定为source、架构、工作点、约束和线性
信赖域条件化的结果，并由locked direct-particle运行证明预测力。

### 3.3 可证伪的设计决策

通过至少两种source condition验证：focusability、未解残差与新增控制方向重叠能否事前预测新增场区
的收益或无收益。由此得到的“继续优化分析器、做source-weighted重优化或改变source distribution”只
作为工况条件化的结果，不写成普遍新设计原则。

### 3.4 已有J3理论证据的严格边界

三区最初的理论动机不是任意增加电极数，而是：两区在`D1/D2`闭合后没有余下局部控制自由度；当轴向束宽从
约1 mm增至2.2 mm，有限束宽的高阶时间项主导，单靠低阶两区重匹配不能维持窄峰。冻结一维T5验收显示，
第三区提供的`Γ3`独立方向可显著降低该2.2 mm有限束宽的时间展宽。它支持“存在待验证的高阶控制机制”，
不是对真实RF源、三维真实场、传输率或普适工程优势的结论。

当前C2的负/不确定结果检验的是另一件事：在S1/S2的条件源协方差下，source-whitened J2是否一致优于未加权
目标。两者不得互相替代或互相否定；前者仍需真实场验证，后者尚未取得跨源GO。

## 4. 不能作为创新的内容

- OA + reflectron架构；
- dual-stage reflectron；
- `z-v_z`线性或非线性相关；
- coupled space/velocity focusing；
- 三区或更多场区；
- `D1/D2/D3=0`；
- Jacobian、`Γ3`、rank、PCA、projector或SVD本身；
- 使用SIMION、COMSOL或达到一个很高的单点`R`。

这些只作为背景、精确oracle、比较架构或验证工具。

## 5. 文章结构

### 5.1 Introduction

1. OA-TOF峰宽受完整源相空间而非独立标量宽度控制；
2. 已有space–velocity correlation和coupled focusing的贡献；
3. 真实RF源的条件厚度、异方差和尾部；
4. 局部高阶closure与有限分布最优之间的缺口；
5. 本文的可证伪问题、方法和证据范围。

### 5.2 Theory

- pulse-relative时钟和共同pre-pulse源；
- 多维条件流形与厚度；
- total variance和高阶适用边界；
- N-zone OA、dual-stage reflectron与统一参考面；
- 受约束focusability、残差模态和新增控制方向；
- 有限孔径和传输边界。

### 5.3 Methods

- source authority、cohort split和detector-blind模型选择；
- analytic/AD/finite-difference导数交叉校核；
- two-zone、three-zone、unweighted和source-weighted公平优化；
- ideal、轴线场、3D SIMION和独立COMSOL/实现；
- 峰提取、bootstrap、损失census和盲化test。

### 5.4 Results

1. exact oracle与三维导数一致性；
2. affine薄源的局部closure；
3. observed条件厚度、异方差和残差模态；
4. predicted variance/floor与direct-particle结果；
5. 充分重优化的架构比较；
6. 多质量和多source condition稳健性；
7. 新增场区何时有用、何时无用；
8. 分析器优化与source conditioning的决策图。

### 5.5 Discussion

- 与1974/1994/1996/2005/2006/2010/2015/2016/2017/2024/2026工作的明确差异；
- 局部projector和协方差近似的边界；
- 非高斯、孔径、脉冲、空间电荷和实验源推断限制；
- 对oa-TOF源接口和分析器设计的可推广启示。

### 5.6 Conclusions

结论应落在受约束、source-conditioned的设计判据，而不是最高分辨率纪录：

> High-order closure along a source manifold is effective only to the extent that the remaining conditional source modes have weak timing projection or lie within the feasible control subspace of the complete analyzer.

## 6. 不提前公开的Paper 2资产

- 最终conditioner结构、电压和波形；
- 自动匹配/调谐实现；
- prototype resolution—transmission Pareto；
- sensitivity、duty cycle和dynamic range；
- 真实分析样品；
- 产品CAD、公差补偿和校准数据库。

Discussion可以指出主动source matching是后续方向，但不能展示最终解决方案或主要性能。

## 7. 投稿go/no-go

只有同时满足以下条件才进入JASMS稿件冻结：

1. 剩余关键正文/SI、扩展引用链与专利预审未发现与J2/J3核心组合等价的先行工作；
2. 条件残差不是只用一个N=100事后诊断支持；
3. projector/mode结论在独立source condition和locked test上有预测力；
4. two-zone、three-zone和source-weighted方案完成相同预算下的充分重优化；
5. 至少三个质量点、真实三维场和独立求解路径支持主结论；
6. 直接FWHM、尾部、传输和不确定度一致支持结论；
7. 主要结论不依赖单一私有几何或单个极高`R`点；
8. 稿件未泄露Paper 2的IP和主要实验资产。

未满足时的动作是补证、缩小claim或重新选择期刊，不把`YELLOW_CANDIDATE`写成已验证创新。

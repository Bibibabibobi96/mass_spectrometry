# OA-TOF 核心全文逐式 claim chart 与理论审计（2026-08-25）

> `STATUS: FOUR_LOCAL_MAIN_TEXTS_EQUATION_REVIEWED / SUPPLEMENTS_AND_REMAINING_CORE_TEXTS_OPEN`
>
> `SCOPE: SCIENTIFIC_NOVELTY_AND_FORMULA_AUDIT / NOT_LEGAL_ADVICE`

本文记录四份人工保存全文的逐式核对、仓库理论回查和对两篇论文新颖性的影响。它补充
[`prior_art_search_audit_20260825.md`](prior_art_search_audit_20260825.md)，不替代专业专利 FTO、
领域专家复核或投稿证据。为避免把第三方 PDF 或本机目录纳入版本库，本文只保存书目信息、文件名、
SHA-256 和审计结论，不保存 PDF 副本或绝对路径。

## 1. 审查语料与边界

| 本地文件 | 书目信息 | 页数 | SHA-256 | 本轮覆盖 |
|---|---|---:|---|---|
| `423073.pdf` | Papanastasiou, *Space Velocity Correlation in Orthogonal Time-of-Flight Mass Spectrometry*, PhD thesis, 2005, DOI [`10.83056/mmu.32482788`](https://doi.org/10.83056/mmu.32482788) | 280 | `B85F76B05093EB12F186EC48AECF201685D199D690F26C8724FB0B1AFC253D71` | 与 TOF 聚焦直接相关的第 2–4 章、附录 I–II；公式页逐页渲染核对 |
| `cai2015 Coupled Space- and Velocity-Focusing in Time-of-Flight Mass Spectrometry—a Comprehensive Theoretical Investigation.pdf` | Cai, Lai & Wang, JASMS 2015, DOI [`10.1007/s13361-015-1206-y`](https://doi.org/10.1007/s13361-015-1206-y) | 10 | `966933D5B1000537D12015DAE340F022512CA257286A71F072B3DC2F10749A58` | 全文、全部编号公式和图表定义 |
| `Models for mass-independent space and energy focusing in time-of-flight mass spectrometry.pdf` | Yefchak, Enke & Holland, IJMSIP 1989, DOI [`10.1016/0168-1176(89)80031-X`](https://doi.org/10.1016/0168-1176(89)80031-X) | 18 | `6B1AAEACC99C2BE2AEA9B8B3982F2434938CFA0BBA35B35919F71230A207AEE2` | 全文、式 (1)–(37)、表 1 横排公式和模拟指标 |
| `Theoretical Study of High-Order Velocity Focusing Achieved with Single-Stage Reflectron Time-of-Flight Mass Spectrometry.pdf` | Cai & Wang, JASMS 2026, DOI [`10.1021/jasms.5c00167`](https://doi.org/10.1021/jasms.5c00167) | 9 | `5D411B26BF03D071EBE6AE8BDC4590784D922E3CBAFC3C92A2C813A5A9967E9C` | 全文、全部编号公式和图表定义 |

学位论文第 5–7 章的装置实现、电子发射和应用数据不属于本轮“理论逐式”范围；两篇期刊论文的
Supporting Information 不在本地目录，仍是开放项。以下状态码统一为：

| 状态 | 含义 |
|---|---|
| `FOUNDATIONAL` | 标准力学、误差传播或经典 TOF 公式，不构成候选新颖性 |
| `PRIOR_ART` | 直接覆盖当前宽泛 claim，必须作为先行工作 |
| `CONSISTENT` | 与仓库对应解析式和定义一致 |
| `SOURCE_ERROR` | 原文存在量纲、代数、编号或定义错误；不得照抄 |
| `REPO_GAP_CLOSED` | 原仓库缺少或弱化的边界，本轮已补入统一理论 |
| `TERMINOLOGY_BOUNDARY` | 源文献的术语定义不能直接等同仓库标准定义 |
| `MODEL_LIMIT / BRANCH_OMISSION / SIGN_CONVENTION_OPEN` | 公式只在附加近似下成立、漏掉物理分支，或有符号合同不足以无歧义复现 |

## 2. Cai、Lai 与 Wang 2015：逐式 claim chart

| 式 | 原文功能/主张 | 仓库映射 | 审计结论与 claim 影响 |
|---|---|---|---|
| (1) | 以 $\partial t/\partial s=0$ 定义一阶空间聚焦 | `oaaccelerator_time_focus.md` | `FOUNDATIONAL / CONSISTENT`；不能作为新意 |
| (2) | 用平移一维高斯表示初速度分布，并把 $\sqrt{3kT/m}$ 称为 average speed | 条件源分布 | `SOURCE_ERROR`：该量是三维 RMS speed，不是 Maxwell speed 的均值；平移一维高斯是模型假设，不是精确 Maxwell 速率分布 |
| (3) | 均匀提取场中的第一段飞行时间 | `oaaccelerator_time_focus.md` | `FOUNDATIONAL / CONSISTENT` |
| (4) | 第二加速区飞行时间 | 同上 | `FOUNDATIONAL / CONSISTENT` |
| (5) | 无场漂移时间 | 同上 | `SOURCE_ERROR`：印刷式缺少漂移长度 $D$，量纲为时间/长度；正确结构必须含 $D/\sqrt W$ |
| (6) | 源区、加速区和漂移区总飞行时间 | 同上 | `SOURCE_ERROR`：继承式 (5) 缺失的 $D$；数值计算显然使用了文中冻结的漂移长度，印刷式不能直接复用 |
| (7) | 对位置和速度扰动展开到混合项 | `source_to_detector_phase_space_framework.md` §5 | `SOURCE_ERROR`：混合二阶项印为 $(\partial t/\partial s)(\partial t/\partial v)\Delta s\Delta v$，应为混合偏导 $\partial^2t/(\partial s\partial v)$；原式量纲不成立 |
| (8) | 空间端点时间差的高阶展开 | 同上 | `SOURCE_ERROR / TERMINOLOGY_BOUNDARY`：沿用错误混合项，且所谓 full expression 并非完整多元 Taylor，遗漏其他同阶混合项 |
| (9) | 把空间—速度关联代入到达时间差 | 条件均值流形特例 | `PRIOR_ART / SOURCE_ERROR`：宽泛 coupled focusing 已知；混合项仍错误，首个时间差比值还缺绝对值；文中 $s_2-s_1=\tau v_0$ 只在额外端点假设下成立，通常应为 $-\tau\Delta v$ |
| (10) | 保留选定低阶项进行联合优化 | 局部截断模型 | `PRIOR_ART / CONSISTENT_AS_APPROXIMATION`：是选择性截断而非完整公式；all-ion、有限区间和延迟联合优化直接压缩 J4 的新颖性空间 |

该文的数值“分辨率”以选定速度区间内的 $\Delta t_{\max}$ 或时间包络构造，而不是对带概率权重的
arrival-time density 直接测 FWHM；探测器和电子学响应也未纳入。因此其数值可以比较其自身设计，
但不能直接等同仓库的 canonical direct FWHM。

## 3. Yefchak、Enke 与 Holland 1989：逐式 claim chart

该文提出 dynamic-field focusing（DFF）：先在第一无场区形成质量相关到达时序，再用同步时变的短
后源加速区对每个 isomass packet 施加不同速度修正，最后在第二无场区追赶聚焦。它不是 oa-TOF，
但已公开“到达时刻编码质量—动态波形—空间/能量联合聚焦—几何与波形联合优化”的完整路线。

| 式 | 原文功能/主张 | 仓库映射 | 审计结论与 claim 影响 |
|---|---|---|---|
| (1) | 用 $\alpha=(s_0+\delta s)/s_0$ 表示源位置扰动 | 条件源坐标 | `FOUNDATIONAL / CONSISTENT` |
| (2) | 用 $\beta=\delta U/U_s$ 表示初始动能扰动 | 条件源坐标 | `FOUNDATIONAL / CONSISTENT`；$\beta$按定义是非负能量比，不能同时编码速度方向 |
| (3) | 两粒子在第二无场区末端同时到达的 pairwise 条件 | 有限端点 isochrony | `PRIOR_ART / CONSISTENT`；不是局部导数阶 |
| (4) | 参考粒子穿过动态区后的能量 | 时变薄隙 kick | `PRIOR_ART / CONSISTENT_WITH_THIN_GAP` |
| (5) | 领先粒子在更早时刻穿过动态区后的能量 | 同上 | `PRIOR_ART / CONSISTENT_WITH_THIN_GAP` |
| (6) | 在单个质量包通过期间把波形局部线性化为 $V(t)=V_0-k\Delta t$ | 时变控制局部模型 | `PRIOR_ART`；动态波形的局部斜率设计已知 |
| (7) | 由目标末能量反解局部波形斜率 $k$ | 时变控制反解 | `PRIOR_ART / CONSISTENT` |
| (8) | 由第二无场区等时条件反解领先粒子的目标末能量 | pairwise 控制目标 | `PRIOR_ART / CONSISTENT` |
| (9) | 把斜率写成 $k=F(V_0,m)$ | 到达时刻条件化控制 | `PRIOR_ART`；只有在扰动参数和几何已冻结/平均后才成立 |
| (10) | 以 $dV/dt=F(V(t),m)$ 构造质量相关波形 ODE | 非自治 source-to-detector 映射 | `PRIOR_ART` |
| (11) | 用到达动态区的时刻替换质量，得到 $dV/dt=F'(V(t),t)$ | 时间编码质量 | `PRIOR_ART`；直接压缩 Paper 2“同步主动匹配”的宽泛空间 |
| (12) | 数值积分得到波形族 $V(t)=G(V(0),t)$ | 动态控制律 | `PRIOR_ART` |
| (13) | 空间扰动粒子的源出口能量 $U_{1S}=\alpha U_s$ | 单场源运动学 | `FOUNDATIONAL / CONSISTENT` |
| (14) | 朝向探测器初速度分支的出口能量 | 单场源运动学 | `FOUNDATIONAL / CONSISTENT` |
| (15) | 反向初速度分支完成 turn-around 后的出口能量 | 单场源运动学 | `FOUNDATIONAL / CONSISTENT` |
| (16) | 空间扰动粒子相对参考粒子的 DFF 到达提前量 | 有限端点时间差 | `PRIOR_ART / CONSISTENT` |
| (17) | 正向初速度分支的到达提前量 | 有限端点时间差 | `PRIOR_ART / CONSISTENT` |
| (18) | 反向初速度/turn-around 分支的到达提前量 | 有限端点时间差 | `PRIOR_ART / CONSISTENT` |
| (19) | 把 (13)、(16) 代入 (7)–(8) 得到空间分支 $k_S$ | 动态空间聚焦控制 | `PRIOR_ART`；表 1 横排公式量纲一致 |
| (20) | 正向初速度分支 $k_{E+}$ | 动态能量聚焦控制 | `PRIOR_ART` |
| (21) | 反向初速度分支 $k_{E-}$ | 动态 turn-around 补偿 | `PRIOR_ART`；主动补偿反向初速度并非新问题 |
| (22) | 跨 $\delta s,\delta U,V_0,m$ 网格累加相对峰间隔误差的 simplex 目标 | finite-distribution 优化 | `PRIOR_ART / TERMINOLOGY_BOUNDARY`：这是离散、等权的误差目标，不是文中所称的 resolving power 本身 |
| (23) | $k_S=F_1(V_0,m,\alpha)$ | case-wise 控制映射 | `PRIOR_ART` |
| (24) | $k_{E+}=F_2(V_0,m,\beta)$ | case-wise 控制映射 | `PRIOR_ART` |
| (25) | $k_{E-}=F_3(V_0,m,\beta)$ | case-wise 控制映射 | `PRIOR_ART` |
| (26) | 对九个选定扰动点的三个 $F_i$ 等权平均 | 源分布加权的早期近似 | `PRIOR_ART / MODEL_LIMIT`：权重是人为等权采样，不是经验联合分布或协方差；组合扰动可聚焦性只由假设推出 |
| (27) | 源、FF1、有限 DFF 区和 FF2 的总时间 | 完整分段时间映射 | `PRIOR_ART / CONSISTENT` |
| (28) | 单场源内飞行时间 | 初速度源时间 | `SOURCE_ERROR / BRANCH_OMISSION`：按非负 $\beta$ 定义，印刷式分母只对应朝向探测器分支；反向分支需要有符号初速度或相反号，不能由该式自动包含 turn-around |
| (29) | 第一无场区飞行时间 | 漂移 oracle | `FOUNDATIONAL / CONSISTENT` |
| (30) | 线性变化电压下有限 DFF 区的三次轨迹 | 时变有限区传播 | `PRIOR_ART / SIGN_CONVENTION_OPEN`：结构合理，但正文的负电压、$q/e$与系数符号未形成自足一致的有符号合同 |
| (31) | 三次项系数 $p_3$ | 同上 | `PRIOR_ART / SIGN_CONVENTION_OPEN` |
| (32) | 二次项系数 $p_2$ | 同上 | `PRIOR_ART / SIGN_CONVENTION_OPEN` |
| (33) | 一次项系数 $p_1$ | 同上 | `PRIOR_ART / SIGN_CONVENTION_OPEN` |
| (34) | 常数项 $p_0$ | 同上 | `PRIOR_ART / SIGN_CONVENTION_OPEN` |
| (35) | 令 $x=l$ 后求有限动态区渡越时间的三次方程 | 时变区事件根 | `PRIOR_ART / CONSISTENT`；不能用零长度 kick 代替而不做渡越时间检查 |
| (36) | 动态区出口速度 | 时变区事件速度 | `PRIOR_ART / CONSISTENT` |
| (37) | 第二无场区飞行时间 | 漂移 oracle | `FOUNDATIONAL / CONSISTENT` |

该文还有三项对当前计划重要的先行工作：一是明确比较路径、延迟、速度和持续加速度四类后源控制；
二是联合优化提取能量、两个漂移长度和动态波形；三是用 Monte Carlo arrival histogram、直接 FWHM
和相邻质量峰谷而非仅用端点 envelope 评价。其主要模型限制是：先分别处理 S/E+/E− 三种单扰动，
再**假设**同时聚焦三种代表分支会聚焦任意组合；没有经验联合分布、条件协方差、横向/孔径、场穿透、
波形抖动或独立盲测。正文也承认有限动态区的栅格场穿透未详细研究。

## 4. Cai 与 Wang 2026：逐式 claim chart

| 式 | 原文功能/主张 | 仓库映射 | 审计结论与 claim 影响 |
|---|---|---|---|
| (1) | 源区、漂移、单级反射镜和返回漂移的完整一维时间 | `oaaccelerator_time_focus.md` + `dual_stage_reflectron.md` 的单级特例 | `PRIOR_ART / CONSISTENT`；但正文定义 $U_s=q s_iV_s$ 量纲错误，应为 $q s_iE_s$，其中 $E_s=V_s/s_0$ |
| (2) | 用 $t(v_2,\tau)-t(v_0,\tau)\approx0$ 使速度区间两个端点等时 | 有限端点 isochrony | `PRIOR_ART / TERMINOLOGY_BOUNDARY`：这是端点约束，不等于 $\partial t/\partial v=0$ 或 $\partial^2t/\partial v^2=0$ 的局部导数 closure |

该文把 $t(v)$ 出现两个转折点称为 second-order focusing，并明确允许
$\partial^2t/\partial v^2\ne0$。这是一种有限区间拓扑/操作性分类，不是本仓库采用的标准局部导数阶。
其 $R_m=t_c/(2\Delta t_{\max})$ 同样来自速度区间的最大—最小时间包络，不是概率峰 FWHM。理想模型
还假设一维均匀场、无网格场畸变、确定性的 MALDI 速度—延迟关系和按每个 $m/z$ 重新优化；这些边界
不能外推到连续 RF 源的有限条件厚度。

## 5. Papanastasiou 2005 thesis：相关公式逐式 claim chart

以下逐式表覆盖本论文问题直接使用的第 2–4 章和附录 I–II。描述只标注公式功能和碰撞，不复制长式。

### 5.1 第 2 章：空间聚焦、有限源与焦区

| 式 | 功能 | 状态/仓库映射 |
|---|---|---|
| (2.1.1) | 把多个峰宽贡献作平方和 | `FOUNDATIONAL`；仅在贡献独立且宽度定义相容时成立，相关源应使用完整协方差 |
| (2.2.1) | 一般 Taylor 展开 | `FOUNDATIONAL / CONSISTENT` |
| (2.2.2) | 截断到二阶 | `FOUNDATIONAL / CONSISTENT` |
| (2.2.3) | Taylor 余项/截断误差 | `FOUNDATIONAL / CONSISTENT` |
| (2.3.1) | 第一均匀场飞行时间 | `FOUNDATIONAL / CONSISTENT` |
| (2.3.2) | 第二均匀场飞行时间 | `FOUNDATIONAL / CONSISTENT` |
| (2.3.3) | 无场漂移时间 | `FOUNDATIONAL / CONSISTENT` |
| (2.3.4) | 静止释放的双场总时间 | `PRIOR_ART`；对应双区 oracle |
| (2.3.5) | 一阶空间焦距 | `PRIOR_ART / CONSISTENT` |
| (2.3.6) | 场比参数化 | `FOUNDATIONAL` |
| (2.3.7) | 围绕源中心展开总时间 | `FOUNDATIONAL` |
| (2.3.8) | 一阶闭合后的高阶残差 | `PRIOR_ART`；高阶残差不是本项目首创 |
| (2.3.9) | 二阶空间聚焦的漂移长度 | `PRIOR_ART` |
| (2.3.10) | 无量纲一阶聚焦关系 | `PRIOR_ART` |
| (2.3.11) | 无量纲二阶聚焦关系 | `PRIOR_ART` |
| (2.3.12) | 单场加速时间的能量形式 | `FOUNDATIONAL` |
| (2.3.13) | 单场漂移时间的能量形式 | `FOUNDATIONAL` |
| (2.3.14) | 加速时间对能量的一阶导数 | `FOUNDATIONAL` |
| (2.3.15) | 漂移时间对能量的一阶导数 | `FOUNDATIONAL` |
| (2.3.16) | 双场第一段能量时间 | `FOUNDATIONAL` |
| (2.3.17) | 双场第二段能量时间 | `FOUNDATIONAL` |
| (2.3.18) | 双场漂移时间 | `FOUNDATIONAL` |
| (2.3.19) | 第一段能量导数 | `FOUNDATIONAL` |
| (2.3.20) | 第二段能量导数 | `FOUNDATIONAL` |
| (2.3.21) | 漂移段能量导数 | `FOUNDATIONAL` |
| (2.3.22) | 双场能量域的一阶焦距 | `PRIOR_ART`；整机能量 closure 不是新概念 |
| (2.4.1) | 均匀加速轨迹 | `FOUNDATIONAL` |
| (2.4.2) | 到达场区边界时间 | `FOUNDATIONAL` |
| (2.4.3) | 场区出口速度 | `FOUNDATIONAL` |
| (2.4.4) | 漂移时间 | `FOUNDATIONAL` |
| (2.4.5) | 漂移轨迹 | `FOUNDATIONAL` |
| (2.4.6) | 两个源端点的轨迹 | `PRIOR_ART`；finite ion-pair construction |
| (2.4.7) | 两轨迹交点的时间/位置 | `PRIOR_ART` |
| (2.4.8) | 单场 pairwise 焦距 | `PRIOR_ART` |
| (2.4.9) | 有限源区的端点到达时间差 | `PRIOR_ART` |
| (2.4.10) | 端点时间差对源位置导数 | `PRIOR_ART` |
| (2.4.11) | 第一段有限源宽分段表达式 | `PRIOR_ART` |
| (2.4.12) | 第二段有限源宽分段表达式 | `PRIOR_ART` |
| (2.4.13) | 第三段有限源宽分段表达式 | `PRIOR_ART` |
| (2.4.14) | 第四段有限源宽分段表达式 | `PRIOR_ART` |
| (2.4.15) | 完整 piecewise finite-source width | `PRIOR_ART / REPO_GAP_CLOSED`；有限源形成焦区而非单一面 |
| (2.4.16) | 第二场区中的轨迹 | `FOUNDATIONAL` |
| (2.4.17) | 进入第二场的时间 | `FOUNDATIONAL` |
| (2.4.18) | 第二场出口速度 | `FOUNDATIONAL` |
| (2.4.19) | 第二场后的漂移轨迹 | `FOUNDATIONAL` |
| (2.4.20) | 两粒子双场轨迹 | `PRIOR_ART` |
| (2.4.21) | 通用 pairwise 焦距 | `PRIOR_ART` |
| (2.4.22) | 双场 pairwise 焦距闭式 | `PRIOR_ART` |

### 5.2 第 3 章：delayed extraction 与位置—速度耦合

| 式 | 功能 | 状态/仓库映射 |
|---|---|---|
| (3.1.1) | 延迟后单场出口速度 | `FOUNDATIONAL` |
| (3.1.2) | 延迟后提取时间 | `FOUNDATIONAL` |
| (3.1.3) | 延迟后漂移时间 | `FOUNDATIONAL` |
| (3.1.4) | 总时间对延迟后位置的一阶导数 | `PRIOR_ART` |
| (3.1.5) | 相应二阶导数 | `PRIOR_ART` |
| (3.1.6) | delayed-extraction 一阶焦距 | `PRIOR_ART` |
| (3.1.7) | 相关速度假设下的简化焦距 | `PRIOR_ART`；位置—速度相关优化已知 |
| (3.1.8) | 一阶闭合后的二、三阶残差 | `PRIOR_ART` |
| (3.1.9) | 二阶时间导数 | `PRIOR_ART` |
| (3.1.10) | 三阶时间导数/高阶项 | `PRIOR_ART` |
| (3.1.11) | 二阶 delayed-extraction 焦距 | `PRIOR_ART` |
| (3.1.12) | 相关速度下的二阶简式 | `PRIOR_ART` |
| (3.1.13) | 双场第一级出口速度 | `FOUNDATIONAL` |
| (3.1.14) | 双场最终出口速度 | `FOUNDATIONAL` |
| (3.1.15) | 双场第一段时间 | `FOUNDATIONAL` |
| (3.1.16) | 双场第二段时间 | `FOUNDATIONAL` |
| (3.1.17) | 双场漂移时间 | `FOUNDATIONAL` |
| (3.1.18) | 第一段位置导数 | `FOUNDATIONAL` |
| (3.1.19) | 第二段位置导数 | `FOUNDATIONAL` |
| (3.1.20) | 漂移段位置导数 | `FOUNDATIONAL` |
| (3.1.21) | 双场一阶 delayed-extraction 焦距 | `PRIOR_ART` |
| (3.1.22) | 第一段二阶位置导数 | `FOUNDATIONAL` |
| (3.1.23) | 第二段二阶位置导数 | `FOUNDATIONAL` |
| (3.1.24) | 漂移段二阶位置导数 | `FOUNDATIONAL` |
| (3.1.25) | 双场二阶 delayed-extraction 焦距 | `PRIOR_ART` |
| (3.1.26a) | 单场时间对初速度的一阶导数 | `PRIOR_ART`；原文编号与下一式重复 |
| (3.1.26b) | 漂移时间对初速度的一阶导数 | `PRIOR_ART / SOURCE_ERROR`：编号重复，不影响公式功能 |
| (3.1.27) | 沿位置—速度关系的一阶链式导数 | `PRIOR_ART`；对应仓库 affine source-chain 特例 |
| (3.1.28) | 沿相关流形的二阶链式导数 | `PRIOR_ART` |
| (3.1.29) | 能量导数与位置导数关系 | `FOUNDATIONAL` |
| (3.1.30) | 单场端点 1 出口速度 | `FOUNDATIONAL` |
| (3.1.31) | 单场端点 2 出口速度 | `FOUNDATIONAL` |
| (3.1.32) | 端点 1 总时间 | `FOUNDATIONAL` |
| (3.1.33) | 端点 2 总时间 | `FOUNDATIONAL` |
| (3.1.34) | 两有限端点的一般等时焦距 | `PRIOR_ART / REPO_GAP_CLOSED`；端点等时不同于局部导数阶 |
| (3.1.35) | 特定相关关系下的 pairwise 焦距 | `PRIOR_ART` |
| (3.1.36) | 双场端点 1 最终速度 | `FOUNDATIONAL` |
| (3.1.37) | 双场端点 2 最终速度 | `FOUNDATIONAL` |
| (3.1.38) | 端点 1 第二场飞行时间 | `FOUNDATIONAL` |
| (3.1.39) | 端点 2 第二场飞行时间 | `FOUNDATIONAL` |
| (3.1.40) | 端点 1 漂移时间 | `FOUNDATIONAL` |
| (3.1.41) | 端点 2 漂移时间 | `FOUNDATIONAL` |
| (3.1.42) | 双场有限端点等时焦距 | `PRIOR_ART` |

### 5.3 第 4 章：oa-TOF space–velocity correlation focusing

| 式 | 功能 | 状态/仓库映射 |
|---|---|---|
| (4.1.1) | turn-around time | `PRIOR_ART`；oa-TOF 初始速度项已知 |
| (4.2.1) | 正/反向初速度粒子的分段总时间 | `PRIOR_ART` |
| (4.2.2) | 正向粒子总时间 | `PRIOR_ART` |
| (4.2.3) | 正向粒子一级出口速度 | `FOUNDATIONAL` |
| (4.2.4) | 正向粒子二级出口速度 | `FOUNDATIONAL` |
| (4.2.5) | 反向粒子总时间 | `PRIOR_ART` |
| (4.2.6) | 反向粒子一级出口速度 | `FOUNDATIONAL` |
| (4.2.7) | 反向粒子二级出口速度 | `FOUNDATIONAL` |
| (4.2.8) | 正向分支的线性位置—速度关系 | `PRIOR_ART` |
| (4.2.9) | 反向分支的线性位置—速度关系 | `PRIOR_ART` |
| (4.2.10) | 正向分支的有限速度 Taylor 差 | `PRIOR_ART` |
| (4.2.11) | 正向分支的到达时间展宽 | `PRIOR_ART` |
| (4.2.12) | 反向分支的有限速度 Taylor 差 | `PRIOR_ART` |
| (4.2.13) | 反向分支的到达时间展宽 | `PRIOR_ART` |
| (4.2.14) | 两分支总展宽 | `PRIOR_ART` |
| (4.2.15) | 线性相关的一阶 closure | `PRIOR_ART`；J1 宽泛表述被直接覆盖 |
| (4.2.16) | 对应的一阶焦距 | `PRIOR_ART` |
| (4.2.17) | 正向速度比 | `FOUNDATIONAL` |
| (4.2.18) | 正向第二速度比 | `FOUNDATIONAL` |
| (4.2.19) | 反向速度比 | `FOUNDATIONAL` |
| (4.2.20) | 反向第二速度比 | `FOUNDATIONAL` |
| (4.2.21) | 正向有效路径 | `PRIOR_ART` |
| (4.2.22) | 反向有效路径 | `PRIOR_ART` |
| (4.2.23) | 质量无关的一阶 SVCF 焦距 | `PRIOR_ART` |
| (4.2.24) | 两分支合成的二阶 closure | `PRIOR_ART` |
| (4.2.25) | 相应二阶焦距 | `PRIOR_ART` |
| (4.2.26) | 二阶解的速度比参数 | `PRIOR_ART` |

论文关于非线性相关、virtual time delay、有限到达时间展宽和 source-dependent virtual focus 的讨论
进一步表明：线性/非线性 $z-v_z$、有限 spread 与虚拟源不能作为本项目独立新颖性。所谓理想线性相关
下的“infinite-order”或近零展宽，只对零厚度、精确仿射的理想流形成立，不能外推到有限条件协方差。

### 5.4 附录 I：误差与协方差传播

| 式 | 功能 | 状态/仓库映射 |
|---|---|---|
| (I.i) | 多变量全微分 | `FOUNDATIONAL` |
| (I.ii-a) | 一阶误差微分 | `FOUNDATIONAL` |
| (I.ii-b) | Taylor 微分算子 | `SOURCE_ERROR`：与前式重复编号 |
| (I.iv) | 二阶误差展开 | `FOUNDATIONAL` |
| (I.v) | 相关误差的绝对值界 | `FOUNDATIONAL` |
| (I.vi) | 独立误差的平方和 | `FOUNDATIONAL`；只适用于零协方差 |
| (I.vii) | 二变量方差传播 | `SOURCE_ERROR`：交叉项误用 $2f_{xy}\sigma_{xy}$；正确线性项是 $2f_xf_y\operatorname{Cov}(x,y)$ |
| (I.viii) | $x$ 的方差定义 | `FOUNDATIONAL` |
| (I.ix) | 协方差定义 | `FOUNDATIONAL` |
| (I.x) | 到达时间方差对象 | `FOUNDATIONAL` |
| (I.xi) | 源位置方差 | `FOUNDATIONAL` |
| (I.xii) | 源速度方差 | `FOUNDATIONAL` |
| (I.xiii) | 位置—速度协方差 | `FOUNDATIONAL` |
| (I.xiv) | 精确时间误差定义 | `FOUNDATIONAL` |
| (I.xv) | 线性化位置贡献 | `FOUNDATIONAL` |
| (I.xvi) | 线性化速度贡献 | `FOUNDATIONAL` |
| (I.xvii) | 正向分支平方误差 | `SOURCE_ERROR`：平方后的交叉项应为一阶导数乘积，不是混合 Hessian |
| (I.xviii) | 反向分支平方误差 | `SOURCE_ERROR`：同上 |
| (I.xix) | 平均平方误差 | `SOURCE_ERROR`：继承错误交叉项 |
| (I.xx) | 合并两分支矩 | `SOURCE_ERROR`：继承错误交叉项 |
| (I.xxi) | 代入相关源矩 | `SOURCE_ERROR`：继承错误交叉项 |
| (I.xxii) | 简化方差表达式 | `SOURCE_ERROR`：继承错误交叉项 |
| (I.xxiii) | 最终时间方差 | `SOURCE_ERROR`：继承错误交叉项 |
| (I.xxiv) | 最终时间标准差 | `SOURCE_ERROR`：继承错误交叉项 |
| (I.xxv) | 零协方差特例 | `CONSISTENT`；错误交叉项在该特例消失 |

仓库统一式 $\mathbf g^T\Sigma\mathbf g$ 是正确的一阶协方差传播；混合 Hessian 只在二阶映射和
高阶矩中出现。本轮已把分量式和禁止误用写入统一理论。

### 5.5 附录 II：均匀场运动学

| 式 | 功能 | 状态/仓库映射 |
|---|---|---|
| (II.i) | 匀加速速度积分 | `FOUNDATIONAL / CONSISTENT` |
| (II.ii) | 速度—时间关系 | `FOUNDATIONAL / CONSISTENT` |
| (II.iii) | 位置积分 | `FOUNDATIONAL / CONSISTENT` |
| (II.iv) | 位置—时间关系 | `FOUNDATIONAL / CONSISTENT` |
| (II.v) | 到达固定位置的时间根 | `FOUNDATIONAL / CONSISTENT` |
| (II.vi) | 功—能积分 | `FOUNDATIONAL / CONSISTENT` |
| (II.vii) | 电势能差与功 | `FOUNDATIONAL / CONSISTENT` |
| (II.viii) | 力—时间形式 | `FOUNDATIONAL / CONSISTENT` |
| (II.ix) | 力的时间积分 | `FOUNDATIONAL / CONSISTENT` |
| (II.x) | 一次能量积分 | `FOUNDATIONAL / CONSISTENT` |
| (II.xi) | 速度的能量形式 | `FOUNDATIONAL / CONSISTENT` |
| (II.xii) | 速度解 | `FOUNDATIONAL / CONSISTENT` |
| (II.xiii) | $dx/dt$ 代换 | `FOUNDATIONAL / CONSISTENT` |
| (II.xiv) | 时间积分形式 | `FOUNDATIONAL / CONSISTENT` |
| (II.xv) | 一般势能下的飞行时间 | `FOUNDATIONAL / CONSISTENT` |
| (II.xvi) | 均匀场势能积分 | `FOUNDATIONAL / CONSISTENT` |
| (II.xvii) | 均匀场时间积分 | `FOUNDATIONAL / CONSISTENT` |
| (II.xviii) | 代入均匀场后的积分 | `FOUNDATIONAL / CONSISTENT` |
| 未编号中间式 | 变量替换后的根式积分 | `FOUNDATIONAL / CONSISTENT` |
| (II.xxx) | 均匀场飞行时间终式 | `FOUNDATIONAL / CONSISTENT`；原文编号从 xviii 跳到 xxx，是排版编号问题 |

## 6. 仓库理论回查结果

本轮逐项回查统一框架、双区/三区 OA、线性 $z-v_z$、二级 reflectron 和整机一维耦合文档及其实现
入口。结论如下：

| 审计项 | 结论 | 本轮动作 |
|---|---|---|
| 均匀场与漂移时间 | 未发现仓库代数或量纲错误；均含正确场强和漂移距离 | 保持组件 oracle 不变；统一框架新增外部公式量纲门禁 |
| OA—reflectron 参考面和链式导数 | 未发现重复计时或参考面错误 | 不改组件公式 |
| 一至四阶矩传播 | 仓库式正确；优于 thesis 附录 I 的错误交叉项 | 新增正确二变量分量式和 Hessian 边界 |
| “独立状态”措辞 | 原文可能被误读为统计独立 | 改为“非冗余状态”，明确允许协方差 |
| 随机残差可补偿性 | 原文“不能靠改变 $\kappa$ 消除”过于容易被读成分析器完全不可补偿 | 明确区分“不能靠重拟合斜率消失”和“控制子空间可能降低时间投影” |
| 聚焦阶定义 | 原仓库未显式区分导数阶、端点等时、转折点和轨迹交点 | 新增标准定义和禁止混用规则 |
| 有限源最佳探测面 | 原仓库强调有限厚度，但未明确 focal region | 新增有限焦区和冻结分布上的直接峰形评价 |
| 时间包络与 FWHM | 原仓库已有 direct FWHM，但未针对文献的 $\Delta t_{\max}$ 明确隔离 | 新增 envelope 不是概率峰 FWHM 的规则 |
| 时变场与同步波形 | 原统一映射可容纳触发状态，但未明确 non-autonomous 场、质量到达时刻编码和有限动态区条件 | 新增波形时钟、thin-kick失效条件、slew/fringe/jitter和相邻质量包约束 |

因此，本轮没有证据表明仓库 canonical 解析式需要数值更改；发现的是源文献错误、仓库术语边界和
遗漏的有限区间诊断。若未来实现端点等时或转折点搜索，必须另设 metric，不能把它标成 `D2=0`。

## 7. 综合全部已审查文献后的新颖性判定

### 7.1 已被先行工作覆盖的内容

结合此前检索的 Stein 1974/1994、Colby 1996、Papanastasiou & McMahon 2006、Yildirim 2010、
SCIEX 2016、Waters 2017、Kambarova 2024、相关专利族，以及本轮四份全文，可以确认以下内容不能
承担 Paper 1 主新颖性，且 Paper 2 的宽泛主动调理空间进一步收窄：

- 位置—速度相关、线性或非线性 source manifold、virtual source/time delay；
- 有限源、有限到达时间展宽、focal region 和 pairwise isochrony；
- coupled space/velocity focusing、delayed extraction 与 all-ion/full-distribution 优化；
- 单级或多级 reflectron、高阶局部导数、多个转折点或新增场区；
- 用数值优化寻找场长、电压、delay 和高阶聚焦条件；
- 以质量相关到达时刻驱动时变后源加速，对空间、能量和 turn-around 作联合补偿；
- 联合优化源提取能量、漂移长度、动态波形，或按空间/速度展宽大小调整经验权重；
- arrival-time envelope 优化和按 $m/z$ 单独重优化；
- 一般 phase-space、协方差、PCA/SVD、null space、projector 或 controllability 数学。

J1 因此仍只能是组织和归因框架；J4 只是 J2/J3 的次级验证结果；J5 只能是工况条件化的 triage
后果。若稿件只做到“完整时间公式 + 所有离子 + 联合 OA/reflectron 优化 + 多焦点”，会与 2015/2026
路线实质重复，不具备当前 JASMS 计划所需的新颖性。

对 Paper 2，Yefchak 1989 已使“active/time-dependent conditioner”“按质量包同步波形”“空间—能量
联合聚焦”和“源参数—几何—波形联合优化”成为明确先行工作。A1 的功能级 claim 因而维持
`RED_KNOWN`；A2 不能靠把 conditioner、OA 和 reflectron 放入同一 optimizer 成立。只可能保留具体
未披露拓扑/波形/IP，以及相同平台充分重优化后、由 Paper 1 残差模态机制预测并经样机 A/B 验证的
新 Pareto 前沿。

### 7.2 尚未发现直接同构披露的窄边界

在目前所有已审查主文本中，仍未发现以下**完整组合**：

1. 在共同、detector-blind 的 pre-pulse 时刻取得经验 RF 源；
2. 对条件源协方差作冻结尺度的 source whitening；
3. 把完整 OA—dual-stage-reflectron 的时间灵敏度限制到保持低阶聚焦和工程约束的 null space；
4. 用正交残差投影预测 direct-particle timing floor；
5. 在至少两个独立源工况中，事前预测新增分析器控制方向的收益或无收益。

这支持 J2 保持 `YELLOW_CANDIDATE / STRONGEST`，而不是升级为“已证实新颖”。J3 仍为
`YELLOW_CANDIDATE / HIGH_OBVIOUSNESS_RISK`：它和一般可控性、Yefchak 1989 对四类控制的选择及
分布权重建议、多场高阶设计、2010 负结果及 2026 联合优化非常接近，只有跨工况的事前增量预测力
才能形成有意义差异。

### 7.3 当前 go/no-go

当前结论是：`JASMS_PATH_REMAINS / NOT_SUBMISSION_READY / NO_GREEN_CLAIM`。现有工作并未因重复而
整体失去投稿可能性，但只有 J2/J3 的窄组合值得继续。出现以下任一情况，应停止当前主 claim：

- 剩余全文或 SI 披露等价的 source-whitened constraint-nullspace projector 和增量判据；
- J2/J3 相对标准 finite-distribution optimization 没有额外的盲测预测力；
- 预测只在 training、单一源、单质量或单一私有几何成立；
- 改善来自粒子损失、不同母 cohort、不同优化预算或 envelope/FWHM 偷换；
- 结论对尺度、rank tolerance、条件模型或局部信赖域不稳健。

## 8. 仍未关闭的查重与证据任务

1. 取得 2015 和 2026 Supporting Information，特别核对优化目标、补充推导和未正文展示的质量点；
2. 继续取得仍停留在摘要/摘录等级的 closest-work 正文，优先 Stein 1974/1994、Colby 1996和
   Papanastasiou & McMahon 2006；
3. 围绕 J2/J3 做向前/向后引文扩展，并由独立领域专家检查等价术语；
4. 对 Paper 2 的具体 conditioner 拓扑逐独立权利要求做同族、continuation、法域状态和专业 FTO；
5. 在不启动大规模三维 campaign 前，先完成 J2/J3 的最小 solver-free locked falsification test。

在这些任务关闭前，只允许使用“本轮未发现同构主文本披露”或“candidate method”等有限措辞，禁止
`first`、`novel`、`unprecedented`、`fundamental limit` 和 `clearance`。

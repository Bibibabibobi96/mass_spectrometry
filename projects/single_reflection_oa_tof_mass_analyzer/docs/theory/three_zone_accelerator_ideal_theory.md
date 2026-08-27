# oa-TOF 三区加速器理想理论与隔离验证漏斗

> `ASSESSMENT_STATUS: POST_PILOT`
>
> `EVIDENCE_LEVEL: FUNCTIONAL / PROVISIONAL`
>
> `EXECUTION_SCOPE: SOLVER_FREE_ONE_DIMENSIONAL_IDEAL_FIELD_ONLY`
>
> `THEORY_ROLE: FOUNDATIONAL_MULTIZONE_SPECIAL_CASE / PROJECT_ORACLE`
>
> `PUBLICATION_NOVELTY: NONE_BY_ITSELF`

## 1. 职责和资格边界

本文是三区分段均匀场加速器的当前理论权威，并定义其隔离、阶段化、求解器无关验证漏斗。机器精确的
campaign、阈值、seed、前驱关系和输出结构由
[`three_zone_solver_free_funnel_v2.json`](../../config/experiments/three_zone_solver_free_funnel_v2.json)
管理；公式参考实现为
[`three_zone_ideal_theory.py`](../../analysis/three_zone_ideal_theory.py)。外部输入的审阅与处置记录见
[`20260817__three-zone-accelerator-external-document-review.md`](../history/20260817__three-zone-accelerator-external-document-review.md)。

本工作流的 `Functional` 只表示一维精确时间、解析导数、冻结离散域和阶段receipt能够在不调用商业
求解器的条件下闭合；`PROVISIONAL` 表示它仍是既见过先导结果后的受控理论评估。它不是COMSOL、
SIMION或CAD Candidate，不构成三维真实场、栅透过、传输、制造可行性或性能资格。

项目当前524 Da、+1、`5±0.4 eV`双区Formal release、baseline、resolved几何、求解器资产和既有
Formal验证全部不变。此次理论评估冻结的是100 Th集成问题身份；该身份及2.2 mm先导观察不得外推为
项目Formal事实，也不得反写Formal资产。

## 2. 坐标、单位和不冲突符号

设源点坐标 $x$ 从排斥极沿提取方向增加，第一场区为 $0<x<\ell_1$。三个场区长度只记为
$\ell_1,\ell_2,\ell_3$，并定义

```math
\ell_{23}=\ell_2+\ell_3,
\qquad
\lambda=\frac{\ell_2}{\ell_{23}},
\qquad 0<\lambda<1.
```

电荷量级记为 $q_e>0$；离子电荷符号是T0独立冻结的身份字段。沿冻结 affine 相空间主线：

```math
\chi(x)=\chi_c+\beta(x-x_c),
```

```math
\chi_c=v_c\sqrt{\frac{m/q_e}{2}},
\qquad
\beta=\kappa\sqrt{\frac{m/q_e}{2}}.
```

$\chi$ 保留 $v_z$ 的符号，不能用 $\sqrt{\chi^2}$ 替换。最终单位电荷能量为

```math
\mathcal W(x)=V_R-E_1x+\chi(x)^2.
```

中心导数记为

```math
p=\mathcal W'_c=-E_1+2\chi_c\beta,
\qquad
w_2=\mathcal W''_c=2\beta^2.
```

这里用 $w_2$ 避免把电荷 $q_e$ 再用作二阶系数；时间导数只记为 $A_n,B_n,D_n$，不把
$d_1,d_2,d_3$ 同时用作长度和导数系数。

当长度使用mm、场强使用V/mm、$m/q_e$ 使用kg/C时，归一化时间 $\tau$ 的SI换算必须是

```math
t_{\rm s}=10^{-3}\sqrt{\frac{m}{2q_e}}\,\tau.
```

因而省略 $10^{-3}$ 会把绝对时间放大 $10^3$；任何秒、微秒或纳秒结果都必须经过该换算。

## 3. 精确三区时间和退化恒等式

边界电势按提取方向依次为 $V_R,V_{G1},V_{G2},0$，且

```math
E_1=\frac{V_R-V_{G1}}{\ell_1},
\qquad
E_2=\frac{V_{G1}-V_{G2}}{\ell_2},
\qquad
E_3=\frac{V_{G2}}{\ell_3}.
```

定义 $K_0=\chi^2$、$K_1=\mathcal W-V_{G1}$、$K_2=\mathcal W-V_{G2}$、
$K_3=\mathcal W$。从源点经过三区并漂移到加速器一阶时间焦面的精确归一化时间为

```math
\begin{aligned}
\tau_A^{(3)}(\mathcal W,\chi)={}&
\frac{2}{E_1}\left[\sqrt{\mathcal W-V_{G1}}-\chi\right]\\
&+\frac{2}{E_2}\left[\sqrt{\mathcal W-V_{G2}}-
\sqrt{\mathcal W-V_{G1}}\right]\\
&+\frac{2}{E_3}\left[\sqrt{\mathcal W}-
\sqrt{\mathcal W-V_{G2}}\right]
+\frac{D_A}{\sqrt{\mathcal W}}.
\end{aligned}
```

物理域至少要求 $V_R>V_{G1}>V_{G2}>0$、$E_i>0$，并对完整cohort满足后述能量、折返和
单调性门禁。

固定 $\chi$ 时令 $B_n^{(3)}=\partial^n\tau_A^{(3)}/\partial\mathcal W^n$。取

```math
(c_1,c_2,c_3,c_4)=\left(1,-\frac12,\frac34,-\frac{15}{8}\right),
```

```math
(k_1,k_2,k_3,k_4)=\left(-\frac12,\frac34,-\frac{15}{8},\frac{105}{16}\right),
```

则四阶以内可统一写为

```math
\begin{aligned}
B_n^{(3)}={}&c_n\Bigg[
\left(\frac1{E_1}-\frac1{E_2}\right)(\mathcal W-V_{G1})^{1/2-n}\\
&+\left(\frac1{E_2}-\frac1{E_3}\right)(\mathcal W-V_{G2})^{1/2-n}
+\frac1{E_3}\mathcal W^{1/2-n}\Bigg]\\
&+k_nD_A\mathcal W^{-n-1/2},\qquad n=1,2,3,4.
\end{aligned}
```

其量纲为 $[B_n]=L\,V^{-n-1/2}$。若 $E_2=E_3$，含 $V_{G2}$ 的两个时间项严格望远镜
相消，三区退化为二区；新增边界没有新的时间聚焦能力。

令

```math
\gamma=\frac{V_{G2}}{V_{G1}},
\qquad
\gamma_0=1-\lambda,
\qquad
g=\gamma-\gamma_0.
```

$g=0$ 与 $E_2=E_3$ 都必须精确回归二区oracle。实现内部也可使用
$\eta=\ln(E_2/E_3)$ 保证场强为正；$\eta=0$ 是同一退化点。

## 4. affine 源链和整机导数

沿 $\chi(\mathcal W)$ 主分支，三区加速器导数为

```math
A_1^{(3)}=B_1^{(3)}-\frac{2\beta}{E_1p},
```

```math
A_2^{(3)}=B_2^{(3)}+\frac{4\beta^3}{E_1p^3},
```

```math
A_3^{(3)}=B_3^{(3)}-\frac{24\beta^5}{E_1p^5},
```

```math
A_4^{(3)}=B_4^{(3)}+\frac{240\beta^7}{E_1p^7}.
```

多项式展开系数等于相应原始导数除以阶乘；两者不得混用。整机时间包含加速器、焦面到反射器入口的
上行漂移、双级反射器和下行漂移。令其余部分的原始能量导数为 $R_n$，则

```math
D_n=A_n^{(3)}+R_n.
```

三阶候选不是先局部调加速器再拼回旧反射器，而是用反射器两个原生变量与第三方向一次联合闭合
$D_1=D_2=D_3=0$。联合Jacobian必须满秩且尺度化条件数受控。沿 $D_1=D_2=0$ 流形，第三方向的
有效控制量为

```math
\Gamma_3=\partial_gD_3-
\begin{pmatrix}\partial_{\rho_1}D_3&\partial_{\rho_2}D_3\end{pmatrix}
J_R^{-1}
\begin{pmatrix}\partial_gD_1\\\partial_gD_2\end{pmatrix}.
```

$\Gamma_3\approx0$ 表示第三方向被低阶补偿抵消，不支持“三区提供有效第三自由度”的结论。即使
$D_3=0$，仍必须报告 $D_4$、精确有限宽度时间、峰模态和混合项；局部三阶闭合不是2.2 mm全宽充分条件。

## 5. 精确全宽和失效关闭

令 $y=x-x_c\in[-h,h]$，则

```math
\mathcal W(y)=\mathcal W_c+py+\frac12w_2y^2,
\qquad
\mathcal W_x(y)=p+w_2y.
```

能量包络必须取 $y=-h,+h$，并在 $w_2>0$ 且
$y_*=-p/w_2\in[-h,h]$ 时再取内部驻点；三者的精确极值才是cohort门禁输入。不能用中心线性斜率乘
半宽替代。若 $\mathcal W_x$ 在区间内穿零，局部能量反演和导数资格必须fail closed。

还必须逐粒子检查：

```math
\min\mathcal W>V_{G1}+\Delta V_{\rm margin}.
```

当 $\chi<0$ 时粒子先朝排斥极运动；仅有上述能量条件不能排除撞击排斥极。一维均匀第一场区内的
后向折返点为

```math
x_{\rm turn}=x-\frac{\chi^2}{E_1}.
```

完整cohort必须满足 $\min x_{\rm turn}$ 大于预声明的排斥极间隙余量。所有场强、焦后漂移、反射器二级
折返深度和有限值检查同样由调用方阈值fail closed；它们不能在看到结果后放宽。

## 6. 全局焦面与长度策略

项目当前坐标把加速器精确一阶时间焦面固定为 $z_{A,f}=0$。对每个候选先由
$A_1^{(3)}(\mathcal W_c)=0$ 派生 $D_A$，再整体平移加速器，使

```math
z_{A,\mathrm{out}}=-D_A.
```

若反射器入口的全局坐标不变，$L_{\rm up}$ 始终是从固定焦面 $z=0$ 到反射器入口的正路径长度，
因此保持不变；变化的是加速器出口到反射器入口的机械距离。不得同时冻结旧出口位置、旧机械距离和新
$D_A$，也不得把“焦面固定”误写成 $D_A=D_A^{\rm old}$。后续若要移动硬件或改变接口坐标，必须另开
工程Candidate。

外部分析没有指定 $\ell_1,\ell_2,\ell_3$ 或 $\lambda$ 的数值。它的首选路线是保留Stage1、冻结原
Stage2总长 $\ell_{23}$ 和预选 $\lambda$，只把 $g$ 作为新增电学变量。当前项目的隔离评估则显式把
$\ell_1,\ell_{23},\lambda$ 和第一段压降作为受控外层离散域；这是本项目的post-pilot试验设计，不能
倒写成外部文档的固定尺寸要求。某个等分值或 `8.4/8.4 mm` 只在被campaign显式选中时才成立，不是
理论默认值。

## 7. 科学模型与工程拓扑边界

本文的三区命名是 `zone1/zone2/zone3`，边界角色是
`repeller/intermediate1/intermediate2/exit`。既有双区resolved几何、SIMION电极语义和
`FULL_DOMAIN_PIECEWISE_IDEAL_FIELD` schema v1仍只认识
`accelerator_stage1/accelerator_stage2`、`repeller/grid1/grid2`及 `accel1/accel2`；其中现有
`grid2` 是双区出口，不是三区新增中间边界。

后续已实现并执行一条显式桥接能力：T5 receipt可由
[`three_zone_t5_simion_candidate.py`](../../analysis/three_zone_t5_simion_candidate.py)编译为
`CANDIDATE_ONLY` resolved；integration region-field schema v2只在显式
`three_zone_accelerator_ideal_v1`拓扑下接受三区region/plane/field；电极拓扑注册表保持旧双区
`0..19`不变，仅为三区新增ID `20`。显式successor layout把二区5.1 mm和三区11.9 mm的5个整形环
分别布置为1+4，并已完成真实frontend/overlay PA、N=1原生路径和完整2.2 mm N=100。隔离理论仍不得
直接复用双区profile，也不得把现有`grid2`静默改成中间电极；COMSOL、CAD、N=1000和工程资格仍未
闭合。

## 8. T0—T5阶段漏斗

机器合同声明的唯一公开入口为
`python -m projects.single_reflection_oa_tof_mass_analyzer.workflows.three_zone_ideal_theory.run_theory`。
只有该模块、campaign及schema同时存在并通过门禁时才可执行；文档本身不构成可执行入口。每次只允许
显式选择一个stage和一个新run ID；没有 `--all`，无自动重试，也不调用SIMION或COMSOL。每个stage
独立写入run-local plan、report、receipt、summary和manifest，后继stage必须消费获准的前驱receipt。

| 阶段 | 目的 | 允许的结论边界 |
|---|---|---|
| T0 | 冻结100 Th质量电荷身份、电荷符号、名义能量、affine源/cohort/权重、有效pulse时钟、全局焦面、离散域、seed、阈值和权威SHA | 只判断合同能否进入oracle |
| T1 | 验证精确公式、SI换算、符号、$g=0/\eta=0$、$\beta=0$、解析导数、阶乘、能量极值和后向折返 | 只判断理论oracle是否获支持 |
| T2 | 在完整冻结外层域上确定同一baseline连接分支内的最佳可行二区基准 | 二区若已满足目标，不自动授权三区 |
| G1 | 人工审阅T2 receipt | 授权第三方向、停止，或要求后继合同 |
| T3 | 检查低对比锚点、$\Gamma_3$、满秩/条件数及冻结的 `32+8+1` 稀疏面板 | 只判断第三方向和有限宽度信号 |
| T4a | 执行确定性的 $5^4=625$ 点粗网格 | 识别粗候选或关闭粗搜索 |
| T4b | 对预注册排名前八个粗候选做去重的 $3^4$ 邻域细化 | 形成待冻结primary，不作Formal声明 |
| G2 | 人工冻结primary、停止，或授权T4c；若授权，T4c按冻结排名确定primary后直接进入T5，不再执行第二次G2 | 只有明确receipt可开启全域扩展 |
| T4c | 可选完整外层网格覆盖扩展 | 只在G2人工授权后运行；不是默认路径 |
| T5 | 用冻结primary独立对比最佳可行二区基准并报告稳健性 | 最多支持一维理想场理论结论或递交求解器后继 |

T4c的 `32,955` 只是离散外层域笛卡尔积的点数：

```math
13\;(\ell_1=3.00{:}0.25{:}6.00)\times
13\;(\ell_{23}=5{:}1{:}17)\times
13\;(\lambda=0.20{:}0.05{:}0.80)\times
15\;(\Delta V_1=150{:}25{:}500)=32{,}955.
```

它不是性能指标、不是外部文档结论、不是已执行点数，也不是32,955次SIMION/COMSOL运行。T4a/T4b
足以给出可冻结primary时，默认不执行T4c；只有边界或覆盖不足触发并取得G2人工授权后才可扩展。

### 已完成结果的历史边界

2026-08-17已完成的canonical solver-free链、真实SIMION PA后继、observed-source顺序归因、全部数值、
run身份和限制已冻结在
[`20260823__three-zone-completed-results-snapshot.md`](../history/20260823__three-zone-completed-results-snapshot.md)。
本理论正文不再复制日期化结果。

该历史证据最高仍为100 Th、N=100真实PA或求解器无关post-pilot结论，不改变524 Da Formal，也未完成
条件源模型、source-weighted受约束重优化、N≥1000、多质量、独立求解器、COMSOL/CAD或工程资格。
它可以支持提出[`条件相空间可聚焦性`](conditional_phase_space_focusability.md)问题，不能直接支持
Paper 1投稿结论。

## 9. 晋级与停止条件

任何stage都必须保留完整失败行、全部根和分支选择依据，不得按低FWHM后筛选。branch选择只按baseline
连续性和参数距离，不按性能。先导结果只作为高对比上界和post-pilot设计输入，不能作为warm start或
确认数据。

T5通过也只允许报告`PRIMARY_THEORY_ONLY_SUPPORTED`、
`PRIMARY_CONFIRMATION_PASSED_OVER_BEST_TWO_ZONE`或同等的求解器无关结论。即使已存在
T5→Candidate resolved编译边界，也必须另行预注册并执行三区工程拓扑、当前电压包络、真实边缘场、
栅网、传输、容差、COMSOL、SIMION和CAD关闭条件；在该后继完成前，项目Formal及所有现有工程资产
保持不变。

## 10. 有限束宽接受的理论设计（理想场，不是机械约束）

本节扩展的是精确理想场理论，不修改上述历史T0—T5合同。场区边界表示分段均匀场的作用范围；旧
电极尺寸、孔径、厚度和边缘场不得成为这里的理论上限。有限接受设计应先解聚焦方程，再用精确时间
和独立粒子检验，而不是先按峰宽寻优、再倒推解释。解析展开的维护入口为
[`ideal_acceptance_theory.py`](../../analysis/ideal_acceptance_theory.py)。

### 10.1 直接在位置域展开，保留残差投影

令 $y=x-x_c$，$v=v_c+\kappa y+\epsilon$，均匀位置全宽为 $W=2h$，条件速度残差标准差为
$\sigma_v$。在固定的源到检测器模型中写

```math
t(y,\epsilon)=t_0+\sum_{n\ge1}a_ny^n+b(y)\epsilon+O(\epsilon^2),
\qquad a_n=\frac{1}{n!}\left.\frac{d^nt(y,0)}{dy^n}\right|_0.
```

局部三阶聚焦要求 $a_1=a_2=a_3=0$，不要求、也不保证 $a_4=0$。当局部能量反演成立时，这与
$D_1=D_2=D_3=0$等价；位置域精确时间在能量斜率穿零时仍可定义，不能把能量反演失效误判为粒子
物理损失。近似总方差为

```math
\operatorname{Var}(t)\simeq
\operatorname{Var}_y\!\left[\sum_{n\ge1}a_ny^n\right]
+\sigma_v^2\,\mathbb E_y[b(y)^2].
```

这只改变固定源残差对到达时间的投影，不改变上游源残差。若仅保留四阶且位置均匀，

```math
\operatorname{Var}(a_4y^4)=\frac{16}{225}a_4^2h^8.
```

因此束宽增大时，高阶展宽可以比固定速度残差迅速增长。该方差式不是FWHM式，不能把高斯等效宽度
当作有尾峰的实际FWHM，接受判据仍须用精确时间分布和既有峰宽算法验证。

### 10.2 先增加展开的有效范围，而非机械地拉长间隙

第一场区出口处的中心动能为

```math
K_{1c}=\mathcal W_c-V_{G1}
=E_1(\ell_1-x_c)+\chi_c^2.
```

精确时间含 $\sqrt{K_{1c}+py+\beta^2y^2}$。其中心二项式展开在
$|py+\beta^2y^2|<K_{1c}$内收敛；接近该比值的一侧，四阶后的项不可忽略。低中心动能近似下，
该比值约为 $h/(\ell_1-x_c)$。所以增加源中心到第一场区出口的理想场距离，可以减缓高阶项增长；
仅取消三阶项不能保证宽束仍处于有效展开范围。

另一方面，在中心一阶聚焦成立时，令 $\alpha=\sqrt{m/(2q_e)}$，长度用mm，速度用m/s，则

```math
b(0)=10^{-3}\frac{m/q_e}{p},
\qquad p=-E_1+2\chi_c\beta.
```

故在相同源条件下，保持第一场压降却增大长度会降低 $E_1$，通常增大残差的时间投影。理论设计必须
同时考虑展开范围与提取场强，而不能把“更长”单独当作充分条件。该局部恒等式不是整个仪器的物理
分辨率下限；高阶项、全宽 $b(y)$、事件可达性和精确FWHM仍需检验。

### 10.3 用线性聚焦方程反求场强与场区长度

给定 $E_1$、源中心到第一场区出口的距离 $a$、中心静电能 $V_0$，有
$V_{G1}=V_0-E_1a$。再给定 $0<V_{G2}<V_{G1}$和反射器第一级电势 $U_1$，设
$u_2=1/E_2$、$u_3=1/E_3$、$u_R=1/F_2$。固定反射器第一级长度 $L_1$和总无场路径 $D$时，

```math
\begin{aligned}
\tau(y)={}&H(y)+u_2P_2(y)+u_3P_3(y)+u_RP_R(y),\\
H(y)={}&\frac{2}{E_1}[\sqrt{\mathcal W-V_{G1}}-\chi]
+\frac{4L_1}{U_1}[\sqrt{\mathcal W}-\sqrt{\mathcal W-U_1}]
+\frac{D}{\sqrt{\mathcal W}},\\
P_2(y)={}&2[\sqrt{\mathcal W-V_{G2}}-\sqrt{\mathcal W-V_{G1}}],\\
P_3(y)={}&2[\sqrt{\mathcal W}-\sqrt{\mathcal W-V_{G2}}],\\
P_R(y)={}&4\sqrt{\mathcal W-U_1}.
\end{aligned}
```

取这四个函数的一至三阶Taylor系数，$a_1=a_2=a_3=0$成为一个三乘三线性方程组，直接解出
$u_2,u_3,u_R$。正场解对应的长度随后由

```math
\ell_2=(V_{G1}-V_{G2})u_2,\qquad
\ell_3=V_{G2}u_3
```

得到。这是从时间聚焦条件反求理想设计，而非按粒子峰宽盲调电压。矩阵奇异、逆场非正或完整源不能
跨越/折返时，该理论分支不适格。可进一步以 $a_4=0$作为剩余电势参数的方程，但必须实际找到正场
根；不能仅按自由变量数量宣称必然能消除第四阶。若无根，应报告该分支上的非零高阶余项。

若要隔离“重新分配场区”与“加长飞行时间”的贡献，可增加总加速器长度方程：

```math
\ell_1+(V_{G1}-V_{G2})u_2+V_{G2}u_3=L_{\rm accelerator}.
```

在前三阶线性解上对剩余的 $U_1$求此方程的根。必须排除矩阵极点、负场与不满足长度残差的伪根，
保留全部检测到的正场根。固定旧总长只是公平对照，不是理论设计的普适尺寸限制；有限电压网格没有
检测到根也不能证明连续域无根。实现见
[`ideal_acceptance_linear_design.py`](../../analysis/ideal_acceptance_linear_design.py)。

### 10.4 “最大接受尺度”的范围必须明示

需分别报告：某一冻结设计的最大已验证全宽、某一理论设计族中找到的最大已验证全宽，以及是否存在
全局上界证明。数值扫描终点、旧几何范围、求根失败或未找到更好设计都不是全局上界证明。

若同时把整个理想仪器长度乘 $s$、电势乘 $\mu^2$、初速度乘 $\mu$，精确飞行时间乘 $s/\mu$。
保留源的线性斜率要求 $\mu=s$，但同时必须处理中心速度与随机残差的缩放；不能在固定这两者时
直接套用相似变换。该关系说明不声明长度、能量及源条件时，“绝对最大宽度”缺少唯一比较定义。
当前无三维场计算时，“实验接受”只指独立数值粒子实验，不能称为真实仪器或实测接受尺度。

### 10.5 总体峰宽与有限粒子峰宽不能混为一谈

有限粒子的canonical KDE带宽与样本标准差、粒子数有关。长尾会增大样本标准差，从而把主峰平滑得
更宽；所以某一粒子数下的KDE分辨率未通过，不等于连续总体的真实主峰未通过。粒子对照仍使用同一
canonical口径，但理论接受另用源分布的精确推前密度验证。

对均匀 $y$与Gaussian残差，令 $\epsilon_k(t,y)$为精确时间方程 $t(y,\epsilon)=t$ 的各根，则

```math
f_T(t)=\frac{1}{W}\int_{-W/2}^{W/2}
\sum_k\frac{\phi_{\sigma_v}(\epsilon_k(t,y))}
{|\partial t/\partial\epsilon|_{\epsilon_k}}\,dy.
```

当前维护实现[`ideal_acceptance_density.py`](../../analysis/ideal_acceptance_density.py)在显式有限残差
包络内检查每个位置积分节点的残差到时间映射单调性，反演唯一根并积分，不使用KDE带宽。映射折叠时
明确报告模型方法不支持，不删除该位置，也不冒充无粒子损失；位置求积、时间网格和概率积分须检查
收敛。包络外Gaussian尾概率单独报告，不能称无限Gaussian严格全体可达。

用与粒子分析相同的表观质量定义 $M=m_0(T/\bar T)^2$，密度变换为

```math
f_M(m)=f_T\!\left(\bar T\sqrt{m/m_0}\right)
\frac{\bar T}{2\sqrt{m_0m}}.
```

质量FWHM沿用canonical半高交点定义，$R=m_0/\Delta m_{\rm FWHM}$。这不是更换有限粒子的指标，而是
把连续理论峰与有限粒子估计分开；总体积分收敛、有限粒子种子重复和粒子数收敛是三种不同证据。

### 10.6 200 mm 实用长度约束下的已测范围

`ideal_acceptance_200mm.json`及其边界配置冻结了一个可复现的理想场比较：三区总长严格为200 mm，
100 Th规定仿射源、10 m/s Gaussian条件残差、2000 V中心静电能、反射器长度和无场路径保持固定。
枚举声明的$E_1$、源中心至grid1距离和grid2电势比例；每个正场三阶解再以长度方程求反射器一级根。
每一束宽先按精确矩的相对时间方差保留八个候选，随后以精确总体FWHM选择一个冻结候选，最后以三个
独立的5000粒子canonical-KDE重复确认。完整receipt见项目历史快照。

在该**离散、已声明设计域**内，4.0 mm是最大已测总体通过宽度（总体$R=26435$）；4.2 mm及以上至
20 mm的已检查候选均未通过总体门槛$R\ge25000$。3.6 mm是最大已测独立粒子通过宽度（三个重复
$R=27308,26655,25225$）；3.8 mm的冻结候选总体仍通过（$R=26793$），但第三个粒子重复为
$R=24699$，因而不通过“所有重复”判据。该结果说明旧短第一场区/三区分配不是宽度接受的结构性上限，
但不构成200 mm连续参数空间的全局最优证明，更不构成真实三维仪器、孔径传输或实测源接受度结论。

### 10.7 300 mm 对照：长度是有价值的设计自由度，但非单调定律

在保持10.6的离散宽度、源、反射器、控制域、数值密度与粒子合同不变、且不补密边界的公平对照中，
总三区长度300 mm的4.0 mm冻结候选取得总体$R=28181$和三个5000粒子重复
$R=28657,27422,26022$；200 mm主扫描同一宽度的第三重复为$R=24456$。因此在这个受限的理想场
设计域中，总长是改善宽束接受稳健性的有效自由度。该对照不推出长度与接受宽度的单调关系，不是连续域
最大宽度或工程几何结论；完整运行身份、设计及负结果见
[`300 mm扫描快照`](../history/20260827__300mm-ideal-acceptance-scan.md)。

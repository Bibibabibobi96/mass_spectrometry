# oa-TOF 三区加速器理想理论与隔离验证漏斗

> `ASSESSMENT_STATUS: POST_PILOT`
>
> `EVIDENCE_LEVEL: FUNCTIONAL / PROVISIONAL`
>
> `EXECUTION_SCOPE: SOLVER_FREE_ONE_DIMENSIONAL_IDEAL_FIELD_ONLY`

## 1. 职责和资格边界

本文是三区分段均匀场加速器的当前理论权威，并定义其隔离、阶段化、求解器无关验证漏斗。机器精确的
campaign、阈值、seed、前驱关系和输出结构由
[`three_zone_solver_free_funnel_v1.json`](../../config/experiments/three_zone_solver_free_funnel_v1.json)
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

后续已实现但尚未执行一条显式桥接能力：T5 receipt可由
[`three_zone_t5_simion_candidate.py`](../../analysis/three_zone_t5_simion_candidate.py)编译为
`CANDIDATE_ONLY` resolved；integration region-field schema v2只在显式
`three_zone_accelerator_ideal_v1`拓扑下接受三区region/plane/field；电极拓扑注册表保持旧双区
`0..19`不变，仅为三区新增ID `20`。这些能力没有被任何canonical run消费，也没有新增layout
profile、frontend GEM/PA中的真实第三栅、N=1 smoke或N=100传输。因此隔离理论结果仍不得直接复用
双区profile，不得把现有 `grid2` 静默改成中间电极，更不得声称三区理论场已经在SIMION、COMSOL或
CAD中实现。进入工程验证仍须先闭合三区layout/profile/GEM、真实栅面、电极映射、solver run和证据链。

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

### 2026-08-17 canonical solver-free结果

canonical链实际执行了`T0,T1,T2,G1,T3,T4a,T4b,G2,T5`，没有执行可选T4c。T2在冻结域和同一
baseline连接分支内得到的最佳可行二区基准为
`d1=4.5 mm, l23=15.0 mm, lambda=0.5, DeltaV1=475 V`；其2.2 mm cohort
`population sigma=0.8159038773341178 ns`、直接
`FWHM=0.679286964277992 ns`。

G2冻结的三区primary为
`d1=3.25 mm, l23=17.0 mm, lambda=0.30, DeltaV1=250 V`。它的场对比度为
`2.826764127118471`，尺度化Jacobian条件数为`561.8473678`，尺度化
`Gamma3=1.12487848e-4`；所有post-root门禁通过，但因`l23=17.0 mm`落在冻结域上界而标记为
`boundary_limited=true`。这支持冻结域内的primary，不支持向域外外推。

T5在1001点cohort上得到：

| 宽度 | population sigma (ns) | 直接FWHM (ns) |
|---|---:|---:|
| 2.2 mm | `0.18240109086706416` | `0.14113517445224488` |
| 1.0 mm | `0.004970459371531842` | `0.003840889778672363` |

相对最佳可行二区，2.2 mm的sigma和直接FWHM分别改善`77.6443%`和`79.2230%`。primary在
2.2 mm和1.0 mm上的501/1001/2001点population-sigma最大相对差分别为`0.7647%`和`0.6353%`，
峰模态均稳定。最终结论为
`PRIMARY_CONFIRMATION_PASSED_OVER_BEST_TWO_ZONE`，canonical T5 run是
`20260817_122700__analysis__python__three-zone-t5`。

这些数值仍只是post-pilot、solver-free、一维理想分段场证据，不是工程资格、SIMION/COMSOL/CAD
结果或当前Formal设计变更。

## 9. 晋级与停止条件

任何stage都必须保留完整失败行、全部根和分支选择依据，不得按低FWHM后筛选。branch选择只按baseline
连续性和参数距离，不按性能。先导结果只作为高对比上界和post-pilot设计输入，不能作为warm start或
确认数据。

T5通过也只允许报告`PRIMARY_THEORY_ONLY_SUPPORTED`、
`PRIMARY_CONFIRMATION_PASSED_OVER_BEST_TWO_ZONE`或同等的求解器无关结论。即使已存在
T5→Candidate resolved编译边界，也必须另行预注册并执行三区工程拓扑、当前电压包络、真实边缘场、
栅网、传输、容差、COMSOL、SIMION和CAD关闭条件；在该后继完成前，项目Formal及所有现有工程资产
保持不变。

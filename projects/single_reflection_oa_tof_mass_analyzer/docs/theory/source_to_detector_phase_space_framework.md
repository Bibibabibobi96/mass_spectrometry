# OA-TOF 从条件源到探测器的统一相空间框架

> `DOC_STATUS: PROJECT_THEORY_CANDIDATE / EVIDENCE_REQUIRED`
>
> `ROLE: CANONICAL_MULTIVARIATE_FRAMEWORK`
>
> `FORMAL_EFFECT: NONE`

本文是单次反射 oa-TOF 的多变量理论入口。它统一源状态、正交加速、漂移、二级反射镜、有限孔径、
探测事件、工程误差和测量响应，但不替代已有组件的精确解析 oracle，也不把候选理论升级为当前
Formal 结论。双区、三区、二级反射镜和一维耦合的精确公式仍由本目录相应组件文档维护。

本文中的条件期望、协方差、矩传播、投影、SVD 和辛映射都是标准数学工具。可投稿的候选贡献只可能
来自它们在完整 oa-TOF source-to-detector 问题中的可证伪组合、真实源验证和新的物理结论；新颖性
状态见[`发表先行工作与claim注册表`](../publication/prior_art_claim_registry.md)。

## 1. 权威边界与理论标签

本文只维护稳定物理定义和验证边界：

- `FOUNDATIONAL`：经典理论或标准数学，只能引用和实现；
- `PROJECT_ORACLE`：本项目已有精确特例、回归实现或失效关闭条件；
- `PAPER_1_CANDIDATE`：JASMS候选贡献，仍需先行工作与数值证据；
- `PAPER_2_EXTENSION`：后续主动相空间调理与实验联合设计；
- `EVIDENCE_REQUIRED`：尚不能写成已证实结论。

机器精确参数、当前资格和结果分别属于`../../config/`、[`PROJECT.md`](../PROJECT.md)和受manifest
管理的运行证据。本文不保存日期化电压、run ID或分辨率数字。

## 2. 三个时刻必须分开

### 2.1 源表征时刻

条件源必须在所有粒子共享的物理时刻

$$
t=t_{\mathrm{pre}}
$$

记录。该时刻位于有效提取脉冲之前，用于冻结 detector-blind 粒子状态、RF相位和eligible cohort。
不同粒子不得在各自穿过不同事件面时取“初态”，否则会把自由飞行时间混入相空间相关。

### 2.2 分辨率零点

项目分辨率的唯一时钟仍为

$$
\boxed{T_{\mathrm{TOF}}=t_{\mathrm{detector}}-t_{\mathrm{pulse,effective}}}.
$$

`t_pre`只定义源表征epoch，不是TOF零点。脉冲前生成、驻留和传输时间不得进入质量分辨率，只能通过
脉冲瞬间的位置、速度、能量和相位分布影响结果。

### 2.3 仪器绝对时钟

absolute instrument clock用于调度、连续飞行和诊断，不能作为分辨率声明。任何分析输出都必须显式
区分`pre_pulse_epoch`、`pulse_effective_epoch`和`detector_event_time`。

## 3. 坐标、独立状态与无量纲化

### 3.1 坐标映射

理论使用局部正交提取轴`s_parallel`及速度`v_parallel`。实现可以使用局部`x/vx`或全局`z/vz`，但必须
在机器合同中给出有符号映射；不得靠文件名或绝对值静默转换。

### 3.2 独立状态

共同pre-pulse状态可写为

$$
\mathbf u=
(\mathbf r,\mathbf v,\delta t_{\mathrm{trigger}},
\delta\phi_{\mathrm{RF}},\boldsymbol\eta_{\mathrm{ind}})^T,
$$

其中`η_ind`只保存不能由位置、速度、质量和电荷唯一计算的独立状态。若动能由三维速度重算，就不能
再把同一总动能作为独立随机维度；若确有内部能量、未解析自由度或独立能量误差，必须单独命名并说明
与速度的关系。

### 3.3 固定尺度

位置、速度、电压、时间和RF相位的数值尺度不同。任何协方差特征模态、SVD、rank或条件数分析前，
必须在查看探测器结果之前冻结尺度矩阵`S_u`和设计参数尺度`S_theta`：

$$
\mathbf u=S_u\widetilde{\mathbf u},
\qquad
\delta\boldsymbol\theta=S_\theta
\delta\widetilde{\boldsymbol\theta}.
$$

尺度来源可以是预注册物理容差、训练源稳健尺度或明确工程上限。模态排序必须声明所用坐标、单位和
尺度；未缩放的混合单位PCA不能成为物理结论。

## 4. 完整source-to-detector映射

对冻结输入和设计参数`θ`，定义：

$$
T=\mathcal T(\mathbf u;\boldsymbol\theta),
\qquad
\mathbf r_D=\mathcal R_D(\mathbf u;\boldsymbol\theta),
$$

$$
\mathcal I(\mathbf u;\boldsymbol\theta)\in\{0,1\},
\qquad
\mathcal C(\mathbf u;\boldsymbol\theta)
=\text{termination/loss class}.
$$

`T`只对真实探测事件存在，但母cohort、损失分类和分母对全部eligible粒子保持冻结。因此正式性能对象
至少包含：

- pulse-relative TOF峰；
- 命中率和完整损失census；
- 探测位置、角度和入射能量；
- 峰形、尾部、旁峰和多模态；
- 对源、设计和工程扰动的敏感度。

只优化幸存命中粒子的条件峰宽会产生post-selection偏差。缩孔、裁束或使难聚焦粒子损失不能被报告
为无代价的分辨率改善。

### 4.1 时变场、波形时钟与有限渡越

若系统含脉冲后动态加速、时变反射或主动调理，映射是非自治的：

$$
\dot{\mathbf r}=\mathbf v,
\qquad
m\dot{\mathbf v}=q\mathbf E(\mathbf r,t;\boldsymbol\theta),
\qquad
T=\mathcal T(\mathbf u,t_{\mathrm{pulse}};\boldsymbol\theta).
$$

波形相位、触发抖动和绝对仪器时刻只有在会改变粒子所见场时才作为独立状态进入；报告的TOF零点
仍是有效提取脉冲。利用第一漂移区的质量相关到达时刻$t_a(m/q)$对不同质量包施加不同波形值，是
time-encoded control，不等于一套静态电压对所有质量同时聚焦。

把短动态区写成瞬时能量kick

$$
\Delta K\approx-q\Delta V(t_{\mathrm{cross}})
$$

只在渡越时间远小于波形变化时间、fringe field可忽略且进入时刻定义唯一时成立。一般情况必须积分
$q\mathbf E(\mathbf r,t)\cdot d\mathbf r$，并把有限动态区长度、slew rate、带宽、栅格场穿透、波形
抖动和相邻质量包同时占据纳入约束。任何“mass-independent dynamic focusing”都必须说明其质量编码
机制、同步参考和可同时处理的质量包范围。

## 5. 局部到达时间张量

在冻结工作点附近，以中心化、非冗余且已缩放的状态展开：

$$
\Delta T
=g_i u_i
+\frac12H_{ij}u_i u_j
+\frac16C_{ijk}u_i u_j u_k
+\frac1{24}Q_{ijkl}u_i u_j u_k u_l
+O(\|\mathbf u\|^5).
$$

其中`g`、`H`、`C`和`Q`分别是一至四阶source-to-detector时间灵敏度。现有一维`D1/D2/D3`只是该
体系沿一条指定源链的方向导数，不代表完整三维系统的全部像差。

若源矩为`Σ`、`M^(3)`和`M^(4)`，则四阶截断下：

$$
E[\Delta T]\approx
\frac12H_{ij}\Sigma_{ij}
+\frac16C_{ijk}M^{(3)}_{ijk}
+\frac1{24}Q_{ijkl}M^{(4)}_{ijkl},
$$

$$
\begin{aligned}
\operatorname{Var}(T)\approx{}&
g_i\Sigma_{ij}g_j
+g_iH_{jk}M^{(3)}_{ijk}
+\frac13g_iC_{jkl}M^{(4)}_{ijkl}\\
&+\frac14H_{ij}H_{kl}
\left(M^{(4)}_{ijkl}-\Sigma_{ij}\Sigma_{kl}\right).
\end{aligned}
$$

对近似零均值高斯源，可化为

$$
\operatorname{Var}(T)\approx
\mathbf g^T\Sigma\mathbf g
+\frac12\operatorname{tr}(H\Sigma H\Sigma)
+g_iC_{jkl}\Sigma_{ij}\Sigma_{kl}.
$$

这些矩公式用于解释、初值和误差预算；最终FWHM、尾部和多模态仍必须由冻结粒子逐粒子传播得到。

### 5.1 协方差交叉项

“非冗余”不等于“统计独立”。两个有相关性的源坐标仍可同时作为独立坐标轴；只要没有把同一物理量
重复编码，就应保留其协方差。对两个零均值变量$x,y$的一阶传播，正确的分量式为

$$
\operatorname{Var}(T)\approx
T_x^2\sigma_x^2+T_y^2\sigma_y^2
+2T_xT_y\operatorname{Cov}(x,y).
$$

交叉项由两个一阶灵敏度的乘积给出，不能写成$2T_{xy}\operatorname{Cov}(x,y)$。混合Hessian
$T_{xy}$只在保留二阶映射后通过更高阶矩进入方差。任何外部推导在纳入仓库前还必须通过量纲检查：
均匀场飞行项应含$2(\sqrt{W_{\rm out}}-\sqrt{W_{\rm in}})/E$，无场漂移项必须含
$D/\sqrt W$；缺少场强或漂移距离的表达式不能作为时间公式使用。

### 5.2 局部导数阶、端点等时与有限焦区

本项目采用标准的局部导数阶定义。对标量源坐标$x$，若

$$
T_x=T_{xx}=\cdots=T_{x^{(q)}}=0
$$

在同一参考粒子和同一固定探测面成立，才称为$q$阶局部时间聚焦。下列量不能与该定义混用：

- 两个有限端点满足$T(x_a)=T(x_b)$，这是pairwise/end-point isochrony；
- $T(x)$在有限区间内有若干转折点，这是峰形拓扑；
- 不同粒子轨迹在若干位置相交，这是空间焦点计数。

有限源通常形成焦区而不是唯一焦面。应在预先冻结的源分布上，沿候选探测面比较直接峰宽、尾部、
传输和损失，而不能用单个参考粒子的导数零点替代有限分布最优面。类似地，
$\max_iT_i-\min_iT_i$只是arrival-time envelope；除非权重和分布另有严格证明，它不是概率密度峰的
FWHM。投稿性能必须由带粒子权重的到达时间分布直接提取，并在需要时与触发、探测器和电子学响应卷积。

## 6. 多维条件流形与有限厚度

令条件坐标`\mathbf s\in\mathbb R^k`，真实源写成

$$
\boxed{
\mathbf u=\boldsymbol\mu(\mathbf s)+\boldsymbol\varepsilon,
\quad
E[\boldsymbol\varepsilon\mid\mathbf s]=0,
\quad
\operatorname{Cov}(\boldsymbol\varepsilon\mid\mathbf s)
=\Sigma_\varepsilon(\mathbf s)
}.
$$

这同时允许：

- 一维affine或非线性`z-v_z`主流形；
- 多维位置、RF相位或上游状态条件化；
- 异方差、偏态、尾部和多模态残差。

定义

$$
\tau(\mathbf s)=\mathcal T(\boldsymbol\mu(\mathbf s);\boldsymbol\theta),
\qquad
J_\mu=\frac{\partial\boldsymbol\mu}{\partial\mathbf s}.
$$

一阶切向closure为

$$
\boxed{J_\mu^T\mathbf g=0},
$$

而给定`\mathbf s`的最低阶条件厚度时间代价为

$$
\boxed{
J_\perp(\mathbf s)
=\mathbf g^T\Sigma_\varepsilon(\mathbf s)\mathbf g
}.
$$

总方差恒等式

$$
\operatorname{Var}(T)
=\operatorname{Var}(E[T\mid\mathbf S])
+E[\operatorname{Var}(T\mid\mathbf S)]
$$

严格成立；把两项近似为`Var[τ(S)]`和`E[J_perp(S)]`则依赖局部展开。条件协方差随`s`变化时的Hessian
均值偏移、切向—残差交叉项和非高斯高阶项必须单列，不能藏进一个“残差”数字。

## 7. 一般N区正交加速器接口

设`N`个连续匀强场区的边界电位满足

$$
V_0=V_R>V_1>\cdots>V_N=0,
\qquad
E_j=\frac{V_{j-1}-V_j}{d_j}>0.
$$

定义有符号初速度的电压等效量与出口总能量每电荷：

$$
\chi=v_\parallel\sqrt{\frac{m}{2q}},
\qquad
\mathcal W=V_R-E_1x+\chi^2.
$$

从第一场区内释放点到加速器出口后距离`D_A`的精确归一化时间为

$$
\begin{aligned}
\tau_A^{(N)}={}&
\frac{2}{E_1}
\left[\sqrt{\mathcal W-V_1}-\chi\right]\\
&+\sum_{j=2}^{N}\frac{2}{E_j}
\left[\sqrt{\mathcal W-V_j}
-\sqrt{\mathcal W-V_{j-1}}\right]
+\frac{D_A}{\sqrt{\mathcal W}}.
\end{aligned}
$$

长度为mm、场强为V/mm时，物理时间乘

$$
10^{-3}\sqrt{\frac{m}{2q}}.
$$

`N=2`和`N=3`分别由现有
[`双区文档`](oaaccelerator_time_focus.md)与
[`三区文档`](three_zone_accelerator_ideal_theory.md)及其代码测试维护。一般`N`式目前是解析统一接口，
不是已实现任意拓扑的工程能力。

二级反射镜精确时间、能量包络和整机`D_n=A_n+R_n`分别只由
[`反射镜文档`](dual_stage_reflectron.md)和
[`整机耦合文档`](oatof_oaaccelerator_coupling.md)维护，本文不复制其局部解。

## 8. 三维轨迹和探测事件灵敏度

对状态`\mathbf y=(\mathbf r,\mathbf v)^T`：

$$
\dot{\mathbf y}=\mathbf F(\mathbf y,t;\boldsymbol\theta).
$$

初态或设计参数`α`的灵敏度满足变分方程

$$
\dot S_\alpha
=\frac{\partial\mathbf F}{\partial\mathbf y}S_\alpha
+\frac{\partial\mathbf F}{\partial\alpha}.
$$

若探测面为`h(\mathbf r,t,\alpha)=0`，则事件时间导数为

$$
\boxed{
\frac{\partial T}{\partial\alpha}
=-
\frac{h_\alpha+\nabla h\cdot
\partial\mathbf r(T)/\partial\alpha}
{h_t+\nabla h\cdot\mathbf v(T)}
}.
$$

该式可把三维轨迹灵敏度转换为真实到达时间梯度。掠入射使分母接近零、事件拓扑改变或粒子命中状态
变化时，局部导数可能失效，必须转回直接有限粒子比较。

高阶导数可以使用变分方程、自动微分、稳定多步长中心差分或局部正交设计拟合，并至少用两条真正
独立的计算路径校核。不同wrapper调用同一核心函数不算独立验证。

## 9. 工程扰动、测量链与良率

令工程扰动协方差为`Σ_theta`，则一阶时间贡献为

$$
\sigma_{T,\theta}^2
\approx
\mathbf g_\theta^T\Sigma_\theta\mathbf g_\theta.
$$

若源与工程扰动相关，还需加入交叉协方差项。误差类别至少覆盖OA波形、反射镜电压、机械间距与
同轴度、RF相位、有效探测面、detector transit time、TDC和温漂。

实际观测峰为

$$
p_{\mathrm{obs}}
=p_{\mathrm{ion}}
*h_{\mathrm{pulse}}
*h_{\mathrm{det}}
*h_{\mathrm{TDC}}
*h_{\mathrm{proc}}.
$$

只有各响应近似独立高斯时才允许方差相加。存在振铃、偏态、离散采样或多触发模式时，应使用实测响应
直接卷积。反卷积必须同时报告原始峰、响应测量和不确定度，不能制造低于测量链响应的超分辨率。

设计验收应报告容差分布下满足`R`、传输和单峰性规格的良率，而不只报告名义工作点。

## 10. 性能向量与有限分布设计

推荐使用Pareto性能向量：

$$
\mathbf P=(R_{\mathrm{FWHM}},\eta,Q_{99}-Q_1,
P_{\mathrm{main}},P_{\mathrm{multi}},A,\Delta E_{\mathrm{acc}},Y_{\mathrm{tol}}).
$$

其中`η`使用完整母cohort分母，`A`表示空间/相空间接受度，`Y_tol`表示工程良率。正式比较必须在相同
源、粒子ID、几何与电压上限、detector、命中规则、优化预算和峰算法下，让每个架构在自身参数空间中
充分重新优化。

质量分辨率仍遵循项目统一定义：

$$
R=\frac{m}{\mathrm{FWHM}_m}
\approx\frac{T_{\mathrm{TOF}}}{2\,\mathrm{FWHM}_t}.
$$

`2.3548σ`只在近高斯单峰时是FWHM代理；论文主要结果应同时报告直接FWHM、分位宽、尾部、主峰比例、
命中率和bootstrap区间。

## 11. 模型层级

| 层级 | 内容 | 允许结论 |
|---|---|---|
| L0 | 双区/三区/N区一维精确时间、二级反射镜、局部导数 | 解析可行性与oracle |
| L1 | 冻结经验源、条件分布、理想分段场逐粒子传播 | source-conditioned理论候选 |
| L2 | 真实轴线电势与参考面 | 轴向场偏差与折返边界 |
| L3 | 三维无空间电荷轨迹、孔径和探测事件 | Candidate级三维物理证据 |
| L4 | 实测波形、制造/电压/时序误差和测量链 | 工程稳健性与良率 |
| L5 | 空间电荷、as-built样机、多质量与实验校准 | 实验测量能力 |

层级之间不能越级表述。当前100 Th三区observed-source结果仍是N=100、固定设计的历史诊断；当前
524 Da Formal结果也不能替代真实RF源上的Paper 1验证矩阵。

## 12. 与现有组件文档的关系

| 文档 | 唯一职责 |
|---|---|
| [`oaaccelerator_time_focus.md`](oaaccelerator_time_focus.md) | 静止源、N=2双区精确模型与焦面oracle |
| [`z_vz_linear_phase_space_coupling.md`](z_vz_linear_phase_space_coupling.md) | affine `z-v_z`特例与随机残差入口 |
| [`dual_stage_reflectron.md`](dual_stage_reflectron.md) | 二级反射镜局部精确时间和包络oracle |
| [`oatof_oaaccelerator_coupling.md`](oatof_oaaccelerator_coupling.md) | 一维加速器—反射镜整机耦合 |
| [`three_zone_accelerator_ideal_theory.md`](three_zone_accelerator_ideal_theory.md) | N=3精确特例、`A1–A4`、`Γ3`和隔离漏斗 |
| [`conditional_phase_space_focusability.md`](conditional_phase_space_focusability.md) | 条件厚度的受约束可聚焦性判据 |

## 13. 禁止性结论

- 不得把共同pre-pulse时刻写成分辨率零点。
- 不得把重复的速度和总能量字段同时作为独立随机维度。
- 不得用未缩放的混合单位协方差模态支持物理排序。
- 不得用命中后筛选的窄峰替代完整母cohort性能。
- 不得把`D1/D2/D3=0`、`Γ3≠0`或局部projector下界写成有限真实源充分条件。
- 不得把一般N区解析式写成任意N区COMSOL、SIMION或CAD已经实现。
- 不得把标准统计、线性代数或经典相关聚焦重新命名为项目创新。

# 三区正交加速器局部理想理论

> `THEORY_ROLE: FOUNDATIONAL_MULTIZONE_SPECIAL_CASE / PROJECT_ORACLE`
>
> `PUBLICATION_NOVELTY: NONE_BY_ITSELF`
>
> `MODEL_SCOPE: ONE_DIMENSIONAL_PIECEWISE_UNIFORM_FIELD`

## 1. 职责和资格边界

本文统一维护独立加速器项目的三区精确时间、局部一至四阶导数、第一时间焦距、退化与可达性条件。
内容从单次反射 oa-TOF 的三区理论中按物理边界拆出；并不迁移其旧 Formal、历史证据或集成运行。

参考实现为
[`analysis/three_zone_ideal_theory.py`](../../analysis/three_zone_ideal_theory.py)。
二区静止释放见[`oaaccelerator_time_focus.md`](oaaccelerator_time_focus.md)，
有符号初始速度见[`affine_phase_space_time_focus.md`](affine_phase_space_time_focus.md)。
精确值、结构变体与项目成熟度分别由 `config/` 和 [PROJECT](../PROJECT.md)维护。

三区结构的边界角色为 `repeller/intermediate1/intermediate2/exit`，两区出口不能被静默改名为
三区中间电极。这里没有栅丝、真实边缘场、碰撞、空间电荷或任意脉冲波形；解析闭合不等于
三维场、传输或质量分辨率资格。反射器的 $\Gamma_3$ 联合控制、T0—T5实验及源到检测器的有限束宽设计
仍见[单次反射 oa-TOF 的联合理论](../../../single_reflection_oa_tof_mass_analyzer/docs/theory/three_zone_accelerator_ideal_theory.md)。

## 2. 坐标、单位和不冲突符号

设源点坐标 $x$ 从排斥极沿提取方向增加，第一场区为 $0<x<\ell_1$。三个场区长度只记为
$\ell_1,\ell_2,\ell_3$，并定义

```math
\ell_{23}=\ell_2+\ell_3,
\qquad
\lambda=\frac{\ell_2}{\ell_{23}},
\qquad 0<\lambda<1.
```

电荷量级记为 $q_e>0$；离子电荷符号由调用方合同独立冻结。沿冻结 affine 相空间主线：

```math
\chi(x)=\chi_c+\beta(x-x_c),
```

```math
\chi_c=v_c\sqrt{\frac{m/q_e}{2}},
\qquad
\beta=\kappa\sqrt{\frac{m/q_e}{2}}.
```

$\chi$ 保留局部提取速度的符号，不能用 $\sqrt{\chi^2}$ 替换。最终单位电荷能量为

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

## 4. affine 源链的局部导数

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

多项式展开系数等于相应原始导数除以阶乘；两者不得混用。这些 $A_n$ 只描述加速器及指定无场
漂移段；下游反射器、多圈镜组或检测器时间不得隐含加入加速器模型。

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

完整cohort必须满足 $\min x_{\rm turn}$ 大于预声明的排斥极间隙余量。所有场强、焦后漂移和有限值
检查同样按调用方阈值fail closed，不得在看到结果后放宽。下游反射器的折返深度是下游独立验收，
不属于加速器穿越条件。

## 6. 第一时间焦面与装配

对标称能量和冻结 affine 主线，用 $A_1^{(3)}(\mathcal W_c)=0$ 解出出口后距离 $D_A$。
在 $p\ne0$ 且正场、完整源穿越的模型域内，这是局部一阶条件；它不保证 $A_2$、$A_3$ 或
有限宽度残差为零。下游无场焦面还要求 $D_A\ge0$，负值不能被解释成出口后的真实焦面。

令局部正提取方向在整机中对应单位向量 $\mathbf n$，声明焦面参考点为 $\mathbf r_f$，则

```math
\mathbf r_{\rm exit}=\mathbf r_f-D_A\mathbf n.
```

其余电极和源位置由同一刚体变换派生；速度只旋转。新项目不固定整机 $z=0$，
也不假定 $\mathbf n=+\hat z$。例如 MR-TOF 指定 $\mathbf n=-\hat z$ 时，
中央焦面前的出口位于正 $z$；单次反射 oa-TOF 的正 $z$ 提取则相反。

场区长度 $\ell_1,\ell_{23},\lambda$ 和电势分配由明确合同提供；等分、继承旧两区总长或某个固定毫米值
都不是理论默认。若用新增边界保持 $E_2=E_3$，则只是同一均匀场的几何分段，不能宣称新增聚焦自由度。

## 7. 参考实现和最低验证

新项目局部模块提供 `AffineSource`、`OuterGeometry`、`ThreeZoneState`、
`derive_three_zone_state`、`derive_first_order_focus_drift`、
`source_energy_per_charge`、`source_coordinate_for_energy` 与
`exact_accelerator_normalized_time`。调用方负责完整源、阈值与下游时间；模块不导入反射器求解器。

最低回归包括：SI时间单位；有符号初速；$E_2=E_3$、$g=0$ 与 $\eta=0$ 到二区的恒等退化；
静止源和零斜率极限；原始导数与Taylor阶乘；精确能量端点/内部驻点；局部反演斜率穿零；
后向折返点；焦面位置有限差分与声明方向的刚体变换。三区/二区结构的资格必须独立验证，
一个变体通过不得自动赋予另一个变体资格。

若局部能量反演失效，位置域精确时间仍可能存在；必须区分数学参数化失效与电极碰撞。
所有粒子和失败行都须保留，不能根据低FWHM或探测命中后筛选源。

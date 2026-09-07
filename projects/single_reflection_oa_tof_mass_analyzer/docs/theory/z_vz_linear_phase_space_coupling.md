# 线性 z–vz 相空间下的 oa-TOF 纵向耦合

> `THEORY_ROLE: KNOWN_PRIOR_ART_CONTEXT / PROJECT_ORACLE`
>
> `PUBLICATION_NOVELTY: NONE_BY_ITSELF`

## 1. 职责与权威边界

加速器局部 affine 源的能量、精确时间、焦距与 $A_1/A_2$ 公式已统一归属独立项目：
[`affine_phase_space_time_focus.md`](../../../orthogonal_accelerator/docs/theory/affine_phase_space_time_focus.md)。
本文只维护这些输出与单次反射 oa-TOF 的下游反射器、源合同及验收的连接，不保存局部公式副本。

当前集成拟合合同由 integration 的 `config/accelerator_phase_space_match.json` 所有。
加速器接口是
[`accelerator_time_focus.py::linear_phase_space_timing_coefficients`](../../../orthogonal_accelerator/analysis/accelerator_time_focus.py)；
反射器接收入口仍是本项目
[`oatof_oaaccelerator_coupling.py::solve_coupled_reflectron_from_accelerator_derivatives`](../../analysis/oatof_oaaccelerator_coupling.py)。

## 2. 源、坐标和焦面连接

源必须取共同 pre-pulse、detector-blind cohort，冻结粒子表、拟合规则、质量电荷、时钟与 SHA。
局部提取速度要先按显式 frame transform 从全局速度投影，不得把任意项目的 `v_z` 列当成加速器正向速度。

下游连接使用独立加速器合同发布的以下记号，而不在本文重算其局部时间：

```math
\chi(x)=\chi+\beta(x-x_c),\qquad
\mathcal W(x)=W(x)+\chi(x)^2.
```

本项目正提取方向与整机 $+z$ 同向，固定一阶时间焦面为 $z=0$ 时，出口为
$z_{A,\mathrm{out}}=-D_A$。$D_A$ 每次由加速器合同重算；不能同时保持旧出口位置与新的焦距。
这一装配关系不适用于提取方向为全局 $-z$ 的 MR-TOF。

## 3. 向反射器传递的系数

设独立加速器发布的原始能量导数为 $A_{1,\mathrm{lin}}$、$A_{2,\mathrm{lin}}$，
反射器及其后续无场路径归一化时间为 $\tau_R$，则整机条件为

```math
A_{1,\mathrm{lin}}+\tau_R'(\mathcal W_c)=0,\qquad
A_{2,\mathrm{lin}}+\tau_R''(\mathcal W_c)=0.
```

$A_1$ 和 $A_2$ 取代静止源的加速器导数，不能再与静止源导数相加。
反射器完整源可达性使用每粒子的实际能量：低能尾必须进入目标第二级，高能尾不得穿底。
公式和求解域仍由[`oatof_oaaccelerator_coupling.md`](oatof_oaaccelerator_coupling.md)定义。

## 4. 随机残差与真实场验收

局部加速器返回的残差时间投影不意味着随机残差可全部补偿或必然不可补偿。
是否存在满足既有约束且与该方向重叠的控制自由度，由
[`conditional_phase_space_focusability.md`](conditional_phase_space_focusability.md)判定。

流程为：冻结 cohort → 局部加速器匹配 → 完整能量包络与导数 → 下游反射器匹配 →
同一粒子表的成对真实场重放。不得用探测器命中重新拟合源斜率，不得从一次质荷比或 RF 相位
外推通用电压，也不得以一阶归零替代二阶、横向耦合、峰形、传输、数值收敛或正式资格。
旧 Formal 与历史证据保持原身份，不因领域代码和文档迁移获得新资格。

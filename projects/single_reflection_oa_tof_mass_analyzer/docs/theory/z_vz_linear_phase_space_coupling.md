# 线性 z–vz 相空间下的 oa-TOF 纵向耦合

> `THEORY_ROLE: KNOWN_PRIOR_ART_CONTEXT / PROJECT_ORACLE`
>
> `PUBLICATION_NOVELTY: NONE_BY_ITSELF`

## 1. 职责与权威边界

本文是“离子进入正交加速器时已有加速方向速度，且该速度与加速坐标线性相关”的公式权威。它扩展
[`oaaccelerator_time_focus.md`](oaaccelerator_time_focus.md)的静止释放模型，并向
[`oatof_oaaccelerator_coupling.md`](oatof_oaaccelerator_coupling.md)提供实际能量及一、二阶时间导数。
基础加速器和反射器推导不在本文重复。

机器合同是integration的`config/accelerator_phase_space_match.json`；实现入口是
`analysis/accelerator_time_focus.py::linear_phase_space_timing_coefficients`和
`analysis/oatof_oaaccelerator_coupling.py::solve_coupled_reflectron_from_accelerator_derivatives`。
项目工作点、实验结果和资格边界不属于本文。

## 2. 实测线性模型

在脉冲前、detector-blind的声明cohort上，以普通最小二乘拟合

```math
v_z(x)=v_c+\kappa(x-x_c)+\varepsilon .
```

其中局部加速坐标$x$以mm计，$v_z$以m/s计，故$\kappa$的单位为m/s/mm。必须冻结输入粒子表、
cohort规则、拟合方法和文件SHA；不得用探测器命中反推斜率。$\varepsilon$是随机残差，不属于
确定性线性修正。

令$m/q$使用SI单位，定义

```math
\chi=v_c\sqrt{\frac{m/q}{2}},\qquad
\beta=\kappa\sqrt{\frac{m/q}{2}}.
```

$\chi$的单位为$\sqrt{\mathrm V}$，$\beta$的单位为$\sqrt{\mathrm V}/\mathrm{mm}$。因此由一个
质荷比拟合得到的匹配电压不能未经重算直接用于其他质荷比。

## 3. 含初速度的加速器时间

设静电能量每电荷为$W(x)=V_R-E_1x$，沿拟合直线定义，并令

```math
\chi(x)=\chi+\beta(x-x_c),\qquad
\mathcal W(x)=W(x)+\chi(x)^2.
S_2=\sqrt{\mathcal W-V_G},\qquad S_3=\sqrt{\mathcal W}.
```

从释放点到距第二场区出口$D_A$的固定焦面，归一化时间和实际时间分别为

```math
\tau_{A,\mathrm{lin}}
=\frac{2[S_2-\chi(x)]}{E_1}
+\frac{2(S_3-S_2)}{E_2}
+\frac{D_A}{S_3}.
t=10^{-3}\sqrt{\frac{m/q}{2}}\,\tau_{A,\mathrm{lin}}.
```

第一项中的$-2\chi(x)/E_1$是静止释放公式没有的项；不能只把$W$换成$\mathcal W$而遗漏它。

沿拟合直线有

```math
\mathcal W'=-E_1+2\chi(x)\beta,\qquad
\mathcal W''=2\beta^2.
```

定义固定$\chi$时对$\mathcal W$的一、二阶导数因子

```math
B_1=
\frac{1}{E_1S_2}
+\frac{1}{E_2}\left(\frac{1}{S_3}-\frac{1}{S_2}\right)
-\frac{D_A}{2S_3^3},
B_2=
-\frac{1}{2E_1S_2^3}
+\frac{1}{2E_2}\left(\frac{1}{S_2^3}-\frac{1}{S_3^3}\right)
+\frac{3D_A}{4S_3^5}.
```

链式求导得到

```math
\tau_x=\mathcal W'B_1-\frac{2\beta}{E_1},\qquad
\tau_{xx}=\mathcal W''B_1+(\mathcal W')^2B_2.
```

固定焦面的一阶匹配条件是$\tau_x(x_c)=0$。等价焦距为

```math
D_{A,\mathrm{lin}}=2S_3^3\left[
\frac{1}{E_1S_2}
+\frac{1}{E_2}\left(\frac{1}{S_3}-\frac{1}{S_2}\right)
-\frac{2\beta}{E_1\mathcal W'}
\right]_{x=x_c}.
```

### 3.1 有限源区的设计层级

完整宽度为$\Delta x$的有限源区仍只使用两个均匀加速场；第二场区内部环线性分压，不作为额外
分段场自由度。设计顺序是：给定$d_1$、$d_2$、名义能量和实测线性关系；选择一级压降；由
$\tau_x(x_c)=0$派生$D_A$；再以完整区间的时间RMS和峰峰宽评价高阶残差。

全局焦面是固定布局合同，$D_A$是理论派生量。若焦面固定于全局$z=0$，则

```math
z_{\mathrm{grid2}}=-D_A,\qquad
z_{\mathrm{grid1}}=-D_A-d_2,\qquad
z_{\mathrm{repeller}}=-D_A-d_2-d_1.
```

只在当前$d_2$不存在可接受解时才最小增加$d_2$；环数只服务均匀场实现和制造间隙。只换电压而不按
派生焦距重构位置，是失配诊断而非该理论候选。加速器对相邻几何只发布编译后的外包络端点，屏蔽罩
不得重复维护其内部尺寸或绝对位置。

## 4. 向反射器传递的系数

以实际能量$\mathcal W$为自变量，加速器传给反射器求解器的系数为

```math
A_{1,\mathrm{lin}}=\frac{\tau_x}{\mathcal W'},\qquad
A_{2,\mathrm{lin}}=
\frac{\tau_{xx}\mathcal W'-\tau_x\mathcal W''}{(\mathcal W')^3}.
```

在$\tau_x=0$的一阶匹配点，第二式化为

```math
A_{2,\mathrm{lin}}
=B_2+\frac{4\beta^3}{E_1(\mathcal W')^3}.
```

固定反射器几何时，全机条件为

```math
A_{1,\mathrm{lin}}+\tau_R'(\mathcal W_c)=0,\qquad
A_{2,\mathrm{lin}}+\tau_R''(\mathcal W_c)=0.
```

$A_1$和$A_2$取代静止源导数，不能再与静止源导数相加，否则会重复计算加速器时间。

## 5. 能量包络与随机残差

反射器可达性必须使用每个cohort粒子的实际能量：

```math
\mathcal W_i=V_R-E_1x_i+\frac{m}{2q}v_{z,i}^{2},\qquad
\mathcal W_{\min}=\min_i\mathcal W_i,\qquad
\mathcal W_{\max}=\max_i\mathcal W_i.
```

低能尾必须进入第二级，高能尾不得穿底。线性拟合残差引起的一级时间扰动近似为

```math
\delta\tau_A\approx
\left(2\chi B_1-\frac{2}{E_1}\right)
\sqrt{\frac{m/q}{2}}\,\varepsilon.
```

该项不能靠重新拟合或单独改变确定性斜率$\kappa$而消失。分析器控制若在保持既有约束后仍有与该
残差时间方向重叠的可行方向，可以降低其投影；否则才应优化上游稳态束或建立受证据约束的非线性
相空间模型。能否补偿必须由条件协方差和
[`conditional_phase_space_focusability.md`](conditional_phase_space_focusability.md)的控制子空间判据决定，
不能从“随机残差”这一名称直接推出不可聚焦。

## 6. 真实场校正与验收

理论流程依次冻结cohort、拟合线性关系、反算加速器、计算能量包络与$A_1/A_2$、反算反射器，再用
同一粒子表做成对真实场重放。真实场校正只能在此后进行，不能反向改写理论。

端点为零的内部环三次形状项可写为

```math
\Delta V(f)=C_3f(1-f)(2f-1),\qquad 0\le f\le1.
```

$C_3$是工程校正自由量，不是理论派生量。实际三维场的一阶验收量是在同一detector-blind队列中拟合
$t=a+b_zz+b_vv_z$，再沿$v_z=v_c+\kappa(z-z_c)$计算$b_z+\kappa b_v$。将该斜率归零只闭合
一阶方向；仍须检查二阶项、非线性场、横向耦合、随机残差、峰模态和直接FWHM。

## 7. 禁止性结论

- 不得用探测器命中筛选拟合$\kappa$。
- 不得把名义静电能量与$mv_z^2/(2q)$重复相加。
- 不得把线性相关解释成零残差、零角散或三维理想束。
- 不得把一次质荷比或RF相位的拟合电压外推为通用电压。
- 不得用一阶斜率归零替代峰形、传输、数值收敛或Candidate/Formal资格。

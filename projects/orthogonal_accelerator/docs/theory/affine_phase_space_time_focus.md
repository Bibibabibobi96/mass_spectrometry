# 线性位置—速度相空间下的双区正交加速器时间聚焦

> `THEORY_ROLE: KNOWN_PRIOR_ART_CONTEXT / PROJECT_ORACLE`
>
> `PUBLICATION_NOVELTY: NONE_BY_ITSELF`

## 1. 职责与权威边界

本文维护有符号初始提取速度与局部位置线性相关时的双区加速器时间模型，扩展
[`oaaccelerator_time_focus.md`](oaaccelerator_time_focus.md)的静止释放模型。它只计算加速器至声明
观察面的时间、实际能量与导数，不解反射器或整机检测时间。

参考实现为独立项目的
[`accelerator_time_focus.py`](../../analysis/accelerator_time_focus.py)，其中
`linear_phase_space_timing_coefficients`发布实际能量及一、二阶导数。
源的采样、拟合与阈值由调用方合同冻结；工作点、结果和资格见各项目的 PROJECT。
单次反射 oa-TOF 的具体连接见其
[`z_vz_linear_phase_space_coupling.md`](../../../single_reflection_oa_tof_mass_analyzer/docs/theory/z_vz_linear_phase_space_coupling.md)。

## 2. 实测线性模型

在脉冲前、detector-blind的声明cohort上，以普通最小二乘拟合

```math
v_z(x)=v_c+\kappa(x-x_c)+\varepsilon .
```

其中局部加速坐标$x$以mm计，$v_z$沿局部正提取方向、以m/s计，故$\kappa$的单位为m/s/mm。
这里的$x$与$v_z$沿用解析记号，不是整机全局轴标签。必须冻结输入粒子表、
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
```

```math
S_2=\sqrt{\mathcal W-V_G},\qquad S_3=\sqrt{\mathcal W}.
```

从释放点到距第二场区出口$D_A$的固定焦面，归一化时间和实际时间分别为

```math
\tau_{A,\mathrm{lin}}
=\frac{2[S_2-\chi(x)]}{E_1}
+\frac{2(S_3-S_2)}{E_2}
+\frac{D_A}{S_3}.
```

```math
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
-\frac{D_A}{2S_3^3}.
```

```math
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

焦面是调用方的布局合同，$D_A$是理论派生量。仅在局部提取方向与装配$+z$同向且目标焦面为$z=0$时，才有

```math
z_{\mathrm{grid2}}=-D_A,\qquad
z_{\mathrm{grid1}}=-D_A-d_2,\qquad
z_{\mathrm{repeller}}=-D_A-d_2-d_1.
```

只在当前$d_2$不存在可接受解时才最小增加$d_2$；环数只服务均匀场实现和制造间隙。只换电压而不按
派生焦距重构位置，是失配诊断而非该理论候选。加速器对相邻几何只发布编译后的外包络端点，屏蔽罩
不得重复维护其内部尺寸或绝对位置。

## 4. 向下游模型传递的系数

以实际能量$\mathcal W$为自变量，加速器发布的原始导数系数为

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

下游模型可以把这些系数与自身的时间导数相加，但不得再叠加静止源的加速器导数，否则会重复计时。
局部能量斜率 $\mathcal W'=0$ 时上述能量域导数不适用，必须失败关闭或显式转用位置域模型，
不能据此把真实粒子标成物理损失。

## 5. 能量包络与随机残差

加速器完整穿越和下游可达性必须使用每个cohort粒子的实际能量：

```math
\mathcal W_i=V_R-E_1x_i+\frac{m}{2q}v_{z,i}^{2},\qquad
\mathcal W_{\min}=\min_i\mathcal W_i,\qquad
\mathcal W_{\max}=\max_i\mathcal W_i.
```

加速器域先检查每粒子是否穿过各场区；下游反射器的低能进入级与高能穿底约束属于下游合同。
线性拟合残差引起的一级时间扰动近似为

```math
\delta\tau_A\approx
\left(2\chi B_1-\frac{2}{E_1}\right)
\sqrt{\frac{m/q}{2}}\,\varepsilon.
```

该项不能靠重新拟合或单独改变确定性斜率$\kappa$而消失。分析器控制若在保持既有约束后仍有与该
残差时间方向重叠的可行方向，可以降低其投影；否则才应优化上游稳态束或建立受证据约束的非线性
相空间模型。能否补偿必须由条件协方差和
单次反射 oa-TOF 的[`条件相空间可聚焦性`](../../../single_reflection_oa_tof_mass_analyzer/docs/theory/conditional_phase_space_focusability.md)控制子空间判据决定，
不能从“随机残差”这一名称直接推出不可聚焦。

## 6. 真实场校正与验收

理论流程依次冻结cohort、拟合线性关系、反算加速器、计算能量包络与$A_1/A_2$，再由调用方完成
下游匹配并用同一粒子表做成对真实场重放。真实场校正不能反向改写理论。

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

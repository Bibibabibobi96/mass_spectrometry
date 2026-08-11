# 线性 `z-v_z` 相空间下的 oa-TOF 纵向耦合

## 1. 职责与权威边界

本文是“离子进入正交加速器时已有轴向速度，且该速度与加速坐标相关”的公式权威。它扩展
`oaaccelerator_time_focus.md` 的静止释放假设，并向
`oatof_oaaccelerator_coupling.md` 提供实际能量及一、二阶时间导数。基础加速器符号和反射器
公式仍由上述两份文档拥有，本文不复制其完整推导。

机器合同唯一入口是集成项目的
`config/accelerator_phase_space_match.json`；当前实现入口是
`analysis/accelerator_time_focus.py::linear_phase_space_timing_coefficients` 与
`analysis/oatof_oaaccelerator_coupling.py::solve_coupled_reflectron_from_accelerator_derivatives`。
文档中的示例数值不是参数权威。

## 2. 实测线性模型

在脉冲前、且不使用探测器结果筛选的可提取 cohort 上，以普通最小二乘拟合

```math
v_z(x)=v_c+\kappa(x-x_c)+\varepsilon .
```

其中 `x` 是正交加速方向的局部坐标，单位 mm；`v_z` 单位 m/s，故 `κ` 单位
m/s/mm。必须冻结输入粒子表、cohort 规则、拟合方法及文件 SHA。残差 `ε` 不能并入确定性
斜率，也不能从已经到达探测器的粒子反推。

令 `m/q` 使用 SI 单位，则

```math
\chi=v_c\sqrt{\frac{m/q}{2}},\qquad
\beta=\kappa\sqrt{\frac{m/q}{2}} .
```

`χ` 的单位是 `sqrt(V)`，`β` 的单位是 `sqrt(V)/mm`。因此该修正随质荷比变化；用
100 Th 拟合得到的电压不能未经重算直接声明适用于其他质荷比。

## 3. 含初速度的加速器时间

设静电贡献为 `W(x)=V_R-E_1x`，离子实际能量每电荷为

```math
\mathcal W(x)=W(x)+\chi(x)^2,
\qquad \chi(x)=\chi+\beta(x-x_c).
```

记 `S_2=sqrt(\mathcal W-V_G)`、`S_3=sqrt(\mathcal W)`。从释放点到固定焦面
`D_A` 的归一化时间为

```math
\tau_{A,\mathrm{lin}}
=\frac{2(S_2-\chi)}{E_1}
+\frac{2(S_3-S_2)}{E_2}
+\frac{D_A}{S_3}.
```

实际时间仍为
`t=10^{-3} sqrt((m/q)/2) tau`。第一项中的 `-2χ/E_1` 是静止释放公式没有的项，
不能只把 `W` 替换为 `mathcal W` 后忽略它。

沿拟合直线的能量位置导数为

```math
\mathcal W'=-E_1+2\chi\beta,
\qquad
\mathcal W''=2\beta^2.
```

定义固定 `χ` 时对实际能量的一阶、二阶导数

```math
B_1=
\frac{1}{E_1S_2}
+\frac{1}{E_2}\left(\frac{1}{S_3}-\frac{1}{S_2}\right)
-\frac{D_A}{2S_3^3},
```

```math
B_2=
-\frac{1}{2E_1S_2^3}
+\frac{1}{2E_2}\left(\frac{1}{S_2^3}-\frac{1}{S_3^3}\right)
+\frac{3D_A}{4S_3^5}.
```

链式求导给出

```math
\tau_x=\mathcal W'B_1-\frac{2\beta}{E_1},
\qquad
\tau_{xx}=\mathcal W''B_1+(\mathcal W')^2B_2.
```

因此固定焦面的一级电压反算条件是 `tau_x(x_c)=0`。等价的焦距表达式为

```math
D_{A,\mathrm{lin}}=2S_3^3\left[
\frac{1}{E_1S_2}
+\frac{1}{E_2}\left(\frac{1}{S_3}-\frac{1}{S_2}\right)
-\frac{2\beta}{E_1\mathcal W'}
\right]_{x_c}.
```

当前流程固定几何、出口电压、名义静电能量和焦面，只反算 repeller/grid1 电压；默认值仍由
oaTOF 几何合同提供。

## 4. 向反射器传递的一、二阶系数

反射器以实际能量 `mathcal W` 为自变量。加速器传给反射器求解器的系数是

```math
A_{1,\mathrm{lin}}=\frac{\tau_x}{\mathcal W'},
\qquad
A_{2,\mathrm{lin}}=
\frac{\tau_{xx}\mathcal W'-\tau_x\mathcal W''}{(\mathcal W')^3}.
```

在一级匹配点 `tau_x=0`，第二式可写成

```math
A_{2,\mathrm{lin}}=
B_2+\frac{4\beta^3}{E_1(\mathcal W')^3}.
```

随后保持反射器几何不变，由全机条件反算一级压降 `U_R1` 和二级场 `F_2`：

```math
A_{1,\mathrm{lin}}+\tau_R'(\mathcal W_c)=0,
\qquad
A_{2,\mathrm{lin}}+\tau_R''(\mathcal W_c)=0.
```

这里的 `A_1/A_2` 取代静止源导数，而不是附加在静止源导数上；否则会重复计算加速器时间。

## 5. 能量包络与残差

反射器可达性必须使用每个 cohort 粒子的实际能量，而不是只用名义能量加对称半宽：

```math
\mathcal W_i=
V_R-E_1x_i+\frac{m}{2q}v_{z,i}^{,2},
\qquad
\mathcal W_{\min}=\min_i\mathcal W_i,
\quad
\mathcal W_{\max}=\max_i\mathcal W_i.
```

必须同时满足低能尾进入第二级和高能尾不穿底。线性拟合残差带来的一级时间噪声近似为

```math
\delta\tau_A\approx
\left(2\chi B_1-\frac{2}{E_1}\right)
\sqrt{\frac{m/q}{2}}\,\varepsilon .
```

该项不能靠调整 `κ` 消除；当它成为主导项时，应优化上游稳态束或使用受证据约束的非线性
相空间模型。

## 6. 可执行流程与校正边界

受治理流程依次执行：冻结脉冲前 eligible cohort；做 detector-blind OLS；固定焦面反算加速器
电压；计算实际能量包络与 `A_1/A_2`；固定反射器几何反算 `V_mid/V_backplate`；用同一粒子表
做成对 SIMION replay；最后才允许用真实场校正项微调。

真实场校正不改变理论权威。当前内部环三次形状项为

```math
\Delta V(f)=C_3 f(1-f)(2f-1),\qquad 0\leq f\leq1,
```

它保持两端电压不变，只修正实际三维边缘场；`C_3` 是自由校正变量，不是理论派生量。
同一449粒子的离散扫描中，`C3=-160,-80,0,+80,+160 V`对应
`R=16928,19399,22307,24639,24961`；继续增至`240,320,400,480 V`后依次降为
`23677,21589,19488,17672`。所以160 V只是已测试离散点的最佳候选，不是精确连续最优值。

2026-08-12 的 N=1000 母样本（eligible 449）成对验证中：当前基准 `R=18528`；线性耦合
`R=22159`；线性耦合叠加 `C_3=160 V` 后 `R=24826`，三臂均为 449/449 到达探测器。
此前“加速器一级匹配 + 原反射器 + C3=160 V”为 `R≈24961`。因此当前证据支持线性理论已
正确接入并显著优于基准，但不支持“理想一维二阶反算值就是实际三维场最终最优值”。正式采用
仍需理论工作点附近的受治理实际场校正及完整连续注入 N=1000 确认。

实际三维场的一阶验收量不是理论 `tau_x` 本身，而是同一 detector-blind 源队列中对
`t=a+b_z z+b_v v_z` 的最小二乘拟合，再沿实测 `v_z=v_c+k(z-z_c)` 计算
`b_z+k b_v`。`actual_slope` 阶段用电压降偏置和端点为零的内部环形状项校准该量。
449 粒子的最终点 `C3=200 V`、一级电压降偏置 `+19.8 V` 得到
`b_z+k b_v=+0.00249 ns/mm`，相对原真实场 `-2.60036 ns/mm` 的绝对值降低 99.90%。
但该点为双峰、`R=13239`，低于原单峰 `R=18528`；因此一阶归零只是诊断约束，不能取代
对二阶/非线性场、横向耦合和随机速度残差的总峰宽优化。

## 7. 禁止性结论

- 不得用探测器命中筛选拟合 `κ`。
- 不得把名义静电能量与 `m v_z^2/(2q)` 重复相加。
- 不得把 `z-v_z` 线性相关解释成零残差、零角散或三维理想束。
- 不得把一次质荷比、一次 RF 相位的拟合电压外推成通用电压。
- 不得仅凭本模型升级 Candidate、Formal 或数值收敛状态。

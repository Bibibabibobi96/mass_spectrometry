---
description: 原 Astral 方案的绝热漂移作用量、有效赝势、Ion Foil/Stripe、镜面收敛、无量纲优化、空间聚焦和时间像差补偿。
keywords:
  - adiabatic invariant
  - drift pseudopotential
  - Ion Foil
  - stripe electrode
  - mirror convergence
  - kappa
  - tau
document_id: astral_replication.adiabatic_drift_original
version: 1.0.0
maturity: reference
---

# 绝热漂移与原 Astral Ion Foil 理论

Astral 的核心不是让离子在一条狭窄通道中始终分开，而是允许离子束在大部分飞行过程中显著展开，在漂移转折后重新收敛，并在探测端恢复单一空间束团和窄时间前沿。这个过程依赖“快轴向振荡 + 慢纵向漂移”的尺度分离。

本文件只讨论原论文的“形状化 Stripe/Ion Foil + 轻微镜面收敛”方案。平行镜双 Stripe 新方案见 [`dual_stripe_non_tilt_design.md`](./dual_stripe_non_tilt_design.md)。

## 1. 快运动和慢运动

离子以小角度 $\vartheta$ 注入两镜之间。总能量分解为

$$
\varepsilon_z
=
\varepsilon_0\cos^2\vartheta
\approx\varepsilon_0,
$$

$$
\varepsilon_y
=
\varepsilon_0\sin^2\vartheta
\ll\varepsilon_0.
$$

其中：

- $\varepsilon_z$ 支配 $z$ 向快速振荡；
- $\varepsilon_y$ 支配 $y$ 向慢漂移；
- $x$ 向运动由镜的横向聚焦控制。

使用能量/电荷：

$$
w_0=\frac{\varepsilon_0}{q},
\qquad
w_{y0}=w_0\sin^2\vartheta_0.
$$

$w_{y0}$ 通常只有标称加速电压的一小部分，因此漂移控制器只需要低压电极，但其时间像差要求非常严格。

## 2. 随漂移坐标变化的轴向作用量

加入缓慢变化的扰动势 $\delta\varphi(x,y,z)$ 后，一次轴向振荡的作用量为

$$
\begin{aligned}
J(\varepsilon_z,y)
&=
J_0(\varepsilon_z)
+
\Delta J(\varepsilon_z,y)\\
&=
\sqrt{8m}
\int_{z_1^*(\varepsilon_z,y)}^{z_2^*(\varepsilon_z,y)}
\sqrt{
\varepsilon_z
-q\varphi_0(z)
-q\delta\varphi(0,y,z)
}
\,\mathrm dz.
\end{aligned}
$$

这里 $z_1^*$ 和 $z_2^*$ 是受扰动后的转折点。

当 $y$ 在一次轴向振荡内变化很小，轴向作用量近似为绝热不变量：

$$
\frac{\partial J}{\partial y}\Delta y
+
\frac{\partial J}{\partial\varepsilon_z}\Delta\varepsilon_z
=0.
$$

总能量守恒给出

$$
\Delta\varepsilon_y+\Delta\varepsilon_z=0.
$$

二者联立：

$$
\frac{\Delta\varepsilon_y}{\Delta y}
=
\frac{\partial_y\Delta J}
{T_0+\Delta T(y)}
\approx
\frac{\partial_y\Delta J}{T_0}.
$$

其中

$$
\Delta T(y)
=
\left.
\frac{\partial\Delta J}{\partial\varepsilon}
\right|_{\varepsilon_0}
$$

是扰动导致的单周期时间变化。

## 3. 有效漂移赝势

定义

$$
\Phi(y)
=
-\frac{\Delta J(\varepsilon_0,y)}{qT_0},
$$

则慢漂移方程变为

$$
\frac{\Delta\varepsilon_y}{\Delta y}
\approx
-q\Phi'(y).
$$

$\Phi$ 的单位是伏特。它是由“每个轴向周期的作用量变化”定义的有效势，不等于某个空间点的静电势。

### 3.1 赝势的任意常数

若

$$
\Phi(y)\rightarrow\Phi(y)+\Phi_c,
$$

漂移力 $-q\Phi'(y)$ 不变，转折条件中的势差也不变。因此漂移动力学只依赖 $\Phi(y)-\Phi(0)$。

但常数项会改变单周期共同时间和能量导数，必须在完整镜校准中保留，不能在最终 ToF 模型中随意删除。

## 4. 漂移反转和返回时间

若 $\Phi(y)$ 为阻滞型，漂移转折点 $y_D$ 满足

$$
\Phi(y_D)-\Phi(0)
=
w_0\sin^2\vartheta.
$$

较大的注入角具有较高漂移动能，因而通常漂移更远。

从 $y=0$ 到 $y_D$ 再返回的时间为

$$
T_D(\vartheta)
=
\sqrt{\frac{2m}{q}}
\int_0^{y_D}
\frac{\mathrm dy}
{\sqrt{\Phi(y_D)-\Phi(y)}}.
$$

轴向完整振荡次数估计为

$$
K
=
\operatorname{round}\!\left(\frac{T_D}{T_0}\right).
$$

为避免不同 $K$ 的离子形成多重谱峰，整个角度接受区至少应满足

$$
K-\frac12
<
\frac{T_D(\vartheta)}{T_0}
<
K+\frac12.
$$

这个条件只约束振荡拓扑。实际还必须检查：

- 探测器有效面积；
- 最终束宽；
- 不同振荡轨迹在探测区是否重叠；
- 棱镜、源和支撑件的机械避让；
- 真实事件计数是否为唯一 $K$。

## 5. 漂移引起的时间偏移

总飞行时间不是简单的 $K T_0$。扰动在每个振荡上引入 $\Delta T(y)$，因此

$$
\Delta T_K(y_D)
=
\sum_{k=0}^{K-1}
\Delta T\!\left(y(kT_0)\right).
$$

在慢变化近似下，离散求和可写成

$$
\Delta T_K(y_D)
\approx
\frac{\sqrt{2m/q}}{T_0}
\int_0^{y_D}
\frac{
\left.\partial_\varepsilon\Delta J(\varepsilon,y)\right|_{\varepsilon_0}
}
{\sqrt{\Phi(y_D)-\Phi(y)}}
\,\mathrm dy.
$$

这揭示两个不同目标：

- **空间返回**取决于 $\Delta J(\varepsilon_0,y)$；
- **时间像差**取决于 $\partial_\varepsilon\Delta J(\varepsilon_0,y)$。

只匹配标称漂移轨迹，不能自动保证时间等时性。

## 6. 初始漂移坐标的对称性

对具有相同注入角和相同转折点的两粒子，若初始坐标分别为 $+y_0$ 和 $-y_0$，它们在完整去程–返程中经历同一条路径但方向相反。因此时间偏移是 $y_0$ 的偶函数：

$$
\Delta T_K(y_0)
=
\Delta T_K(-y_0).
$$

最低阶依赖不强于

$$
\Delta T_K(y_0)-\Delta T_K(0)
\propto y_0^2.
$$

这解释了为什么完整返回后，不同初始 $y$ 位置但相同角度的时间前沿可以重新对齐。中间反射处的时间前沿仍可能倾斜。

## 7. Stripe/Ion Foil 的作用量响应

### 7.1 硬边界模型

设离子在每次轴向振荡中，有总长度 $S(y)$ 的路径位于偏压 $v_s$ 的近常势区，其余路径位于参考电位。精确作用量扰动为

$$
\Delta J_s(\varepsilon,y)
=
\sqrt{8m}
\left[
\sqrt{\varepsilon-qv_s}
-
\sqrt{\varepsilon}
\right]
S(y).
$$

当

$$
|qv_s|\ll\varepsilon,
$$

可展开为

$$
\Delta J_s(\varepsilon,y)
\approx
-qv_s\sqrt{\frac{2m}{\varepsilon}}S(y).
$$

对应漂移赝势为

$$
\Phi_s(y)
=
-\frac{\Delta J_s(\varepsilon_0,y)}{qT_0}
\approx
\frac{v_s}{W}S(y),
$$

其中

$$
W=T_0\sqrt{\frac{\varepsilon_0}{2m}}.
$$

### 7.2 物理图像

离子进入和离开偏置区域时发生静电折射。通过让偏置区域的轴向长度 $S(y)$ 随漂移坐标变化，可在每次振荡上逐步改变漂移角。

真实 Ion Foil 需要：

- 一对位于离子轨迹两侧的偏置板；
- 与其互补的接地板；
- 足够小但不截束的板间距离；
- 平滑的 $S(y)$；
- 中央接地区域以容纳转向棱镜；
- 有限厚度、边缘和支撑的三维场模型。

## 8. 镜面收敛的作用量响应

若两镜沿 $y$ 方向以小角度 $\Theta$ 相向收敛，无场轴向距离随 $y$ 缩短：

$$
\Delta z=-y\tan\Theta.
$$

从作用量中移除这段无场路径：

$$
\Delta J_m(\varepsilon,y)
=
-\sqrt{8m\varepsilon}\,y\tan\Theta.
$$

对应漂移赝势为

$$
\Phi_m(y)
=
\frac{2w_0\tan\Theta}{W}y.
$$

空间上，可把它理解为每两次连续反射使漂移角约减少 $2\Theta$。时间上，路径缩短使轴向振荡更快。

## 9. 为什么空间是“和”，时间是“差”

总漂移赝势：

$$
\Phi(y)=\Phi_s(y)+\Phi_m(y).
$$

因此两种机制共同提供漂移返回力。

但它们的能量响应不同：

$$
\Delta J_s\propto\varepsilon^{-1/2},
\qquad
\Delta J_m\propto-\varepsilon^{+1/2}.
$$

所以

$$
\frac{\partial\Delta J_s}{\partial\varepsilon}
\approx
-\frac{\Delta J_s}{2\varepsilon},
$$

$$
\frac{\partial\Delta J_m}{\partial\varepsilon}
=
\frac{\Delta J_m}{2\varepsilon}.
$$

代入时间偏移后，得到

$$
\frac{\Delta T_K}{T_0}
=
\frac{1}{2W\sqrt{w_0}}
\int_0^{y_D}
\frac{
\Phi_s(y)-\Phi_m(y)
}
{\sqrt{
\Phi_s(y_D)+\Phi_m(y_D)
-
\Phi_s(y)-\Phi_m(y)
}}
\,\mathrm dy.
$$

因此：

- 返回势使用 $\Phi_s+\Phi_m$；
- 时间补偿使用 $\Phi_s-\Phi_m$。

这是原 Astral 能同时实现空间返回和宽时间平台的关键。

## 10. 无量纲化

定义标称漂移长度

$$
L=y_D(\vartheta_0),
$$

无量纲坐标

$$
\eta=\frac{y}{L},
$$

以及标称漂移动能/电荷

$$
w_{y0}=w_0\sin^2\vartheta_0.
$$

归一化赝势为

$$
\psi(\eta)
=
\frac{\Phi_s+\Phi_m}{w_{y0}}
=
\psi_s(\eta)+\psi_m(\eta).
$$

原论文选择

$$
\psi_m(\eta)=c_0\eta,
$$

$$
\psi_s(\eta)
=
c_1\eta
+c_2\eta^2
+c_3\eta^3
+c_4\eta^4
+c_5\eta^5.
$$

## 11. $\kappa$ 和 $\tau$ 函数

漂移返回时间写为

$$
\frac{T_D}{T_0}
=
\frac{L}{W\sin\vartheta_0}
\kappa(\eta_D),
$$

$$
\kappa(\eta_D)
=
\int_0^{\eta_D}
\frac{\mathrm d\eta}
{\sqrt{\psi(\eta_D)-\psi(\eta)}}.
$$

时间偏移写为

$$
\frac{\Delta T_K}{T_0}
=
\frac{L\sin\vartheta_0}{2W}
\tau(\eta_D),
$$

$$
\tau(\eta_D)
=
\int_0^{\eta_D}
\frac{
\psi_s(\eta)-\psi_m(\eta)
}
{\sqrt{\psi(\eta_D)-\psi(\eta)}}
\,\mathrm d\eta.
$$

$\eta_D=y_D/L$ 由注入角决定。

## 12. 原论文的六个优化约束

六个未知量 $c_0,\ldots,c_5$ 由六类约束确定：

1. 在 $\eta_D=1\pm0.1$ 区间的四个节点，使 $\tau$ 对 $\eta_D$ 的导数为零；
2. 空间一阶聚焦：

$$
\kappa'(1)=0;
$$

3. 标称转折长度归一化：

$$
\psi(1)=c_0+c_1+c_2+c_3+c_4+c_5=1.
$$

论文没有在主文中公开四个节点的精确值。若项目重新求解，应把节点、权重和精度作为机器合同保存，不能把自行选择的节点称为论文原始节点。

## 13. 公开无量纲系数

论文给出：

$$
\begin{aligned}
c_0&=0.83999,\\
c_1&=0.75160,\\
c_2&=-7.52535,\\
c_3&=14.0242,\\
c_4&=-9.17661,\\
c_5&=2.08613.
\end{aligned}
$$

印刷舍入后

$$
\sum_{k=0}^{5}c_k=0.99996,
$$

不严格等于 1。高精度计算应：

- 使用印刷值做论文回归；
- 或重新求解并保存未舍入系数；
- 不要手工把某个系数改到“刚好求和为 1”而不重新满足其他约束。

## 14. 从无量纲解到工程参数

### 14.1 注入角

标称工作点满足

$$
K
=
\frac{L}{W\sin\vartheta_0}\kappa(1),
$$

所以

$$
\vartheta_0
=
\arcsin\!\left[
\frac{\kappa(1)L}{KW}
\right].
$$

### 14.2 镜面收敛角

由 $\psi_m(1)=c_0$：

$$
\Theta
=
\arctan\!\left[
\frac{c_0W\sin^2\vartheta_0}{2L}
\right].
$$

### 14.3 Stripe 形状

$$
S(y)
=
S_0
+
S_1
\left[
 c_1\frac yL
+c_2\left(\frac yL\right)^2
+c_3\left(\frac yL\right)^3
+c_4\left(\frac yL\right)^4
+c_5\left(\frac yL\right)^5
\right].
$$

### 14.4 Stripe 偏压

在小偏压近似下：

$$
v_s
=
\frac{Ww_0\sin^2\vartheta_0}{S_1}.
$$

$S_1$ 可以为负，随之 $v_s$ 也可为负。实际几何必须满足 $S(y)>0$ 并留出机械间隙。

## 15. $S_0$ 的作用

$S_0$ 是 Stripe 在 $z$ 方向的常数基线长度。

在理想慢漂移模型中，$S_0$ 只给 $\Phi_s$ 增加常数，因此：

- 不改变 $\Phi'(y)$；
- 不改变转折位置和漂移力；
- 不改变势差形式的 $\kappa$。

但它会改变：

- 每周期的共同时间；
- 作用量对能量的导数；
- 原镜三点等时条件；
- 中央接地板和棱镜的可包装性；
- 真实边缘场。

因此 $S_0$ 由工程包装和全局时间校准共同决定，不能由 $\psi(1)=1$ 单独求出。

## 16. 中央接地板和棱镜区

论文图示把偏置 Stripe 分成位于中央接地走廊两侧的两部分，每部分轴向长度为 $S(y)/2$。中央区域用于布置转向棱镜并保持近无场。

这意味着：

- $S(y)$ 是偏置区的总轴向长度，不是离子沿 $y$ 第一次遇到电极的位置；
- $S(0)=S_0$ 不等于“离子在注入点立即经历完整偏压”；
- 首次实际折射位置必须由三维电极边界确定；
- 中央接地板、棱镜和 Stripe 边缘场必须在同一模型中求解。

## 17. 公开工程基准

原论文公开：

| 量 | 值 |
|---|---:|
| $L$ | $335\ \mathrm{mm}$ |
| $W$ | $641\ \mathrm{mm}$ |
| $w_0$ | $4000\ \mathrm{V}$ |
| $K$ | $25$ |
| $\vartheta_0$ | $1.78^\circ$ |
| $\Theta$ | $0.045^\circ$ |
| $v_s$ | $-13.8\ \mathrm{V}$ |
| 路径 $2KW$ | 约 $32\ \mathrm m$ |

用印刷系数进行端点正则化积分，可得到约

$$
\kappa(1)\approx1.48923,
$$

进而复算

$$
\vartheta_0\approx1.784^\circ,
$$

$$
\Theta\approx0.0446^\circ.
$$

这些是公式一致性基准，不是三维性能预测。

## 18. 端点正则化

$\kappa$ 和 $\tau$ 在 $\eta\rightarrow\eta_D$ 处存在可积平方根奇异。推荐变换

$$
\eta=\eta_D-u^2,
\qquad
0\le u\le\sqrt{\eta_D}.
$$

则

$$
\kappa(\eta_D)
=
\int_0^{\sqrt{\eta_D}}
\frac{2u\,\mathrm du}
{\sqrt{
\psi(\eta_D)-\psi(\eta_D-u^2)
}}.
$$

$\tau$ 同理。

不要通过把积分上限改为 $0.999\eta_D$ 来规避奇异；这种截断会产生依赖参数的系统误差，尤其会污染 $\kappa'$ 和 $\tau'$。

## 19. 绝热近似的适用条件

原论文只给出“$\delta\varphi$ 足够平滑”的条件。工程上应通过以下量验证，而不是套用固定阈值：

### 19.1 相邻周期作用量漂移

$$
\epsilon_J
=
\max_n
\left|
\frac{J_{n+1}-J_n}{J_n}
\right|.
$$

### 19.2 每周期漂移步长

$$
\Delta y_n
=
y_{n+1}-y_n.
$$

它应远小于 $S(y)$、$\Phi(y)$ 和其曲率的变化尺度。

### 19.3 直接轨迹对照

比较：

- 赝势方程预测的 $y_n$；
- 完整三维轨迹的 Poincaré 点；
- 赝势转折点与实际转折点；
- 赝势返回时间与实际返回时间。

只有在网格、时间步和电极边缘逐步精化后误差稳定，才能确认绝热模型可用于该几何。

## 20. 容易犯错的地方

1. **把静电势当漂移赝势**：$\Phi$ 来自作用量，不是局部 $\delta\varphi$。
2. **只匹配 $\Phi$ 不匹配 $\partial_\varepsilon\Delta J$**：会得到空间焦点但时间展宽很大。
3. **把 $K$ 的中心公式当全束保证**：必须扫描完整角度和空间分布。
4. **认为不同振荡轨迹始终不能重叠**：原 Astral 允许中途实空间重叠，关键是最终恢复可选择探测。
5. **认为 $S_0$ 由归一化条件决定**：$S_0$ 是工程基线，不是 $c_0$。
6. **用印刷舍入系数要求机器零残差**：需区分论文回归和重新优化。
7. **忽略 Stripe 的精确有限偏压响应**：高偏压时应使用平方根精确式。
8. **形状中出现尖角或不连续斜率**：会破坏慢变化近似并产生边缘透镜。
9. **改变 $L$ 后只拉伸电极，不重新验证三维接口**：中央棱镜、探测器和端部不会自动相似缩放。
10. **把镜倾斜产生的线性赝势等同于任意线性电极的全部时间响应**：两者的能量尺度不同。

## 21. 最低参考测试

| 测试 | 内容 |
|---|---|
| 作用量绝热性 | 相邻周期 $J$ 漂移随形状平滑化而减小 |
| 赝势力 | 完整轨迹的 $\Delta\varepsilon_y/\Delta y$ 与 $-q\Phi'$ 一致 |
| 转折点 | 势差与初始漂移动能一致 |
| 返回时间 | 赝势积分与直接轨迹一致 |
| $K$ 唯一性 | 全粒子振荡事件数只有目标值 |
| $\kappa'(1)$ | 多种导数步长一致并接近目标 |
| 时间平台 | $\tau$ 在规定区间内的极差满足预算 |
| 端点正则化 | 两种正则化和高精度积分一致 |
| $S_0$ 测试 | 改变基线时漂移轨迹不变，但全局周期按模型变化 |
| 三维场对照 | 硬边界作用量、二维场和三维场的误差被记录 |

## 22. 主要来源

- D. Grinfeld et al., *Nuclear Instruments and Methods in Physics Research A* 1060 (2024) 169017. DOI: `10.1016/j.nima.2023.169017`.
- H. Stewart et al., “Crowd Control of Ions in the Astral Analyzer,” ChemRxiv. DOI: `10.26434/chemrxiv-2023-p6zln`.

---
description: Astral 类五电极无栅格等时离子镜的完整理论、解析场模型、周期等时性、横向稳定性、像差优化、校准接口和复现步骤。
keywords:
  - isochronous ion mirror
  - gridless reflectron
  - action integral
  - Poincare map
  - symplectic map
  - temporal aberration
  - BEM
document_id: astral_replication.isochronous_mirror
version: 1.0.0
maturity: reference
---

# Astral 类无栅格等时离子镜设计

本文件说明如何从物理目标出发，建立和优化 Astral 类五电极伸长离子镜。镜设计不是单纯的“让离子反射”，而是同一组几何和电压同时完成：

1. $z$ 向反射；
2. $x$ 向稳定与聚焦；
3. 振荡周期对能量的高阶等时；
4. 振荡周期对横向相空间的低像差；
5. 为后续 $y$ 向绝热漂移提供稳定的周期 $T_0$ 和有效长度 $W$。

> **实现边界**：论文公开了拓扑、方程、优化条件和公开性能图，但没有公开完整电极宽度、间隙、厚度、端部修正器和最终 CAD。复刻工作应追求物理功能和回归指标，而不是从示意图量取专有尺寸。

## 1. 坐标和镜拓扑

- $z$：离子在两面镜之间往返的轴向坐标；
- $x$：单面镜内的横向聚焦坐标；
- $y$：镜的伸长方向，在理想镜设计阶段假设平移不变；
- 中央平面位于 $z=0$；
- 左、右转折点为 $-z_m$ 和 $+z_m$。

每面镜包含五组电极：

| 电极 | 正离子时的极性 | 主要作用 |
|---|---:|---|
| 0 | 0 V | 与对面电极 0 形成中央近无场区 |
| 1 | 负电压 | 加速正离子并产生横向聚焦透镜 |
| 2 | 正电压 | 塑造反射势的低级段 |
| 3 | 更高正电压 | 调整能量等时平台和像差 |
| 4 | 更高正电压 | 形成最终反射势垒 |

负离子工作时，所有电压极性反转。

电极 1 的负电压不是附加装置，而是等时镜设计本身的一部分。它在轴势中形成加速区，同时通过真实二维场产生 $x$ 向聚焦。

## 2. 作用量、转折点和周期

令轴上静电势为 $\varphi_0(z)$，离子总能量为 $\varepsilon$。转折点满足

$$
q\varphi_0\!\left(z_m(\varepsilon)\right)=\varepsilon.
$$

一次完整轴向振荡的作用量为

$$
J_0(\varepsilon)
=
\oint p_z\,\mathrm dz
=
\sqrt{8m}
\int_{-z_m}^{z_m}
\sqrt{\varepsilon-q\varphi_0(z)}\,\mathrm dz.
$$

周期是作用量对能量的导数：

$$
T(\varepsilon)=\frac{\mathrm dJ_0}{\mathrm d\varepsilon}.
$$

对于正离子，使用能量/电荷

$$
w=\frac{\varepsilon}{q}
$$

可把质量与电荷尺度分离：

$$
T(w)
=
\sqrt{\frac{2m}{q}}
\int_{-z_m}^{z_m}
\frac{\mathrm dz}{\sqrt{w-\varphi_0(z)}}.
$$

因此镜的无量纲电压形状决定周期随 $w$ 的变化，而 $m/q$ 主要提供整体的平方根时间尺度。

## 3. 三点能量等时性

标称能量为

$$
\varepsilon_0=qV_a,
\qquad
w_0=V_a.
$$

等时性要求周期在目标能量窗口内近似不变：

$$
T'(\varepsilon)
=
J_0''(\varepsilon)
\approx 0.
$$

Astral 主论文采用三个能量点：

$$
w=3900,\ 4000,\ 4100\ \mathrm V.
$$

优化条件可写为

$$
\mathbf r_E=
\begin{bmatrix}
\left.\dfrac{\mathrm dT}{\mathrm dw}\right|_{w_0-100\ \mathrm V}\\[4pt]
\left.\dfrac{\mathrm dT}{\mathrm dw}\right|_{w_0}\\[4pt]
\left.\dfrac{\mathrm dT}{\mathrm dw}\right|_{w_0+100\ \mathrm V}
\end{bmatrix}
\rightarrow \mathbf 0.
$$

工程上更适合优化归一化斜率：

$$
s_T(w)=\frac{1}{T(w)}\frac{\mathrm dT}{\mathrm dw},
$$

其单位为 $\mathrm V^{-1}$，可直接与 ppm/V 量级比较。

三点条件的意义是形成宽平台，而不是只让中心点的一阶导数为零。中心点单零通常不足以覆盖源的能量展宽、空间电荷引起的焦面移动和电压漂移。

## 4. Berdnikov 平面镜解析势

### 4.1 理想边界问题

Berdnikov 模型考虑两块平行对称平面，间距为 $2H$。为避免与本知识包坐标混淆，定义无量纲变量

$$
\zeta=\frac{z-z_k}{H},
\qquad
\xi=\frac{x}{H},
\qquad
-1\le\xi\le1.
$$

单位电压阶跃的精确二维拉普拉斯解为

$$
F(\zeta,\xi)
=
\frac12
+
\frac1\pi
\arctan\!\left[
\frac{\sinh(\pi\zeta/2)}{\cos(\pi\xi/2)}
\right].
$$

轴上 $x=0$ 时：

$$
F_0(\zeta)
=
\frac12
+
\frac1\pi
\arctan\!\left[\sinh\!\left(\frac{\pi\zeta}{2}\right)\right].
$$

它满足

$$
F_0(-\infty)=0,
\qquad
F_0(0)=\frac12,
\qquad
F_0(+\infty)=1.
$$

### 4.2 多电极分段常电压

设边界电压在 $z=z_k$ 处从 $U_{k-1}$ 跳到 $U_k$，定义

$$
\Delta U_k=U_k-U_{k-1}.
$$

没有端板时，理想二维电势为

$$
\varphi(z,x)
=
U_0
+
\sum_{k=1}^{M}
\Delta U_k
F\!\left(\frac{z-z_k}{H},\frac{x}{H}\right).
$$

轴势直接取 $x=0$：

$$
\varphi_0(z)
=
U_0
+
\sum_{k=1}^{M}
\Delta U_k
F_0\!\left(\frac{z-z_k}{H}\right).
$$

固定几何时，$\varphi$ 对电极电压严格线性，因此适合预计算单位电压基场和快速优化。

### 4.3 带端电极的反对称延拓

设最后一个分段电极电压为 $U_M$，垂直端板位于 $z=L_e$，端板电压为 $U_L$。可写成

$$
\begin{aligned}
\varphi(z,x)
={}&U_0
+
\sum_{k=1}^{M}
\Delta U_k
\left[
F\!\left(\frac{z-z_k}{H},\frac{x}{H}\right)
+
F\!\left(\frac{z-(2L_e-z_k)}{H},\frac{x}{H}\right)
\right]\\
&+
2\left(U_L-U_M\right)
F\!\left(\frac{z-L_e}{H},\frac{x}{H}\right).
\end{aligned}
$$

在 $z=L_e$ 处，利用 $F(a,\xi)+F(-a,\xi)=1$，可验证边界电压等于 $U_L$。

### 4.4 分段线性边界

真实镜可通过电阻链、PCB 或有限缝隙形成近似分段线性的边界电压。Berdnikov 论文给出了对应的线性基函数，并允许把“电压斜率变化”和“电压跳变”分别叠加。

对于复刻项目，推荐：

- 分段常数模型用于快速拓扑搜索；
- 分段线性模型用于模拟宽缝、阻性分压或 PCB 边界；
- 最终真实厚度、倒角、支撑和端部必须进入 BEM/FEM。

### 4.5 解析模型真正的适用条件

该平面解是指定理想边界条件下的拉普拉斯方程精确解，并不要求“$H$ 必须远小于电极宽度”。它的工程假设是：

- 两个边界面平行且对称；
- 在 $y$ 方向近似平移不变；
- 边界电压可用分段常数或分段线性函数表示；
- 未显式包含真实电极厚度、侧壁、螺钉、绝缘体和有限长度端部。

因此，$H$ 与电极宽度可比较；误差来自真实边界与理想边界的差异，而不是公式本身在该比例下失效。

## 5. 周期积分的数值稳定性

### 5.1 移动转折点

$z_m$ 随能量变化，且周期积分在转折点具有 $1/\sqrt{z_m-z}$ 型可积奇异。不要直接对含移动端点的积分逐项求二阶导数。

推荐三条独立路径：

1. 高精度计算 $J_0(w)$，再用局部多项式或 Chebyshev 拟合求导；
2. 对周期积分做端点正则化，再在多个能量点计算 $T(w)$；
3. 直接积分轨迹，用事件检测测量周期。

### 5.2 固定区间变换

对左右对称镜，可使用

$$
z=z_m\sin\theta,
\qquad
-\frac\pi2\le\theta\le\frac\pi2.
$$

也可在每个转折点附近使用

$$
z=z_m-u^2.
$$

生产实现应比较至少两种正则化方法，并扫描积分容差。

### 5.3 导数步长扫描

若用有限差分计算 $T'(w)$，至少扫描多组 $\Delta w$：

```text
0.1 V, 0.3 V, 1 V, 3 V, 10 V
```

可信结果应在一段步长范围内形成稳定平台。单一差分步长可能把积分噪声误认为等时性，也可能把截断误差隐藏在优化器中。

## 6. 单次反射的 Poincaré 映射

在中央截面选取相点 $(x_0,\alpha_0)$，经过单面镜反射后再次穿过同一截面，定义映射

$$
\begin{pmatrix}
x_1\\
\alpha_1
\end{pmatrix}
=
\mathcal M
\begin{pmatrix}
x_0\\
\alpha_0
\end{pmatrix}.
$$

傍轴线性化为

$$
\mathbf M=
\begin{pmatrix}
(x|x)&(x|\alpha)\\
(\alpha|x)&(\alpha|\alpha)
\end{pmatrix}.
$$

严格辛性应在规范变量 $(x,p_x)$ 中检查。在相同电位、相同轴向速度的截面上，使用小角度 $\alpha$ 可得到等价的线性矩阵。

静电反射的可逆性给出

$$
(x|x)=(\alpha|\alpha).
$$

矩阵可参数化为

$$
\begin{aligned}
(x|x)&=(\alpha|\alpha)=\cos\gamma,\\
(x|\alpha)&=f\sin\gamma,\\
(\alpha|x)&=-\frac{1}{f}\sin\gamma,
\end{aligned}
$$

其中 $f$ 是相空间椭圆的尺度参数，$\gamma$ 是一次反射的相位进动角。

## 7. 横向稳定性

线性稳定条件为

$$
|(x|x)|<1.
$$

等价地，矩阵特征值位于单位圆：

$$
\lambda_{\pm}=e^{\pm i\gamma}.
$$

稳定性必须在完整能量包络、制造误差和电压误差下具有裕量。只在标称中心轨迹上得到 $|(x|x)|<1$ 不足以证明动态孔径。

建议输出：

- $\det\mathbf M$；
- $(x|x)-(\alpha|\alpha)$；
- $\gamma$；
- $f$；
- 多个初始幅度的 Poincaré 轨道；
- 随振荡次数的椭圆面积漂移；
- 轨道是否接近非线性共振岛或机械边界。

## 8. 横向相空间引起的时间像差

单次振荡周期可展开为

$$
T(x_n,\alpha_n)
=
T_0
+T_{xx}x_n^2
+T_{x\alpha}x_n\alpha_n
+T_{\alpha\alpha}\alpha_n^2
+\text{higher-order terms}.
$$

在稳定椭圆上，半轴为 $x_0$ 和 $x_0/f$。对多次反射平均后，二阶幅度系数为

$$
\overline T_{xx}
=
\frac12\left(T_{xx}+f^{-2}T_{\alpha\alpha}\right).
$$

混合项 $T_{x\alpha}$ 在相位平均中交替抵消。优化目标为

$$
\overline T_{xx}=0,
$$

使平均周期对横向轨道幅度从四阶开始变化。

Astral 论文特别选择

$$
\gamma=90^\circ.
$$

此时

$$
(x|x)=(\alpha|\alpha)=0,
$$

实现**平行到点聚焦**。在该工作点，$T_{xx}$ 和 $T_{\alpha\alpha}$ 可同时消零，$T_{x\alpha}$ 在连续两次反射中平均抵消。

> **常见术语错误**：$\gamma=90^\circ$ 在论文中是 parallel-to-point focusing，不应写成 point-to-point focusing。

## 9. 优化变量和目标函数

### 9.1 建议参数向量

```text
H
internal boundary positions z_k
end plane L_e
electrode voltages U_1 ... U_4
optional piecewise-linear slopes
end-corrector parameters
```

不要一开始同时释放全部几何和电压。推荐先固定制造可行的拓扑和最小间距，分阶段增加自由度。

### 9.2 轴向目标

$$
\mathbf r_{\mathrm{iso}}
=
\begin{bmatrix}
s_T(w_0-\Delta w)\\
s_T(w_0)\\
s_T(w_0+\Delta w)
\end{bmatrix}.
$$

### 9.3 映射目标

$$
r_{\mathrm{symp}}=\det\mathbf M-1,
$$

$$
r_{\mathrm{rev}}=(x|x)-(\alpha|\alpha),
$$

$$
r_{\gamma}=\gamma-\frac\pi2.
$$

### 9.4 时间像差目标

$$
r_{x2}=\overline T_{xx},
$$

并可加入四阶系数、能量–幅度交叉项和有限束宽直接平均残差。

### 9.5 工程约束

- 电极 1 必须保持设计极性；
- 反射端电位必须覆盖最高能量粒子并保留穿透深度裕量；
- 转折点不得进入端部高场或几何不确定区；
- 电极宽度、间隙、厚度和绝缘距离满足制造约束；
- 峰值电场满足高压限制；
- 动态孔径覆盖源相空间；
- 中央无场区为 Stripe、棱镜、源和探测器留出空间。

所有残差必须按物理容差无量纲化。例如 ppm 周期残差不能与毫米几何残差直接相加。

## 10. 推荐的分阶段优化流程

### 阶段 A：解析轴势搜索

1. 固定五电极顺序和粗略制造边界；
2. 用 Berdnikov 基函数生成 $\varphi_0(z)$；
3. 扫描电极 1 的电压和宽度，找到可反射且有合理聚焦区的候选；
4. 求转折点和 $T(w)$；
5. 优化三个能量点的 $s_T(w)$。

### 阶段 B：二维横向优化

1. 使用完整 $\varphi(z,x)$ 而非只用轴势；
2. 提取单反射映射；
3. 加入 $\gamma=90^\circ$、辛性和 $\overline T_{xx}=0$；
4. 扫描动态孔径和非线性轨道。

### 阶段 C：BEM/FEM 精化

1. 加入真实电极厚度、缝隙、倒角和材料；
2. 重新计算单位电压基场；
3. 精调电极尺寸和电压；
4. 比较解析场、BEM/FEM 场和轨迹映射。

### 阶段 D：三维系统耦合

1. 加入镜端修正器；
2. 加入原 Ion Foil 或双 Stripe；
3. 加入棱镜、源、探测面和机械支撑；
4. 重新检查三点等时性、Poincaré 稳定和时间像差；
5. 用冻结粒子表计算完整峰形。

## 11. 周期和映射的事件定义

实现时必须明确：

- “单次反射”是中央截面出发并返回同一截面；
- “完整振荡周期 $T_0$”是离子在两面镜之间完成一个完整往返并以相同方向穿过参考截面；
- 转折事件由 $v_z=0$ 且运动方向改变定义；
- Poincaré 截面必须是同一电位、同一几何面和同一方向；
- 不要把半周期、单反射时间和完整振荡周期混用。

因子 2 错误会直接污染 $W$、$K$、总路径和漂移电极尺度。

## 12. 运行校准接口 TE1/TE2

真实装配会因机械偏差、能量标定、空间电荷和探测面位置而偏离设计点。公开的 Astral 校准形式为

$$
\mathbf U
=
w_0
\left[
\mathbf C^{(0)}
+\mathrm{TE1}\,\delta\mathbf C^{(1)}
+\mathrm{TE2}\,\delta\mathbf C^{(2)}
\right].
$$

公开示例系数为：

| 电极 | $C^{(0)}$ | $\delta C^{(1)}$ | $\delta C^{(2)}$ |
|---|---:|---:|---:|
| $U_1$ | -1.840 | 5.67 | -0.256 |
| $U_2$ | -1.158 | -1.616 | -0.654 |
| $U_3$ | 0.916 | -0.715 | 0.032 |
| $U_4$ | 1.503 | -2.963 | -0.361 |

这些向量属于特定镜设计：

- `TE1` 主要改变时间–能量一阶斜率，移动焦面；
- `TE2` 主要改变二阶曲率；
- 最优点位于“最佳分辨率轨迹”的拐点附近，并使该轨迹斜率为零。

新镜不能直接复制这些向量。应从自己的电压–像差 Jacobian 重新构造近似正交的校准方向。

## 13. 公开基准和未公开量

可复算公开基准：

- $w_0=4000\ \mathrm V$；
- 三个等时点为 $w_0$ 和 $w_0\pm100\ \mathrm V$；
- 论文图示中，束宽低于约 $2\ \mathrm{mm}$ FWHM 时平均横向周期误差低于约 $0.5\ \mathrm{ppm}$；
- 解析场用于粗优化，BEM 和像差射线追踪用于精化。

不能从主论文唯一确定：

- 各电极的精确宽度和间隙；
- 平面半间距 $H$ 的生产尺寸；
- 端部修正器和支撑结构；
- 最终电压的生产标定值；
- BEM 网格和全部高阶像差系数。

## 14. 容易犯错的地方

1. **把电极示意图当尺寸图**：示意图不按比例，不能量取生产尺寸。
2. **只优化轴势**：满足三点等时性不代表 $x$ 向稳定和低像差。
3. **把 $\gamma=90^\circ$ 写成点到点聚焦**：论文是平行到点聚焦。
4. **直接对移动奇异端点求二阶导数**：可能得到错误符号或数值发散。
5. **只用一个差分步长**：优化器可能追逐积分噪声。
6. **在 $(x,\alpha)$ 中无条件要求 $\det M=1$**：严格辛性应使用规范变量或保证截面速度归一化一致。
7. **混淆单反射和完整周期**：会使 $W$ 和 $K$ 出现因子 2 错误。
8. **把解析平面模型当真实三维模型**：有限长度、端部和漂移电极会破坏 $y$ 平移对称。
9. **把 TE1/TE2 示例向量用于新镜**：校准向量是设计特定的灵敏度方向。
10. **以峰宽代替镜本体性能**：源时间宽度、探测器、空间电荷和 aperture 都会改变最终峰形。

## 15. 最低参考测试

| 测试 | 判据 |
|---|---|
| Laplace 方程与边界测试 | 解析势在随机点满足 $\nabla^2\varphi=0$，边界电压正确 |
| 电压基场叠加 | 多电压直接场与单位基场线性组合一致 |
| 转折点测试 | $q\varphi_0(z_m)-\varepsilon$ 在容差内 |
| $T=\mathrm dJ/\mathrm d\varepsilon$ | 作用量差分、正则化周期和直接轨迹一致 |
| 三点等时性 | 三个能量点的归一化斜率满足目标 |
| 映射可逆性 | 正向反射后反向积分恢复初态 |
| 辛性 | 规范变量矩阵 $\det M$ 随步长和网格收敛到 1 |
| 线性稳定 | 全能量包络内 $|(x|x)|<1$ 且有裕量 |
| 相位目标 | $\gamma$ 接近 $90^\circ$ |
| 横向时间像差 | 直接多轨道平均验证 $\overline T_{xx}\approx0$ |
| 解析–BEM 对照 | 轴势、场、周期和映射差异进入误差预算 |
| 三维回归 | 加入端部和漂移电极后仍满足项目指标 |

## 16. 主要来源

- D. Grinfeld et al., *Nuclear Instruments and Methods in Physics Research A* 1060 (2024) 169017. DOI: `10.1016/j.nima.2023.169017`.
- A. S. Berdnikov et al., *Journal of Analytical Chemistry* 74 (2019) 1437–1446. DOI: `10.1134/S1061934819140041`.
- H. Stewart et al., “Crowd Control of Ions in the Astral Analyzer,” ChemRxiv. DOI: `10.26434/chemrxiv-2023-p6zln`.

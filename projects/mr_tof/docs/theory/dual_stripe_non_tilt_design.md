---
description: 平行镜双 Stripe 非倾斜 MR-TOF 方案的理论推导、精确作用量响应、形状反演、全能区优化、几何实现、调谐坐标和验证要求。
keywords:
  - dual stripe
  - parallel mirrors
  - non-tilt MR-TOF
  - action matching
  - energy response
  - adiabatic invariant
  - Ion Foil alternative
document_id: astral_replication.dual_stripe_non_tilt
version: 1.0.0
maturity: provisional_design_model
---

# 双 Stripe 平行镜非倾斜方案

本文件在 Astral 原论文的作用量和绝热漂移框架上，建立“**两面镜保持平行，使用两套独立偏压、独立形状 Stripe 控制漂移**”的设计模型。

原论文没有给出该方案，因此本文件分为两部分：

- 原论文直接支持的作用量、赝势和时间偏移框架；
- 在该框架上的新推导：双 Stripe 的精确能量响应、形状反演和优化方法。

> **设计目标**：不是机械地复制原方案的线性赝势，而是在规定能量、注入角和几何包络内，同时重建所需的空间返回和时间平台。

> **模型限定**：本文件中“精确响应”是指**分段常电位、硬边界、有效路径长度与能量无关**的模型内精确。真实三维电极的边缘场、轨迹折射和有效作用长度会随位置、角度和能量变化，必须以三维场中的直接作用量积分和粒子追踪复验。

## 1. 为什么取消镜面倾斜后需要两个独立响应

原方案的作用量扰动为

$$
\Delta J_{\mathrm{orig}}
=
\Delta J_s+\Delta J_m,
$$

其中：

- Stripe 电压扰动近似满足 $\Delta J_s\propto\varepsilon^{-1/2}$；
- 镜面几何缩短满足 $\Delta J_m\propto-\varepsilon^{+1/2}$。

两者在标称能量下共同形成返回赝势，但对能量导数的符号不同。

若只用一个线性 Stripe 产生与 $\Phi_m(y)$ 相同的线性空间赝势，它只能匹配

$$
\Delta J(\varepsilon_0,y),
$$

不能同时匹配

$$
\left.\partial_\varepsilon\Delta J(\varepsilon,y)\right|_{\varepsilon_0}.
$$

因此，双 Stripe 的核心用途是提供两个不同的电压响应基函数，使标称作用量和其能量导数能够独立调节。

## 2. 几何定义

每套 Stripe 由一对面对面的低压电极构成，离子从两板之间通过。设：

- Stripe 1 偏压为 $v_1$；
- Stripe 2 偏压为 $v_2$；
- 每次轴向振荡中，离子在 Stripe 1 近常势区内的总轴向路径长度为 $S_1(y)$；
- 在 Stripe 2 近常势区内的总轴向路径长度为 $S_2(y)$。

解析叠加式要求两套近常势区在轴向上不重叠，或至少能够按明确的分段电位积分。若两个电极场在同一区域叠加，不能简单把两个平方根作用量相加，必须使用真实合成电势重新积分。

## 3. 单个有限偏压 Stripe 的硬边界精确响应

对正离子，设总能量为 $\varepsilon$，Stripe 偏压为 $v$。离子必须满足

$$
\varepsilon-qv>0
$$

才能穿过该近常势区。

单位轴向长度的作用量变化系数定义为

$$
A(v,\varepsilon)
=
\sqrt{8m}
\left[
\sqrt{\varepsilon-qv}
-
\sqrt{\varepsilon}
\right].
$$

因此

$$
\Delta J_v(\varepsilon,y)
=
A(v,\varepsilon)S(y).
$$

其一阶导数为

$$
A_\varepsilon'(v,\varepsilon)
=
\frac{\sqrt{8m}}{2}
\left[
\frac{1}{\sqrt{\varepsilon-qv}}
-
\frac{1}{\sqrt{\varepsilon}}
\right].
$$

二阶导数为

$$
A_\varepsilon''(v,\varepsilon)
=
\frac{\sqrt{8m}}{4}
\left[
\varepsilon^{-3/2}
-
(\varepsilon-qv)^{-3/2}
\right].
$$

三阶导数为

$$
A_\varepsilon'''(v,\varepsilon)
=
\frac{3\sqrt{8m}}{8}
\left[
(\varepsilon-qv)^{-5/2}
-
\varepsilon^{-5/2}
\right].
$$

这些精确式应优先用于双 Stripe 设计；只在 $|v|\ll w_0$ 时使用线性近似。

## 4. 双 Stripe 总作用量

在非重叠硬边界模型中：

$$
\Delta J_{2s}(\varepsilon,y)
=
A(v_1,\varepsilon)S_1(y)
+
A(v_2,\varepsilon)S_2(y).
$$

标称漂移赝势为

$$
\Phi_{2s}(y)
=
-
\frac{\Delta J_{2s}(\varepsilon_0,y)}{qT_0}.
$$

慢漂移方程保持不变：

$$
\frac{\Delta\varepsilon_y}{\Delta y}
\approx
-q\Phi_{2s}'(y).
$$

返回时间和振荡次数仍由

$$
T_D
=
\sqrt{\frac{2m}{q}}
\int_0^{y_D}
\frac{\mathrm dy}
{\sqrt{\Phi_{2s}(y_D)-\Phi_{2s}(y)}},
$$

$$
K=\operatorname{round}(T_D/T_0)
$$

确定。

## 5. 用形状变化而不是绝对宽度做匹配

物理电极宽度必须非负，但为了控制漂移，真正重要的是相对于注入端基线的变化：

$$
\widetilde S_i(y)
=
S_i(y)-S_i(0).
$$

$\widetilde S_i$ 可以为正或负，而完整宽度 $S_i(y)$ 仍保持正值。

对应的 $y$ 依赖作用量为

$$
\widetilde{\Delta J}_{2s}(\varepsilon,y)
=
A_1(\varepsilon)\widetilde S_1(y)
+
A_2(\varepsilon)\widetilde S_2(y),
$$

其中

$$
A_i(\varepsilon)=A(v_i,\varepsilon).
$$

基线项

$$
\Delta J_{\mathrm{base}}(\varepsilon)
=
A_1(\varepsilon)S_1(0)
+
A_2(\varepsilon)S_2(0)
$$

不产生 $y$ 向力，但会改变整体周期和能量聚焦，因此必须在镜电压优化或运行校准中保留。

## 6. 广义无量纲空间函数和时间函数

定义

$$
\eta=\frac yL,
\qquad
w_{y0}=w_0\sin^2\vartheta_0.
$$

对任意漂移控制器，定义归一化空间函数

$$
\psi(\eta)
=
\frac{\Phi(L\eta)-\Phi(0)}{w_{y0}}.
$$

再定义归一化时间响应函数

$$
g(\eta)
=
\frac{2\varepsilon_0}
{qT_0w_{y0}}
\left[
\left.\partial_\varepsilon\Delta J(\varepsilon,L\eta)
\right|_{\varepsilon_0}
-
\left.\partial_\varepsilon\Delta J(\varepsilon,0)
\right|_{\varepsilon_0}
\right].
$$

则

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

广义时间偏移为

$$
\frac{\Delta T_K}{T_0}
=
\frac{L\sin\vartheta_0}{2W}
\tau_g(\eta_D),
$$

$$
\tau_g(\eta_D)
=
\int_0^{\eta_D}
\frac{g(\eta)}
{\sqrt{\psi(\eta_D)-\psi(\eta)}}
\,\mathrm d\eta.
$$

原 Astral 是特例：

$$
\psi_{\mathrm{target}}
=
\psi_s+\psi_m,
$$

$$
g_{\mathrm{target}}
=
\psi_s-\psi_m.
$$

双 Stripe 设计应同时拟合 $\psi$ 和 $g$，而不是继续使用只适用于原方案的 $\psi_s-\psi_m$ 解释。

## 7. 单个 Stripe 的空间–时间响应比

定义单个 Stripe 在标称能量下的归一化空间贡献

$$
p_i(\eta)
=
-
\frac{A_i(\varepsilon_0)\widetilde S_i(L\eta)}
{qT_0w_{y0}}.
$$

则

$$
\psi=p_1+p_2.
$$

利用恒等式

$$
\frac{A_\varepsilon'}{A}
=
-
\frac{1}{2\sqrt{\varepsilon(\varepsilon-qv)}},
$$

可得到

$$
g_i=h_i p_i,
$$

其中

$$
h_i
=
\sqrt{\frac{\varepsilon_0}{\varepsilon_0-qv_i}}
=
\sqrt{\frac{w_0}{w_0-v_i}}.
$$

因此双 Stripe 在标称点满足

$$
\psi=p_1+p_2,
$$

$$
g=h_1p_1+h_2p_2.
$$

物理意义：

- $v_i>0$ 时，$h_i>1$；
- $v_i<0$ 时，$0<h_i<1$；
- $v_i=0$ 时没有作用量扰动，不能作为独立响应基；
- $v_1\approx v_2$ 时，两个响应几乎退化为同一基函数。

## 8. 标称点的闭式形状反演

给定目标 $\psi_t(\eta)$ 和 $g_t(\eta)$，若

$$
h_1\ne h_2,
$$

则

$$
p_1(\eta)
=
\frac{g_t(\eta)-h_2\psi_t(\eta)}{h_1-h_2},
$$

$$
p_2(\eta)
=
\frac{h_1\psi_t(\eta)-g_t(\eta)}{h_1-h_2}.
$$

这给出在 $\varepsilon_0$ 处同时匹配作用量和一阶能量导数的初始解。

若使用原 Astral 目标：

$$
\psi_t(\eta)
=
c_0\eta
+
\sum_{k=1}^{5}c_k\eta^k,
$$

其中 $c_0\eta$ 是原镜倾斜分量，且常数项为零；

$$
g_t
=
\left(c_1\eta+c_2\eta^2+\cdots+c_5\eta^5\right)-c_0\eta.
$$

注意这里的 $c_0\eta$ 是原论文的线性赝势分量，不是 Stripe 基线宽度。

## 9. 从 $p_i$ 转换为物理形状

使用能量/电荷变量 $w_0$，精确形状变化为

$$
\widetilde S_i(L\eta)
=
\frac{Ww_{y0}}{v_i}
\frac{1+\sqrt{1-v_i/w_0}}{2}
\,p_i(\eta),
$$

适用条件为

$$
v_i\ne0,
\qquad
w_0-v_i>0.
$$

当 $|v_i|\ll w_0$：

$$
\widetilde S_i(L\eta)
\approx
\frac{Ww_{y0}}{v_i}p_i(\eta).
$$

完整物理宽度为

$$
S_i(y)=S_{i0}+\widetilde S_i(y).
$$

基线应满足

$$
S_{i0}
>
-\min_{0\le y\le L}\widetilde S_i(y)
+S_{i,\mathrm{margin}},
$$

从而保证

$$
S_i(y)>0.
$$

## 10. 响应矩阵和条件数

直接以作用量写成

$$
\begin{pmatrix}
A_1&A_2\\
A_1'&A_2'
\end{pmatrix}
\begin{pmatrix}
\widetilde S_1\\
\widetilde S_2
\end{pmatrix}
=
\begin{pmatrix}
\widetilde{\Delta J}_{t}\\
\partial_\varepsilon\widetilde{\Delta J}_{t}
\end{pmatrix}.
$$

行列式可写为

$$
\det\mathbf A
=
A_1A_2
\left[
-
\frac{1}{2\sqrt{\varepsilon_0(\varepsilon_0-qv_2)}}
+
\frac{1}{2\sqrt{\varepsilon_0(\varepsilon_0-qv_1)}}
\right].
$$

只要 $v_1\ne v_2$ 且两者均非零，数学上通常可逆。但可逆不等于工程上稳定：

- $v_1$ 和 $v_2$ 太接近时，条件数很大；
- 两个偏压都很小时，$A_i$ 很小，所需形状变化很大；
- 正偏压接近最低离子能量时，穿越裕量消失；
- 过大的正负偏压会增强边缘场和横向透镜。

电压对必须通过条件数、形状幅度、峰值场和能量窗口联合选择。

## 11. 基线宽度的全局影响

为了把有正有负的 $\widetilde S_i$ 实现为真实电极，需要加入 $S_{i0}$。基线不会改变慢漂移力，但会产生

$$
\Delta J_{\mathrm{base}}(\varepsilon)
=
A_1(\varepsilon)S_{10}
+
A_2(\varepsilon)S_{20}.
$$

它会改变：

- 完整轴向周期；
- 三点镜等时性；
- 探测焦面位置；
- TE1/TE2 校准零点。

因此推荐两种处理方式：

### 11.1 联合优化

把 $S_{10},S_{20}$ 与镜电压一起放入全局优化器。

### 11.2 分阶段补偿

先选择满足机械正宽度的基线，再重新优化镜电压和校准向量，使全系统恢复三点等时和目标焦面。

不能在轨迹模型中保留基线，却在时间模型中把它删除。

## 12. 推荐的几何拓扑

### 12.1 串联轴向带区

在中央接地棱镜走廊两侧，按 $z$ 方向依次布置 Stripe 1 和 Stripe 2 的偏置带区。每一套在正、负 $z$ 两侧对称出现，使离子每个振荡穿过相同总长度。

优点：

- 两套作用量可近似线性相加；
- 电压独立；
- 形状定义清楚；
- 容易建立单位电压基场。

约束：

$$
G_0
+S_1(y)
+S_2(y)
+G_{12}
+G_{\mathrm{outer}}
\le
Z_{\mathrm{available}},
$$

其中 $G_0$ 是中央走廊，$G_{12}$ 是两 Stripe 间隔，$G_{\mathrm{outer}}$ 是外侧保护间距。

### 12.2 重叠场区

若两套电极在同一空间区域产生叠加电势，局部电位不是两个独立常势段。此时应直接计算

$$
\Delta J
=
\sqrt{8m}
\int
\left[
\sqrt{\varepsilon-q\delta\varphi_{\mathrm{total}}(x,y,z)}
-
\sqrt{\varepsilon}
\right]
\,\mathrm dz,
$$

不能使用 $A_1S_1+A_2S_2$。

### 12.3 电极板间距

面对面电极距离需要在两种目标之间折中：

- 足够大以覆盖全束和装配误差；
- 足够小以形成接近常势的内部区域并减少泄漏场。

不应从简化理论给出通用毫米值。尺寸由三维场均匀性、束包络和高压安全共同确定。

## 13. 形状基函数选择

闭式反演可得到多项式形状，但真实 CAD 不必直接使用五次全局多项式。推荐使用：

- 端点约束 B-spline；
- 分段三次 Hermite 曲线；
- 具有显式一阶、二阶连续性的 Bézier 段；
- 全局多项式仅用于 L0 基准。

形状应至少满足：

$$
S_i\in C^1,
$$

最好满足

$$
S_i\in C^2.
$$

需要显式控制：

- $S_i(y)>0$；
- 最大和最小宽度；
- $|S_i'(y)|$；
- $|S_i''(y)|$；
- 中央棱镜走廊；
- 两套 Stripe 不相交；
- 加工刀具半径和最小绝缘间隙。

## 14. 绝热性验证

双 Stripe 仍依赖轴向作用量的绝热不变量。建议定义每周期指标：

$$
\epsilon_J(n)
=
\left|
\frac{J_{n+1}-J_n}{J_n}
\right|,
$$

以及形状变化指标

$$
\epsilon_{S,i}(n)
=
\frac{|S_i'(y_n)\Delta y_n|}
{\max(S_i(y_n),S_{\mathrm{scale}})}.
$$

这些量没有跨几何通用阈值，必须通过：

1. 逐步平滑形状；
2. 减小时间步；
3. 提高场网格；
4. 比较赝势轨迹和完整轨迹；
5. 检查指标与性能是否共同收敛。

突然的电极起点、尖角和电压边界会产生非绝热横向踢和时间误差。

## 15. 从原 Astral 解得到双 Stripe 初值

### 15.1 原目标函数

使用论文系数：

$$
\psi_m=c_0\eta,
$$

$$
\psi_s=c_1\eta+c_2\eta^2+c_3\eta^3+c_4\eta^4+c_5\eta^5.
$$

构造

$$
\psi_t=\psi_s+\psi_m,
$$

$$
g_t=\psi_s-\psi_m.
$$

### 15.2 选择电压对

在项目允许的电压范围内扫描 $(v_1,v_2)$，并拒绝：

- $v_1=v_2$；
- 任一 $v_i=0$；
- $w_{\min}-v_i\le0$；
- 响应矩阵条件数过大；
- 反演后的形状变化超出可用轴向长度。

### 15.3 闭式反演

对每个 $\eta$ 计算 $p_1,p_2$，再转换为 $\widetilde S_1,\widetilde S_2$。

### 15.4 基线和 CAD 平滑

选择 $S_{10},S_{20}$ 使物理宽度为正，再把全局多项式拟合为可制造的 $C^2$ 曲线。

### 15.5 全窗口再优化

闭式解只匹配标称能量的一阶响应，必须进入下一阶段。

## 16. 全能区优化

推荐直接使用精确作用量，而不是继续把双 Stripe 强行写成原论文的 $\tau$ 形式。

定义能量网格

$$
w_j\in[w_0-\Delta w,w_0+\Delta w]
$$

和漂移坐标网格 $\eta_l$。目标作用量可来自：

- 原 Astral 解析目标；
- 自己重新优化的 $\psi_t,g_t$；
- 直接以最终 $T_D$ 和 $\Delta T_K$ 为目标。

作用量残差：

$$
r_J(w_j,\eta_l)
=
\Delta J_{2s}(qw_j,L\eta_l)
-
\Delta J_t(qw_j,L\eta_l).
$$

导数残差：

$$
r_{J,n}
=
\partial_w^n\Delta J_{2s}
-
\partial_w^n\Delta J_t,
\qquad
n=1,2,3.
$$

直接性能残差：

$$
r_{\kappa}=\kappa'(1),
$$

$$
r_{\psi}=\psi(1)-1,
$$

$$
r_{\tau}
=
\operatorname{range}_{\eta_D\in\mathcal A}
\tau_g(\eta_D),
$$

其中 $\mathcal A$ 是目标注入角对应的转折区间。

完整目标函数示例：

$$
\mathcal L
=
\lambda_J\|r_J\|_2^2
+
\lambda_1\|r_{J,1}\|_2^2
+
\lambda_2\|r_{J,2}\|_2^2
+
\lambda_3\|r_{J,3}\|_2^2
+
\lambda_\kappa r_\kappa^2
+
\lambda_\tau r_\tau^2
+
\mathcal P_{\mathrm{geometry}}
+
\mathcal P_{\mathrm{field}}.
$$

所有权重必须由时间、空间和制造误差预算决定。

## 17. 直接优化最终时间而不是目标作用量

若原 Astral 的作用量响应只是参考，而非必须逐点复制，可直接优化：

1. 给定六维源粒子；
2. 计算每个离子的实际转折点和振荡数；
3. 计算到达时间；
4. 对目标 $K$ 的粒子计算 FWHM；
5. 同时惩罚损失、overtone 和高场。

但在昂贵三维优化前，仍应保留 L0 作用量模型作为快速筛选和物理诊断工具。

## 18. 平行镜误差必须作为设计变量

非倾斜方案取消的是**有意收敛角**，不是免除平行度要求。任意残余夹角 $\delta\Theta$ 都会产生

$$
\Delta J_{\mathrm{tilt,error}}
=
-\sqrt{8m\varepsilon}\,y\tan\delta\Theta,
$$

即重新引入原方案的几何能量响应。

因此误差矩阵必须包含：

- 整体平行度；
- 扭转角；
- 两杆支撑高度差；
- 热膨胀；
- 局部弯曲；
- Stripe 与镜的相对位置。

平行度误差既可能破坏双 Stripe 优化，也可能被用于小范围补偿。若允许后者，必须明确它是校准自由度还是制造误差，不能在模型中隐含。

## 19. 双 Stripe 的调谐坐标

实际仪器不宜直接以 $v_1,v_2$ 两个原始电压盲扫。建议在标称点计算 Jacobian：

$$
\mathbf J_v
=
\frac{\partial
(\text{return metric},\text{time metric})}
{\partial(v_1,v_2)}.
$$

通过 SVD 或正交化构造：

- `DRIFT_RETURN`：主要改变 $K$ 和空间焦点；
- `DRIFT_TIME`：主要改变时间平台，尽量少改变 $K$。

线性形式：

$$
\begin{pmatrix}
v_1\\v_2
\end{pmatrix}
=
\begin{pmatrix}
v_{1,0}\\v_{2,0}
\end{pmatrix}
+
D_R\mathbf d_R
+
D_T\mathbf d_T.
$$

在三维场和真实源下重新计算调谐方向，不要只从 L0 公式定义。

## 20. 与注入棱镜和镜校准的耦合

双 Stripe 改变了三个运行接口：

1. 返回力不再由单一 Stripe 电压控制，$K$ 调谐变为二维；
2. 基线宽度改变全局镜周期，需要重新计算 TE1/TE2；
3. 中央接地走廊的几何改变棱镜边缘场和注入角。

推荐联合校准顺序：

```text
镜三点等时初调
→ 双 Stripe 返回力调到目标 K
→ 棱镜调到空间焦点
→ 双 Stripe 时间方向调到最小峰宽
→ TE1/TE2 调整全局能量焦点
→ 迭代至收敛
```

## 21. 真实三维场中的额外效应

双 Stripe 可能引入原一维作用量模型没有的效应：

- $x$ 向聚焦或散焦；
- $x$–$y$ 耦合；
- 两套电极边缘场相互作用；
- 中央棱镜区的泄漏场；
- 绝缘体充电；
- 电压误差造成非对称转向；
- 对镜 Poincaré 映射的扰动；
- 局部高场和放电风险。

每套 Stripe 应建立独立单位电压基场，并验证线性叠加只适用于静电势；离子作用量和飞行时间仍是非线性函数。

## 22. 容易犯错的地方

1. **只让线性 Stripe 的 $\Phi(y)$ 等于原 $\Phi_m(y)$**：这不匹配时间响应。
2. **把 $S_i(y)$ 当可带符号的物理宽度**：应使用带符号变化 $\widetilde S_i$ 和正基线 $S_{i0}$。
3. **加入基线后不重新优化镜**：基线会改变全局能量焦点。
4. **两个电压过于接近**：响应矩阵虽可逆但严重病态。
5. **两个电压都很小**：需要不可制造的大宽度变化。
6. **正偏压超过最低离子能量**：离子会在 Stripe 内反射，轨迹拓扑改变。
7. **场区重叠却使用作用量线性相加**：必须积分真实合成电势。
8. **继续直接使用原 $c_0\ldots c_5$ 作为两电极形状系数**：它们是目标函数系数，不是新电极 CAD 系数。
9. **只匹配一阶导数**：宽能量窗口还需二阶、三阶和直接时间验证。
10. **忽略平行度误差**：残余微小倾斜重新引入几何响应。
11. **以中心粒子确认唯一 $K$**：必须检查完整粒子表和实际转折事件。
12. **只看峰宽不看透过率**：边缘截束可能让残余峰变窄。
13. **形状用高阶多项式直接加工**：全局多项式可能有振荡、负宽度和过大曲率。
14. **在不同求解器中手工重建不同几何**：必须由同一形状合同生成。

## 23. 推荐机器合同

```json
{
  "model_id": "astral.dual_stripe.parallel_mirrors.v1",
  "nominal_energy_per_charge_V": 4000.0,
  "energy_window_V": [3900.0, 4100.0],
  "nominal_drift_length_mm": 335.0,
  "effective_mirror_distance_mm": 641.0,
  "target_oscillation_count": 25,
  "stripe_1": {
    "bias_V": null,
    "baseline_width_mm": null,
    "shape_basis": "cubic_bspline",
    "shape_coefficients": []
  },
  "stripe_2": {
    "bias_V": null,
    "baseline_width_mm": null,
    "shape_basis": "cubic_bspline",
    "shape_coefficients": []
  },
  "geometry_constraints": {
    "central_grounded_corridor_mm": null,
    "minimum_interstripe_gap_mm": null,
    "minimum_width_mm": null,
    "maximum_width_mm": null,
    "maximum_slope": null,
    "maximum_curvature_per_mm": null
  },
  "optimization": {
    "target_model": "published_astral_action_response",
    "energy_samples_V": [],
    "eta_samples": [],
    "derivative_orders": [0, 1, 2, 3]
  }
}
```

所有 `null` 项必须由项目工程边界、束包络和高压规则确定，不能由理论文档填入假数值。

## 24. 最低参考测试

| 测试 | 判据 |
|---|---|
| 单 Stripe 精确响应 | 解析 $A,A',A'',A'''$ 与有限差分一致 |
| 响应矩阵 | 条件数、行列式和电压扫描有记录 |
| 标称反演 | $\psi$ 和 $g$ 在 $\varepsilon_0$ 处恢复目标 |
| 宽度正性 | 全 $y$ 范围 $S_i(y)>0$ |
| 几何不重叠 | 两套偏置区和中央走廊无交叉 |
| 基线影响 | 加入 $S_{i0}$ 后重新计算镜周期和能量斜率 |
| 高阶能量响应 | $n=2,3$ 导数残差进入预算 |
| 绝热性 | 相邻周期作用量和完整轨迹收敛 |
| 唯一 $K$ | 全粒子实际事件数一致 |
| 时间平台 | 全目标角度和能量范围的到达时间分布满足预算 |
| 三维场 | 两套单位电压基场、合成场和横向踢通过检查 |
| 平行度鲁棒性 | 角度、扭转和热误差 Monte Carlo |
| 原方案对照 | 相同粒子表下比较 FWHM、透过率、overtone、峰形和高场 |

## 25. 主要来源和推导属性

源论文提供：作用量、绝热不变量、漂移赝势、返回时间、时间偏移、Stripe 响应和镜倾斜响应。

本文件的新推导包括：

- 双有限偏压 Stripe 的响应矩阵；
- $h_i=\sqrt{w_0/(w_0-v_i)}$；
- $\psi/g$ 闭式反演；
- 从归一化贡献到物理形状的精确转换；
- 使用带符号形状变化和正基线的工程实现；
- 全能区和高阶导数优化协议。

主要基础来源：

- D. Grinfeld et al., *Nuclear Instruments and Methods in Physics Research A* 1060 (2024) 169017. DOI: `10.1016/j.nima.2023.169017`.

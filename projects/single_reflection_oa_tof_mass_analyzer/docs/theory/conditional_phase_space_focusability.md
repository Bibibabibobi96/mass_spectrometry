# 有限条件相空间厚度的受约束时间可聚焦性

> `DOC_STATUS: PAPER_1_CANDIDATE / EVIDENCE_REQUIRED`
>
> `ROLE: CANONICAL_FOCUSABILITY_CRITERION`
>
> `FORMAL_EFFECT: NONE`

本文在[`统一相空间框架`](source_to_detector_phase_space_framework.md)定义的时钟、状态、条件源和
source-to-detector映射之上，推导有限条件厚度的局部受约束可聚焦性。本文不重复N区加速器或二级
反射镜精确时间。

投影、SVD、null space和加权最小二乘是标准数学；候选贡献是：在保持oa-TOF既有低阶与工程约束的
条件下，判断真实源残差时间灵敏度有多少落入分析器可行控制子空间，并用冻结6D源和三维场验证预测。

## 1. 切向closure与条件厚度

对多维条件坐标`\mathbf s\in\mathbb R^k`：

$$
\mathbf u=\boldsymbol\mu(\mathbf s)+\boldsymbol\varepsilon,
\quad
E[\boldsymbol\varepsilon\mid\mathbf s]=0,
\quad
\operatorname{Cov}(\boldsymbol\varepsilon\mid\mathbf s)=
\Sigma_\varepsilon(\mathbf s).
$$

在条件均值附近：

$$
T\approx
\tau(\mathbf s)
+\mathbf g(\mathbf s)^T\boldsymbol\varepsilon
+\frac12\boldsymbol\varepsilon^TH(\mathbf s)
\boldsymbol\varepsilon+\cdots.
$$

沿条件均值流形的一阶closure为

$$
\boxed{J_\mu(\mathbf s)^T\mathbf g(\mathbf s)=0},
$$

条件厚度的一阶时间方差为

$$
\boxed{
J_\perp(\mathbf s)
=\mathbf g(\mathbf s)^T
\Sigma_\varepsilon(\mathbf s)
\mathbf g(\mathbf s)
}.
$$

前者只要求时间梯度正交于流形切空间；后者为零则要求时间梯度落入条件协方差的null space。因此沿
affine或非线性主流形令`D1/D2/D3=0`，不自动消除给定流形坐标后的随机厚度。

## 2. 尺度固定与残差模态

先使用预注册尺度`S_u`定义无量纲残差：

$$
\boldsymbol\varepsilon=S_u\widetilde{\boldsymbol\varepsilon},
\qquad
\widetilde{\mathbf g}=S_u^T\mathbf g,
\qquad
\widetilde\Sigma=S_u^{-1}\Sigma_\varepsilon S_u^{-T}.
$$

对无量纲协方差分解：

$$
\widetilde\Sigma
=\sum_k\lambda_k\mathbf e_k\mathbf e_k^T.
$$

则

$$
J_\perp
=\sum_k\lambda_k
(\widetilde{\mathbf g}\cdot\mathbf e_k)^2.
$$

定义`q_k=λ_k(\widetilde g\cdot e_k)^2`作为声明尺度下的残差模态时间代价。一个模态只有在源占据量和
整机时间灵敏度同时较大时才重要。

`q_k`不是坐标自由的绝对本征量。论文必须报告状态定义、尺度、条件模型和bootstrap稳定性；模态接近
简并时应报告子空间而不是给不稳定的单根向量命名。

## 3. 保持既有约束后的可行控制方向

令设计参数为`θ`，已有等式约束包括中心能量、低阶closure、参考面或其他必须保持的条件：

$$
\mathbf c(\boldsymbol\theta)=0.
$$

在可行点`θ0`附近，经设计参数无量纲化后：

$$
C\,\delta\widetilde{\boldsymbol\theta}=0.
$$

令`N`的列张成`Null(C)`：

$$
\delta\widetilde{\boldsymbol\theta}=N\boldsymbol\eta.
$$

到达时间梯度的局部响应为

$$
\widetilde{\mathbf g}
\approx
\widetilde{\mathbf g}_0+G_N\boldsymbol\eta.
$$

`η`才是保持现有条件后真正可用的控制自由度。参数数量、场区数量或未约束Jacobian的列数都不能替代
这一可行方向分析。

## 4. Source-whitened控制子空间

取条件协方差的因子

$$
\widetilde\Sigma=LL^T.
$$

定义

$$
\mathbf b=L^T\widetilde{\mathbf g}_0,
\qquad
A=L^TG_N.
$$

于是局部无界线性参考问题为

$$
\boxed{
\min_{\boldsymbol\eta}
\|\mathbf b+A\boldsymbol\eta\|_2^2
}.
$$

令`P_A=AA^+`，最小参考残差为

$$
\boxed{
J_{\perp,\mathrm{lin}}^{\min}
=\|(I-P_A)\mathbf b\|_2^2
}.
$$

在该局部、无界模型中，条件厚度的一阶时间贡献可完全消除，当且仅当

$$
\mathbf b\in\operatorname{Range}(A).
$$

该条件比“自由参数不少于方程”严格，因为只有与source-weighted残差方向重叠的可行控制方向才有效。

## 5. 沿完整条件分布的离散实现

对detector-blind source bins或局部邻域`j`，冻结权重`w_j`、协方差因子`L_j`、时间梯度`g_j`和设计
响应`G_{N,j}`：

$$
A_j=\sqrt{w_j}L_j^TG_{N,j},
\qquad
\mathbf b_j=\sqrt{w_j}L_j^T\widetilde{\mathbf g}_j.
$$

纵向堆叠：

$$
A_{\mathrm{stack}}=
\begin{bmatrix}A_1\\A_2\\\vdots\end{bmatrix},
\qquad
\mathbf b_{\mathrm{stack}}=
\begin{bmatrix}\mathbf b_1\\\mathbf b_2\\\vdots\end{bmatrix}.
$$

所有projector、rank和SVD结论使用该全源矩阵，而不是只在源中心计算。bin、带宽、条件模型和权重必须
在查看最终detector结果之前冻结，并通过source-space交叉验证选择。

## 6. Focusability index

若`J0=||b||²>0`，定义局部线性可消除比例

$$
\boxed{
\mathcal F_{\mathrm{lin}}
=1-\frac{\|(I-P_A)\mathbf b\|^2}{\|\mathbf b\|^2}
}.
$$

其含义仅限当前source、架构、工作点、尺度、约束和局部线性化：

- `F_lin≈0`：现有可行方向几乎不覆盖主导一阶残差；
- `F_lin≈1`：局部一阶模型认为大部分残差可由分析器重定向；
- 中间值：只有部分source-weighted残差可控。

它不是跨质量、跨源或跨几何可直接比较的仪器常数，也不是分辨率的绝对上限。

## 7. 电压、几何和信赖域约束

实际问题还需满足：

$$
V_{\min}\le V_i\le V_{\max},
\quad
E_i\le E_{\max},
\quad
d_{\mathrm{turn}}\le d_{\mathrm{mirror}}-m_{\mathrm{safety}},
$$

以及孔径、机械、脉冲和detector边界。正式局部优化应使用

$$
\min_\eta
\|\mathbf b+A\eta\|^2
+\rho\eta^TW\eta
$$

并带显式box、线性化不等式和信赖域。无界projector值只能作为“在当前切空间内的乐观参考”。如果最优
解触及边界、要求过大步长或改变粒子命中拓扑，必须使用有界QP/SQP和直接轨迹结果，不能继续引用
`F_lin`作为实际可达比例。

## 8. 新增场区或控制方向的增量价值

已有控制子空间为`Range(A)`，新增参数在保持旧约束后产生source-whitened方向`a_new`。定义

$$
\mathbf a_\perp=(I-P_A)\mathbf a_{\mathrm{new}},
\qquad
\mathbf b_\perp=(I-P_A)\mathbf b.
$$

若`a_perp=0`，新增参数不增加局部source-weighted控制子空间。对无正则、无边界的单一新增方向，最大
额外降低量为

$$
\boxed{
\Delta J_{\mathrm{lin}}
=\frac{(\mathbf b_\perp^T\mathbf a_\perp)^2}
{\mathbf a_\perp^T\mathbf a_\perp}
}.
$$

该式只有在新增方向非零、允许正负连续调节且局部线性模型有效时成立。实际增益必须扣除active
constraints、容差放大、非线性、尾部和传输代价。

## 9. `Γ3`的正确定位

三区文档中的

$$
\Gamma_3
=\left.\frac{dD_3}{dg}\right|_{D_1=D_2=0}
$$

回答：保持两个低阶标量closure时，第三变量是否仍能改变标量`D3`。本文的`a_perp/ΔJ_lin`回答：保持
全部声明约束时，新增方向是否覆盖真实条件源仍未控制的source-weighted timing modes。

因此`Γ3`是后者针对单个高阶标量目标的特例。`Γ3≠0`不保证真实源峰宽改善，`Γ3≈0`也不能排除新增
参数通过其他模态、有限区间或命中边界产生作用。

## 10. SVD、rank与可调性

对缩放后的`A=UΣ_AV^T`：

- `U`表示可控制的source-whitened时间方向；
- `V`表示设计参数组合；
- 奇异值表示局部控制杠杆。

必须报告：

- 状态和参数尺度；
- pseudoinverse/rank容差；
- singular values与有效rank；
- scaled condition number；
- active constraints；
- 对电压、几何、数值噪声和bootstrap重采样的稳定性。

很小的奇异值表示数学上可能存在方向，但需要巨大参数变化且会放大误差；不得把它计作稳健的工程
自由度。

## 11. 有限孔径和命中拓扑边界

Projector理论默认在固定cohort和光滑事件拓扑内对到达时间微分。若参数变化使粒子跨越孔径、栅线、
反射器穿底或detector边界：

- `T`对失去命中的粒子不再存在；
- 条件峰宽和传输同时改变；
- 局部梯度可能不连续；
- 只在共同命中交集上比较会隐藏损失。

因此每个预测和验证都必须冻结pre-pulse母cohort，报告两臂完整census，并把共同命中配对差只用于
机制隔离。正式设计目标同时包含峰形和传输，不把损失当作聚焦。

## 12. 二阶、非高斯和多模态限制

当一阶残差降低后，条件厚度仍通过

$$
\frac12\operatorname{tr}
[(H\Sigma_\varepsilon)^2]
$$

及三、四阶中心矩产生峰宽、偏移和尾部。局部协方差不能描述：

- 明显偏态或重尾；
- 多个条件分支；
- 稀疏极端粒子；
- 强孔径裁剪；
- 空间电荷和粒子相互作用。

所有局部预测最终必须与冻结粒子的直接FWHM、分位宽、tail fraction、mode fraction和hit rate比较。

## 13. 可证伪假设

### 13.1 H1：切向closure不足以预测真实峰宽

保持同一条件均值流形和分析器，改变条件残差厚度时，直接粒子峰宽应改变，而沿流形的`D1/D2/D3`
基本不变。

### 13.2 H2：残差模态可预测主要展宽来源

`q_k`排序应与冻结test cohort上的逐模态消融或受控源工况结果一致，并对合理尺度和bootstrap保持稳定。

### 13.3 H3：受约束projector可预测局部重优化收益

在信赖域内，`J0-Jmin`应预测source-weighted重新优化的方差改善；超出信赖域后误差应有可解释增长。

### 13.4 H4：新增场区只有在增加有效控制方向时才有稳定收益

若`a_perp≈0`，充分重新优化后新增区对locked observed source不应产生超过不确定度的稳健收益。若
`a_perp`与`b_perp`显著重叠，其直接粒子收益应与`ΔJ_lin`在局部范围内一致。

### 13.5 H5：诊断能选择正确干预

至少两种源工况下，切向/残差占比、`F_lin`和active constraints应事前预测：继续改分析器、增加真正
独立控制方向，还是需要改变源条件分布。

## 14. 最低验证要求

### 14.1 Source

- 共同pre-pulse物理时刻；
- detector-blind训练、验证和locked test；
- 粒子ID、cohort hash、单位、坐标和尺度冻结；
- 至少两种独立source operating condition；
- 条件均值、异方差、残差尾部和bootstrap不确定度；
- 不用detector结果选择条件模型阶数。

### 14.2 导数与线性代数

- 到达时间`g`至少两条独立路径；
- `∂g/∂θ`的步长平台或独立实现；
- null-space与原约束残差一致；
- projector与直接最小二乘/QP一致；
- rank和模态对预注册尺度、容差及bootstrap的稳定性；
- 直接轨迹确定局部信赖域。

### 14.3 公平架构比较

同一冻结源、粒子ID和预算下分别充分优化：

```text
two-zone baseline
three-zone design
source-weighted constrained design
unweighted derivative-closure design
```

冻结几何/电压上限、detector、命中规则、峰算法、优化预算和随机种子策略。不得在affine源上优化三区，
再直接换observed源并把崩溃解释为三区原理失效。

### 14.4 三维与统计

- ideal segmented、真实轴线场和3D SIMION；
- 关键COMSOL或独立轨迹实现；
- 至少三个质量点；
- N≥1000 locked test，优选N≥5000或独立重复；
- direct FWHM、分位宽、尾部、主峰比例、命中率和bootstrap区间；
- 基本电压、几何和数值敏感性。

## 15. 设计决策图

定义切向和条件残差的一阶占比诊断。只有在相同冻结cohort与同一近似阶次下比较：

| 观察 | 优先动作 |
|---|---|
| 切向像差主导 | 继续优化N区OA、反射镜或主流形斜率 |
| 条件残差主导且`F_lin`高 | 在现有架构内做source-weighted有界重优化 |
| 条件残差主导且`F_lin`低 | 改变源、孔径匹配、波形或增加真正独立控制方向 |
| 命中拓扑频繁改变 | 放弃纯projector结论，转入联合峰形—传输优化 |
| 二阶/尾部主导 | 使用Hessian、高阶矩和直接粒子目标 |

## 16. 当前证据边界

现有历史证据已表明：固定三区真实PA中，observed `z-v_z`残差比横向恢复更强地恶化N=100峰宽。
它支持提出本文问题，但尚未完成条件源建模、受约束projector、重新编译、公平双区/三区比较、N≥1000、
多质量或独立求解器验证。因此本文状态仍为`PAPER_1_CANDIDATE / EVIDENCE_REQUIRED`，不能改变524 Da
Formal基线或直接支持投稿结论。

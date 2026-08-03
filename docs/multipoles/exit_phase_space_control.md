# 多极杆出口相空间控制：电压、频率、几何、碰撞与接口匹配

> **知识卡**：`document_id=multipoles.exit_phase_space_control` · `version=0.1.0` ·
> `maturity=provisional` · `role=cross_project_design_family_knowledge`
>
> 本文件回答“调整多极杆电压、频率、长度、孔径、锥度和端部结构，能否减小出口位置与角度分散，
> 以及什么情况下属于真正冷却”。它适用于无碰撞四、六、八极杆和明确建模的碰撞多极杆，但不保存
> 任何项目当前电压、尺寸、压力、候选状态或正式结果。外部研究只作为可行性证据，不能直接成为项目
> baseline、验收阈值或优化结论。

## 1. 结论先行

可以通过调整 RF 幅值、频率、DC 偏置、轴向能量、杆长、内切半径、锥度、端部渐变和多极阶数，使离子在指定出口参考平面的空间分散或角度分散减小；但必须区分以下三类完全不同的物理结果。

### 1.1 无碰撞、无损失的保守系统

在理想无碰撞电场中，多极杆可以：

* 改变横向相空间椭圆的方向和形状；

* 把束腰放到指定出口平面；

* 消除入口失配造成的位置—角度相关；

* 减少非线性场、幅相误差和边缘场额外产生的投影展宽；

* 通过轴向加速减小几何角度 $v_\perp/v_z$。

但是它不能任意压缩完整的细粒度相空间体积。对已经匹配、无明显相关的束流，单纯增强横向聚焦通常表现为：

* 空间束斑变小，角度分散变大；或

* 角度分散变小，空间束斑变大。

如果入口束流严重失配、位置与角度高度相关，则在某个平面上，空间 RMS 和角度 RMS **可能同时低于入口值**；这表示相关被消除、相空间被重新匹配，不表示发射度或亮度被真正压缩。

### 1.2 孔径筛选或触杆损失

缩小孔径、提高 RF 使大振幅粒子触杆，或者只统计穿过中心区域的离子，可能让存活粒子的空间和角度分散同时变小。该结果属于**选择或刮束**：

* 传输率下降；

* 被丢弃粒子携带的相空间被排除；

* 不能称为无损冷却或亮度提升。

### 1.3 碰撞、反馈或其他耗散系统

缓冲气体碰撞等非哈密顿耗散机制可以真正降低横向动能和相空间发射度，使空间与角度分散同时减小；但最终受以下因素限制：

* 气体热运动与扩散；

* RF 微运动中断加热；

* 出口 RF 边缘场；

* 压力下降区和气流；

* 空间电荷；

* 轴向停留时间与传输损失。

因此，若目标是“在保持较高传输率的同时，真实地同时减小出口束斑与角度”，通常需要：

> **碰撞冷却或其他耗散 + 主体多极杆约束 + 出口渐变/延伸段 + 轴向提取与下游匹配。**

## 2. 与现有知识文件的关系

本文件沿用以下知识文件的符号与模型边界：

* [多极杆共同理论](./foundations.md)：$2n$ 极场、电压约定、伪势、绝热性和边缘场；

* [四极杆理论](./quadrupole.md)：Mathieu 参数、RF-only 传输、有限长度和入口相空间；

* [高阶多极杆](./higher_multipoles.md)：六极杆、八极杆的非线性伪势和阶数选择；

* [碰撞与冷却](./collisions.md)：C0–C4 碰撞模型、RF 加热和验证要求。

本文默认 RF 幅值 $V$ 表示**一个相位组相对地的零到峰值幅值**，角频率为 $\Omega=2\pi f$，杆轴和平均束流方向为 $z$。

## 3. 出口观察面必须先定义清楚

仓库活动合同中的统一术语和字段以
[`common/multipole/README.md`](../../common/multipole/README.md#轴向部件与物理面术语)为准。本文件只说明
这些观察面的物理用途，不建立第二套字段：

1. **杆出口 `rod_z_max`**：实体杆终止位置，用于诊断杆端到下游接口之间的边缘场转换；
2. **规范交接面 `canonical handoff plane`**：跨部件输出 canonical 粒子状态的主优化和主评价面；
3. **近接口统计面 `near-interface census plane`**：器件紧邻下游的补充统计面；
4. **terminal 事件**：撞壁、数值标记、超时或其他终止条件产生的终态，不是物理面的别名。

杆端与 handoff 即使距离很近，也不能仅凭距离认定场效应为零；该区可能包含 RF 边缘场和轴向静电场。
因此，当前多极杆—oaTOF筛选统一在 handoff 面评价，杆端只保留为诊断。下游厚孔之后的存活分布会混入
孔径选择，不能作为主准直目标；必须同时报告 handoff 与 terminal 的粒子身份和传输率。

这种口径不要求在每个多极杆候选后运行完整 oaTOF：只要统一终端模型真实解析到 handoff，即可评价上游
交付给 oaTOF 的准直状态。完整 oaTOF 只在候选通过上游筛选、需要验证脉冲捕获或整机性能时运行。

## 4. 出口相空间指标

### 4.1 位置与角度

对出口粒子去除质心后，定义：

$$
\tilde x=x-\langle x\rangle,
\qquad
\tilde y=y-\langle y\rangle.
$$

小角度理论中可用：

$$
x'=\frac{v_x}{v_z},
\qquad
y'=\frac{v_y}{v_z}.
$$

正式后处理建议使用：

$$
\theta_x=\operatorname{atan2}(v_x,v_z),
\qquad
\theta_y=\operatorname{atan2}(v_y,v_z),
$$

避免在大角度、低 $v_z$ 或反射粒子上失真。

对当前四、六、八极杆家族，主指标遵循公共工程合同：先由全部出射粒子的三维速度确定平均束流方向，
再分别报告平均方向相对轴线的倾斜和围绕该平均方向的中心化角展宽。$\theta_x,\theta_y$及其分量统计只
作为诊断，不能替代这两个主指标。

最小空间与角度指标为：

$$
\sigma_r=
\sqrt{\langle\tilde x^2+\tilde y^2\rangle},
$$

$$
\sigma_\theta=
\sqrt{\operatorname{Var}(\theta_x)+\operatorname{Var}(\theta_y)}.
$$

还应保存 $r_{68}$、$r_{95}$、$\theta_{68}$、$\theta_{95}$ 和 halo 比例，因为多极杆出口分布经常非高斯。

### 4.2 位置—角度相关和束腰

单平面的协方差矩阵为：

$$
\Sigma_x=
\begin{bmatrix}
\langle\tilde x^2\rangle & \langle\tilde x\tilde x'\rangle\\
\langle\tilde x\tilde x'\rangle & \langle\tilde x'^2\rangle
\end{bmatrix}.
$$

定义：

$$
C_x=\langle\tilde x\tilde x'\rangle.
$$

当 $C_x=0$ 时，束宽在无场漂移的一阶传播中处于驻点；它只有在该驻点为局部最小且传播假设成立时
才是 $x$ 方向束腰，$y$ 方向同理。仅仅使 $\sigma_x$ 很小而不检查相关量及驻点性质，可能得到一个
正在快速会聚或快速发散的交叉点，而不是稳定接口。

在下游无场漂移距离 $d$ 后：

$$
\sigma_x^2(d)
=
\sigma_x^2(0)
+2dC_x(0)
+d^2\sigma_{x'}^2(0).
$$

因此，下游接口设计至少应同时约束：

* $\sigma_x,\sigma_y$；

* $\sigma_{x'},\sigma_{y'}$；

* $C_x,C_y$；

* 目标下游平面处的预测束斑。

### 4.3 RMS 发射度

几何 RMS 发射度定义为：

$$
\varepsilon_x
=
\sqrt{
\langle\tilde x^2\rangle
\langle\tilde x'^2\rangle
-
\langle\tilde x\tilde x'\rangle^2
}.
$$

对非相对论质谱离子，更稳妥的守恒量是横向机械动量发射度：

$$
\varepsilon_{x,p_x}
=
\sqrt{
\langle\tilde x^2\rangle
\langle\tilde p_x^2\rangle
-
\langle\tilde x\tilde p_x\rangle^2
},
\qquad p_x=mv_x.
$$

轴向加速会使 $x'=p_x/p_z$ 变小，因此几何角度发射度可以下降；但若 $p_x$ 分布未改变，$\varepsilon_{x,p_x}$ 并未被冷却。需要注意，$\varepsilon_{x,p_x}$ 只有在线性、解耦、相位一致的保守映射中才可作为单平面不变量；存在 $x$–$y$、RF 相位或纵横耦合时，还应计算相位分辨的四维协方差、辛本征发射度或完整六维指标。

## 5. 无碰撞系统的基本限制

### 5.1 Liouville 与辛映射

无碰撞、无随机阻尼的电场轨迹是哈密顿运动。即使 RF 随时间周期变化，把时间或 RF 相位纳入完整状态后，细粒度相空间密度仍沿轨迹守恒。

在线性、解耦近似下：

$$
\mathbf u_{\mathrm{out}}=M\mathbf u_{\mathrm{in}},
\qquad
\mathbf u=(x,x')^T,
$$

$$
\Sigma_{\mathrm{out}}
=M\Sigma_{\mathrm{in}}M^T.
$$

若 $M$ 为辛矩阵且 $\det M=1$，则：

$$
\det\Sigma_{\mathrm{out}}
=
\det\Sigma_{\mathrm{in}},
$$

即线性 RMS 发射度不变。

在线性无场漂移中，若束宽驻点已验证为局部极小，则该束腰处 $C_x=0$：

$$
\sigma_x\sigma_{x'}=\varepsilon_x.
$$

因此，已匹配束流不能通过无损保守聚焦任意同时减小 $\sigma_x$ 和 $\sigma_{x'}$。

### 5.2 为什么有时两者看起来都变小

若入口存在很强相关：

$$
|C_x|\gg0,
$$

则入口投影乘积满足：

$$
\sigma_x\sigma_{x'}
=
\sqrt{\varepsilon_x^2+C_x^2}
>
\varepsilon_x.
$$

通过相空间旋转把 $C_x$ 调到接近零后，空间和角度两个 RMS 都有可能低于入口值，但发射度仍不变。这是**失配修复**，不是相空间冷却。

### 5.3 非线性和 RF 相位投影

真实多极杆中的以下因素会使投影 RMS 发射度增长：

* 高阶多极分量；

* 高阶杆本身的振幅相关慢运动频率；

* RF 相位混合；

* 边缘场；

* 幅值或相位不平衡；

* 偏心、倾斜和空间电荷。

优化几何和驱动可以减少这些**额外增长**，使出口更接近理想守恒极限；但这仍不是从理想极限以下产生新的亮度。

## 6. 四极杆中的线性匹配近似

对低 $|q|$ 的 RF-only 理想四极杆，伪势为：

$$
\Psi_2(r)
=
\frac{Q^2V^2}{m\Omega^2r_0^4}r^2
=
\frac12m\omega_s^2r^2,
$$

因此慢运动角频率为：

$$
\omega_s
=
\frac{\sqrt2|Q|V}{m\Omega r_0^2}
\approx
\frac{|q|\Omega}{2\sqrt2}.
$$

若 $v_z$ 近似常数，横向包络满足：

$$
\frac{\mathrm d^2x}{\mathrm dz^2}
+\kappa^2x=0,
\qquad
\kappa=\frac{\omega_s}{v_z}.
$$

长度为 $L$ 的均匀段传递矩阵为：

$$
M(L)=
\begin{bmatrix}
\cos\mu & \dfrac{\sin\mu}{\kappa}\\
-\kappa\sin\mu & \cos\mu
\end{bmatrix},
\qquad
\mu=\kappa L.
$$

其中 $\mu$ 是慢运动相位推进。近似地：

$$
\mu
=
\frac{\sqrt2|Q|VL}{m\Omega r_0^2v_z}.
$$

这给出一个重要工程结论：

> 杆长、RF 幅值、频率、内切半径和轴向速度的主要作用之一，是共同决定出口处的慢运动相位推进；它们不是彼此独立的“越大越好”参数。

可先用该矩阵求使 $C_x=C_y=0$ 或使下游目标平面束斑最小的候选，再以完整 RF 时域轨迹复验。

## 7. RF 幅值和频率怎样影响出口分散

### 7.1 提高 RF 幅值 V，固定 f,r_0,v_z

四极近轴下：

$$
\omega_s\propto V,
\qquad
\Psi\propto V^2,
\qquad
|q|\propto V.
$$

常见趋势：

* 主体约束增强；

* 可把较大振幅离子拉回中心；

* 在合适杆长下可减小出口空间束斑；

* 慢运动相位推进增加，可能出现过聚焦；

* 微运动速度和出口相位相关角度可能增大；

* 碰撞环境中的 RF 加热风险增加；

* 稳定裕量、表面场和功耗裕量下降。

所以“提高 RF 一定同时减小束斑和角度”是错误规则。

### 7.2 提高频率 f，固定 V,r_0,v_z

$$
\omega_s\propto\frac1\Omega,
\qquad
\Psi\propto\frac1{\Omega^2},
\qquad
|q|\propto\frac1{\Omega^2}.
$$

常见趋势：

* 约束和相位推进减弱；

* 束斑可能变大；

* Mathieu/绝热稳定裕量通常改善；

* 微运动位移和速度减小；

* 出口相位相关角度可能减小，但也可能因主体约束不足而增大。

### 7.3 同时提高 V 和 f

参数必须说明保持什么量不变：

* 保持 $V/\Omega$ 不变：四极近轴 $\omega_s$ 和伪势强度近似不变，而 $q\propto1/\Omega$；

* 保持 $q$ 不变：需要 $V\propto\Omega^2$，此时 $\omega_s\propto\Omega$，相位推进增加；

* 保持表面场不变：几何和电极轮廓还会进入约束，不能只按以上比例缩放。

自动设计器应优化以下派生量，而不是只优化原始 $V$ 和 $f$：

```text
Mathieu q / 稳定裕量
伪势深度
慢运动频率
相位推进
局部绝热性
微运动速度和能量
出口 RF 相位敏感度
表面最大场与驱动功率
```

### 7.4 RF 相位、幅值平衡和波形

两相位组的幅值不平衡、相位不等于 $\pi$、共模 RF 或谐波失真会引入：

* 中心轨道偏移；

* $x/y$ 两方向接受度不同；

* 旋转或偶极微运动；

* 出口角度和 halo 增长。

因此最优设计常常不是“更高 RF”，而是：

> 更准确的幅相平衡、更低的寄生多极场和更平滑的轴向 RF 连续性。

对脉冲束，可以把提取时刻与 RF 相位同步，降低相位投影展宽；对连续束必须评价均匀 RF 相位分布，不能只选有利相位。

## 8. DC、电位梯度和轴向能量

### 8.1 差模 DC

四极杆上的差模 DC 会同时聚焦一个方向并去聚焦另一个方向，并引入质量选择。它可以改变相空间旋转，但通常不能作为同时压缩两个横向方向的通用静态透镜。

RF-only 传输或冷却 mode 不应隐式加入差模 DC；需要时必须作为独立 mode 和机器合同字段。

### 8.2 共模 DC 与分段轴向梯度

所有杆共同施加的均匀 DC 偏置在理想无限长模型中不产生横向场，但分段偏置或附加电极可以形成轴向电场，控制：

* 轴向速度；

* 停留时间；

* 冷却长度；

* 出口提取；

* 反射和气体滞留。

增大轴向加速通常：

* 减少停留时间和碰撞数；

* 减小同一横向速度对应的几何角度；

* 降低主体横向相位推进；

* 可能削弱冷却和最终空间压缩。

### 8.3 轴向加速为什么能减小角度但不一定冷却

小角度下：

$$
\sigma_{x'}\approx\frac{\sigma_{v_x}}{\bar v_z}.
$$

若横向速度不变而轴向动能从 $K_z$ 增加到 $gK_z$：

$$
\sigma_{x'}\rightarrow\frac{1}{\sqrt g}\sigma_{x'}.
$$

这会改善下游几何发散，但 $p_x$ 和横向温度没有降低，因此不应称为横向冷却。

## 9. 杆长和相位推进

增大杆长 $L$ 会增加慢运动相位推进和 RF 周期数，但出口束斑与角度通常随 $L$ **振荡变化**，不是单调改善。

可能出现：

* 欠聚焦：出口仍在会聚；

* 束腰：$C_x,C_y\approx0$；

* 过聚焦：束腰已位于上游，出口重新发散；

* 非整数 RF 相位投影：连续束角度展宽；

* 高阶场中不同振幅具有不同相位推进，形成像差。

因此杆长应与 $V,f,r_0,v_z$ 联合优化。只增加长度而不重新匹配其他参数，不是可靠的出口压缩方法。

在碰撞环境中，长度还控制冷却和扩散时间：

* 太短：尚未充分冷却；

* 合适：达到目标温度与束斑；

* 太长：扩散、反应、空间电荷和传输损失增加。

## 10. 内切半径、杆径和真实场质量

### 10.1 内切半径 r_0

对四极近轴：

$$
\omega_s\propto r_0^{-2},
\qquad
\Psi\propto r_0^{-4}.
$$

减小 $r_0$ 在固定 $V,f$ 下可显著增强约束和空间压缩，但同时：

* 减小机械接受孔径；

* 提高表面场和击穿风险；

* 放大装配误差的相对影响；

* 增加触杆和污染敏感性；

* 可能提高出口微运动角度。

### 10.2 圆杆半径和中心距

圆杆并不生成理想纯多极场。杆径比、中心距、外壳和支撑决定寄生多极分量。非线性场会造成：

* 振幅相关相位推进；

* 相空间折叠和 filamentation；

* halo；

* 出口 RMS 发射度增长。

优化杆径比可以减少额外像差，使出口位置和角度分布更集中，但它是在**防止发射度增长**，不是凭空产生冷却。

### 10.3 机械误差和电气误差

必须联合扫描：

* 每根杆的横向偏移、倾角和直线度；

* 杆半径、圆度和端部倒角；

* RF 幅值不平衡；

* RF 相位误差；

* 共模电压；

* 分段间隙；

* 支撑介质和接地外壳。

仅在理想对称几何中获得小束斑，不足以证明可制造设计在出口仍满足角度和发射度目标。

## 11. 锥形、渐变半径和渐变 RF

### 11.1 渐变段的两种用途

沿 $z$ 改变 $r_0(z)$ 或 $V(z)$ 可以形成：

* **压缩段**：$V$ 增大或 $r_0$ 减小，横向约束向出口增强；

* **解压/准直段**：$V$ 减小或 $r_0$ 增大，约束向出口减弱。

锥形六极杆或八极杆能够在实验和轨迹模拟中形成明显空间聚焦 [3,4]，但束斑缩小并不自动代表角度或发射度同步下降；必须同时报告传输、角度和发射度。

### 11.2 四极杆中的绝热渐变

在四极谐振近似中，若慢运动频率随 $z$ 缓慢变化：

$$
\omega_s(z)
\propto
\frac{V(z)}{\Omega r_0(z)^2},
$$

绝热条件可写成：

$$
\chi(z)
=
\left|
\frac{v_z}{\omega_s^2}
\frac{\mathrm d\omega_s}{\mathrm dz}
\right|
\ll1.
$$

此时横向作用量近似守恒：

$$
J_x=\frac{E_x}{\omega_s}\approx\text{const}.
$$

对相位混合且匹配的束流：

$$
\sigma_x\propto\omega_s^{-1/2},
\qquad
\sigma_{v_x}\propto\omega_s^{1/2}.
$$

因此：

* 绝热增强约束：空间压缩，角度或横向速度增大；

* 绝热减弱约束：空间展开，角度或横向速度减小。

这正是“空间—角度交换”的定量表达。

### 11.3 非绝热渐变

较短的锥形或突变段可以像透镜一样，把束腰放到出口或下游目标面；但会带来：

* RF 相位依赖；

* 球差和高阶像差；

* 反射与触杆；

* 轴向 RF 场；

* 投影发射度增长。

因此渐变长度和形状应作为 3D 轨迹优化变量，不能只用二维伪势决定。

## 12. 出口 RF 边缘场与延伸段

若 RF 电势包络或几何在出口快速变化：

$$
\Phi(r,\theta,z,t)
\sim
V(z)
\left(\frac{r}{r_0(z)}\right)^n
\cos(n\theta)\cos\Omega t,
$$

则会出现轴向分量：

$$
E_z=-\frac{\partial\Phi}{\partial z}.
$$

出口边缘场可能把微运动能量转化为：

* 自由横向速度；

* 轴向能量展宽；

* RF 相位相关的出口角度；

* $x/y$ 耦合和 halo。

可评估的结构手段包括：

* RF-only 出口延伸杆；

* 小型 RFQ 或后置多极段；

* 分段 RF 幅值渐变；

* 平滑端部倒角和杆端轮廓；

* 缩小主杆到提取孔的无约束间隙；

* 保持各段 RF 相位连续；

* 在低压区完成最终提取；

* 下游静电透镜匹配。

在缓冲气体 RFQ 冷却器研究中，出口 RF 边缘场被发现会显著恶化束流质量；在出口加入小型 RFQ 延伸段能够降低该退化 [2]。这说明出口结构本身必须进入正式优化，而不能只优化无限长主体截面。

## 13. 多极阶数的影响

### 13.1 四极杆

优势：

* 近轴恢复力线性；

* 可用传递矩阵和相位推进做初步匹配；

* 适合在高真空中形成较小束斑；

* 作为最终压缩或接口匹配段通常最可控。

风险：

* 中心 RF 场和微运动高于同孔径高阶多极杆；

* 碰撞中可能出现更明显 RF 加热；

* 对宽质量范围的相位推进差异较大。

### 13.2 六极杆和八极杆

高阶多极伪势为：

$$
\Psi_n(r)
=
\frac{Q^2n^2V^2}{4m\Omega^2r_0^2}
\left(\frac r{r_0}\right)^{2n-2}.
$$

中心区更平坦，适合：

* 大接受度传输；

* 缓冲气体冷却；

* 反应或累积；

* 降低中心区微运动。

但其中心恢复力弱，且慢运动频率随振幅变化，因此：

* 无碰撞条件下不如理想四极杆容易形成低像差小束斑；

* 出口空间云团常较宽；

* 外层粒子会经历快速增长的场和绝热性；

* 锥形段可能空间聚焦，但容易产生振幅相关角度。

### 13.3 高阶主体 + 四极出口段

一个值得优化的候选架构是：

```text
六极/八极低场冷却或大接受度主体
→ 平滑过渡段
→ 四极最终压缩/匹配段
→ RF 延伸与提取
```

其目的不是假设该结构必然最优，而是把：

* 高阶多极的低场冷却优势；

* 四极杆的线性最终匹配优势

分配给不同轴向区域。过渡区必须用完整 3D 场和固定粒子表验证。

## 14. 碰撞冷却下能否同时减小空间和角度

### 14.1 真正的发射度降低

缓冲气体碰撞可以耗散横向动能。已有气体填充线性 RFQ 冷却器实验表明，束流发射度可以获得显著降低 [1]，因此“同时减小空间和角度”在物理上是可实现的，但它依赖碰撞、约束和提取的联合设计。

### 14.2 四极热平衡近似

在忽略空间电荷、离子接近横向温度 $T_\perp$ 且四极伪势为谐振势时：

$$
\langle x^2\rangle
=
\frac{k_BT_\perp}{m\omega_s^2},
$$

$$
\langle v_x^2\rangle
=
\frac{k_BT_\perp}{m}.
$$

因此：

$$
\sigma_x
\propto
\frac{\sqrt{T_\perp}}{\omega_s},
$$

$$
\sigma_{x'}
\approx
\frac{1}{v_z}
\sqrt{\frac{k_BT_\perp}{m}}.
$$

由此可见：

* 增强 RF 约束在固定 $T_\perp$ 下主要缩小空间束斑；

* 降低横向温度才能直接减小角度和横向速度；

* 提高 $v_z$ 可减小几何角度，但不降低横向温度；

* 若提高 RF 同时引起 RF 加热，空间可能缩小而角度恶化。

### 14.3 高阶多极的热分布尺度

令：

$$
\Psi_n(r)=A_nr^p,
\qquad
p=2n-2,
$$

$$
A_n
=
\frac{Q^2n^2V^2}{4m\Omega^2r_0^{2n}}.
$$

在二维热平衡、无空间电荷且机械孔径足够大时：

$$
P(r)\,\mathrm dr
\propto
r\exp\left[-\frac{A_nr^p}{k_BT_\perp}\right]\mathrm dr.
$$

径向二阶矩为：

$$
\langle r^2\rangle
=
\left(\frac{k_BT_\perp}{A_n}\right)^{2/p}
\frac{\Gamma(4/p)}{\Gamma(2/p)}.
$$

这说明：

* 降低 $T_\perp$ 会同时降低空间和速度分散；

* 提高 $V$ 可减小云团半径，但高阶多极对 $V$ 的半径响应指数较弱；

* 高阶多极中心低场有利于降低 RF 加热，但云团可能更宽；

* 空间电荷会破坏上述单粒子热平衡尺度。

### 14.4 压力和长度不是越大越好

提高压力或延长多极杆可能先改善冷却，随后出现：

* 气体扩散；

* 轴向速度过低；

* 反射和滞留；

* 空间电荷增强；

* RF 加热高能尾；

* 出口压力梯度和气流发散；

* 反应或团簇副产物。

正式优化必须使用已批准的 C1–C4 模型，并输出碰撞数、横向温度、出口相空间、传输和高能尾。

## 15. 不同调节量的方向性总结

下表中的趋势都依赖“其他量固定”的条件，不能脱离条件硬编码。

| 调节量                 | 常见空间效果         | 常见角度效果         | 是否真正降低发射度 | 主要风险           |
| ------------------- | -------------- | -------------- | --------- | -------------- |
| 提高主段 RF 幅值，其他固定     | 约束增强，合适匹配时束斑减小 | 微运动或过聚焦可使角度增大  | 否         | 稳定裕量、RF 加热、表面场 |
| 提高频率，幅值固定           | 约束减弱，束斑可能增大    | 微运动减小但失配可能增大角度 | 否         | 势阱不足、传输下降      |
| 增加杆长                | 可把束腰移到出口，也可过聚焦 | 随相位推进振荡        | 否；碰撞时可能   | 过聚焦、非线性相位混合    |
| 减小 $r_0$            | 强空间压缩          | 横向速度/角度可能增大    | 否         | 孔径、击穿、误差敏感性    |
| 向出口增强 $V$ 或减小 $r_0$ | 压缩             | 绝热条件下角度增大      | 否         | 端部轴向 RF 场、触杆   |
| 向出口减弱 $V$ 或增大 $r_0$ | 束斑展开           | 绝热条件下角度减小      | 否         | 下游孔径不匹配        |
| 轴向加速                | 空间由匹配决定        | 几何角度减小         | 否         | 冷却时间减少         |
| 缩小出口孔径              | 存活束斑减小         | 存活角度可能减小       | 否，属于刮束    | 传输和灵敏度下降       |
| 缓冲气体冷却              | 约束下束斑可减小       | 横向温度降低，角度减小    | 是         | 扩散、RF 加热、反应    |
| 平滑 RF 出口/小型延伸段      | 减少边缘场造成的额外扩散   | 减少相位相关角度       | 主要是防止增长   | 结构复杂、相位连续性     |
| 高阶主体转四极出口           | 主体大接受度，出口强匹配   | 可优化最终角度        | 碰撞时可能     | 过渡场非线性         |

## 16. 推荐的设计策略

### 16.1 目标：出口束斑最小

优先评估：

1. 四极或四极最终段；

2. 调整 $V,f,L,r_0$ 使束腰落在目标平面；

3. 允许适度收敛锥度或 RF 增强渐变；

4. 优化杆径比和端部，抑制非线性 halo；

5. 检查角度、发射度和下游漂移，不只看 $\sigma_r$。

### 16.2 目标：出口角度最小

优先评估：

1. 先通过碰撞降低横向温度；

2. 在出口使用平滑 RF 解压或增大 $r_0$；

3. 在低压区轴向加速；

4. 把空间束斑约束移到下游孔径允许范围；

5. 避免在高 RF 场半径处突然终止电极。

### 16.3 目标：空间和角度都尽量小

先判断入口是否只是失配：

* 若入口发射度已经很小但相关很强：用无碰撞匹配消除 $C_x,C_y$；

* 若入口真实发射度很大：必须引入碰撞或其他耗散；

* 若出口退化主要由边缘场造成：先修复出口延伸和 RF 渐变；

* 若通过孔径筛选得到小束斑：必须把传输损失列入硬约束。

推荐架构：

```text
入口匹配
→ 主体 RF 约束
→ 缓冲气体冷却（需要时）
→ 低像差最终匹配段
→ 平滑 RF 出口
→ 轴向提取/加速
→ 接口参考平面
```

### 16.4 宽质量范围

固定 $V,f,r_0$ 时，四极杆慢运动频率和相位推进随 $Q/m$ 变化。一个设置不可能对很宽的 $m/z$ 范围产生完全相同的出口束腰。

应使用：

* 最差质量点约束；

* 多质量 Pareto 优化；

* 质量分段 mode；

* 较短、低相位推进的鲁棒传输段；

* 高阶主体 + 四极最终段候选；

* 固定粒子表的全质量扫描。

不得只对单一标称质量优化后宣称全质量范围出口相空间一致。

## 17. 候选优化变量分类

下列清单是设计变量catalog的候选分类，不是可直接执行的campaign schema。参数是否开放、属于原生量还是
派生量、允许包络和联动约束，必须遵守
[`DEVELOPMENT_STANDARDS.md`](../DEVELOPMENT_STANDARDS.md#声明式实验与参数治理)并由目标项目机器合同决定；
不得把所有字段同时开放为无约束笛卡尔积。

### 17.1 驱动变量

```yaml
drive_variables:
  rf_frequency_Hz: variable_or_fixed
  rf_phase_to_ground_zero_to_peak_V: variable_or_profile
  waveform: sinusoidal
  phase_group_difference_rad: constrained_to_pi
  amplitude_imbalance: tolerance_distribution
  common_mode_dc_V: variable_or_fixed
  differential_dc_V: disabled_or_mode_specific
  axial_dc_profile: segmented_profile
  extraction_phase: continuous_or_synchronized
```

### 17.2 几何变量

```yaml
geometry_variables:
  multipole_order_2n: [4, 6, 8]
  active_length_m: variable
  inscribed_radius_profile: constant_or_spline
  rod_radius_profile: constant_or_spline
  rod_center_profile: parameterized
  end_taper_length_m: variable
  end_shape: parameterized
  segment_gap_m: variable
  rf_extension_length_m: variable
  exit_aperture_m: variable
  downstream_reference_plane_m: fixed_interface
```

### 17.3 物理与运行变量

```yaml
operation_variables:
  mass_to_charge_range_Th: project_contract
  axial_energy_per_charge_eV: variable_or_distribution
  inlet_phase_space_table: immutable_file
  rf_entry_phase: uniform_or_synchronized
  gas_species: optional
  gas_pressure_profile: optional
  collision_model_level: C0_to_C4
  space_charge_model_level: S0_to_S3
```

## 18. 概念性优化记录示例

以下JSON只展示应冻结的语义类别，不是仓库Schema、字段权威或可直接提交的配置。实现时应复用已有
resolved design、canonical粒子状态和项目acceptance合同，不按本例建立第二套机器真值。

```json
{
  "model_id": "multipole.exit_phase_space_control.v1",
  "conventions": {
    "rf_amplitude": "phase_to_ground_zero_to_peak",
    "angle_definition": "three_dimensional_mean_direction_and_centered_angular_spread",
    "position_statistics": "centroid_removed",
    "emittance_definition": "rms_mechanical_momentum",
    "exit_crossing": "first_valid_positive_z_crossing"
  },
  "device": {
    "multipole_order_2n": "design_variable",
    "mode": "rf_only_transport_or_collision_cooling"
  },
  "exit_plane": {
    "plane_id": "interface_plane_v1",
    "z_m": "project_value",
    "evaluation_role": "canonical_handoff_primary"
  },
  "objectives": {
    "minimize": [
      "sigma_r",
      "sigma_theta",
      "mechanical_momentum_emittance_x",
      "mechanical_momentum_emittance_y",
      "halo_fraction"
    ]
  },
  "hard_constraints": {
    "transmission_min": "project_value",
    "surface_field_max_V_per_m": "project_value",
    "stable_mass_range_Th": "project_value",
    "adiabaticity_max_in_occupied_region": "project_value",
    "downstream_aperture_clearance": "project_value",
    "collision_data_extrapolation": "forbidden"
  },
  "diagnostics": {
    "phase_resolved": true,
    "mass_resolved": true,
    "loss_reason_required": true,
    "covariance_required": true,
    "downstream_free_drift_projection": true
  }
}
```

硬约束不满足的候选应直接淘汰，不应用目标函数惩罚项把它“优化成可接受”。

## 19. 优化目标与 Pareto 输出

不建议把“空间最小”和“角度最小”提前合并为唯一标量，因为它们常是相互竞争的目标。推荐输出 Pareto 前沿：

$$
\mathcal P
=
\left\{
(\sigma_r,\sigma_\theta,
\varepsilon_{x,p_x},\varepsilon_{y,p_y},
1-\eta_T,H)
\;\middle|\;
\text{candidate satisfies all hard constraints}
\right\}.
$$

其中：

* $\eta_T$：传输率；

* $H$：halo 或高分位尾部指标。

若工作流必须使用标量，可在通过全部硬约束后使用归一化目标：

$$
J
=
w_r\left(\frac{\sigma_r}{r_*}\right)^2
+w_\theta\left(\frac{\sigma_\theta}{\theta_*}\right)^2
+w_\varepsilon\left(
\frac{\varepsilon_{x,p_x}\varepsilon_{y,p_y}}
{\varepsilon_*^2}
\right)
+w_H\frac{H}{H_*}.
$$

权重、归一化尺度和选择理由必须写入 run config。

## 20. 推荐仿真流程

### 20.1 L0：解析初筛

计算：

* 四极 $a,q$ 与稳定裕量；

* 伪势深度；

* 慢运动频率；

* 相位推进；

* 绝热性；

* 热平衡特征半径；

* 表面场和功率初值。

### 20.2 L1：理想有限长度轨迹

使用固定入口粒子表，扫描：

* $V,f,L,r_0$；

* RF 相位；

* 质量范围；

* 轴向能量；

* 出口束腰和协方差。

### 20.3 L2：真实二维截面

拟合目标多极项和寄生项，比较：

* 束斑；

* 角度；

* 发射度；

* halo；

* 触杆位置。

### 20.4 L3：完整三维端部与接口

必须包含：

* 入口和出口边缘场；

* 锥度或幅值渐变；

* 分段缝隙；

* RF 延伸段；

* 提取孔和下游透镜；

* 真实接口参考平面。

### 20.5 L4：碰撞、空间电荷和公差

加入：

* 已版本化碰撞模型；

* 压力和气流；

* 空间电荷；

* 多种随机种子；

* 机械与电气公差 Monte Carlo。

最终比较必须使用同一粒子表、同一接口平面、同一 angle/emittance 定义和同一损失判据。

## 21. 必须输出的结果

每个候选至少输出：

| 类别  | 必须输出                                                            |
| --- | --------------------------------------------------------------- |
| 传输  | 总传输、质量分辨传输、损失原因和损失 $z$                                          |
| 空间  | 质心、$\sigma_x,\sigma_y,\sigma_r,r_{68},r_{95}$                   |
| 角度  | $\sigma_{\theta_x},\sigma_{\theta_y},\sigma_\theta,\theta_{95}$ |
| 相关  | $C_x,C_y$、完整协方差矩阵                                               |
| 发射度 | 几何 RMS 与动量 RMS 发射度                                              |
| RF  | 出口 RF 相位、微运动速度、相位分箱指标                                           |
| 能量  | 横向/轴向动能、总能量分布和高能尾                                               |
| 下游  | 无场漂移到目标面后的预测束斑                                                  |
| 碰撞  | 碰撞数、横向温度、RF 加热诊断                                                |
| 鲁棒性 | 网格、时间步、粒子数、种子和公差收敛                                              |

## 22. 参考验证测试

| 测试 ID                                     | 内容                                                | 期望                              |
| ----------------------------------------- | ------------------------------------------------- | ------------------------------- |
| `phase_space.linear_symplectic.v1`        | 理想线性四极段                                           | $\det M=1$，动量发射度守恒              |
| `phase_space.waist_matching.v1`           | 解析相位推进候选                                          | 预测平面 $C_x,C_y\approx0$          |
| `phase_space.free_drift.v1`               | 出口状态向下游漂移                                         | 与协方差传播公式一致                      |
| `phase_space.adiabatic_taper.v1`          | 缓慢改变 $V(z)$ 或 $r_0(z)$                     | $J_x,J_y$ 近似守恒，空间—角度标度正确 |
| `phase_space.abrupt_exit_phase.v1`        | 突然截断 RF                                           | 能显示 RF 相位相关出口角度和能量              |
| `phase_space.acceleration.v1`             | 仅提高 $p_z$                                      | 几何角度减小，$\varepsilon_{x,p_x}$ 不变 |
| `phase_space.aperture_selection.v1`       | 缩小孔径                                              | 存活 RMS 可下降但传输同步下降，标记为 selection |
| `phase_space.zero_pressure.v1`            | $p\rightarrow0$                                   | 碰撞模型收敛到 C0                      |
| `phase_space.collision_cooling.v1`        | 已验证缓冲气体模型                                         | 横向动能和发射度可下降，且统计收敛               |
| `phase_space.fringe_extension.v1`         | 主杆出口与延伸段比较                                        | 记录相位、角度、能量与传输差异，不预设必然改善         |
| `phase_space.mass_sweep.v1`               | 多质量固定设置                                           | 解析并验证相位推进和出口匹配的质量依赖             |
| `phase_space.cross_solver.v1`             | 独立求解器                                             | 同一粒子表和接口平面下统计一致                 |
| `phase_space.tolerance.v1`                | 几何和幅相 Monte Carlo                                 | 输出通过率和置信区间                      |

## 23. 常见错误命题

以下命题不得进入正式知识或自动优化规则：

1. **RF 电压越高，出口束斑和角度一定都越小。**

2. **频率越高，约束一定越强。**

3. **杆越长，出口一定越集中。**

4. **高阶多极杆中心场更低，所以出口束斑一定更小。**

5. **锥形杆能聚焦，所以一定降低发射度。**

6. **出口孔径变小后 RMS 下降，说明完成了冷却。**

7. **轴向加速后角度变小，说明横向温度下降。**

8. **只在机械杆端计算位置和速度即可代表下游接口。**

9. **只优化单一质量即可代表宽质量范围。**

10. **二维伪势足以预测出口角度和边缘场。**

11. **有缓冲气体就一定冷却，不需要 RF 加热和扩散模型。**

12. **只报告存活离子的束斑，不报告传输和损失。**

## 24. 面向当前 RF 多极杆设计族的建议

当前四、六、八极杆项目仍是无碰撞RF传输设计线，不能借用碰撞冷却论文把准直改进表述为发射度冷却。
最小、统一且与现有架构一致的后续机器链为：

```text
design profile + source + typed operating mode + downstream terminal profile
→ resolved geometry and drive
→ fixed particle table
→ COMSOL / SIMION independent trajectories
→ canonical handoff state
→ common exit phase-space analyzer
→ Pareto and acceptance report
```

当前首选基线是既有 `segmented_rod_axial_acceleration`，因为它以沿杆段逐级变化的共模电势增加轴向速度，
同时避免新增一套仅用于准直的特殊几何。后续优化应保持总电位差、RF、源、机械几何、数值设置和
terminal连续性不变，只把分段电位分配作为有依据的工程优化量；不得从已有N=100事后结果直接宣称最优。

筛选和评价顺序固定为：

1. 在 canonical handoff 面比较平均方向、中心化角展宽、束流质心和中心化空间展宽；

2. 同时约束 handoff 传输、terminal 传输、平均能量、能量展宽、尾部和损失身份；

3. 用杆端状态诊断 `rod exit → handoff` 的边缘场转换，但不把杆端指标替代主目标；

4. 先用SIMION做固定总电位差的分段电位窄范围筛选，再用少量入选点做COMSOL独立复核；只有该路线
   不能满足接口预算时，才分别建立RF幅值/频率、杆长或出口渐变等独立campaign；

5. 候选通过上游筛选后，才进入完整oaTOF脉冲捕获、分析器传输和整机性能验证；

6. 若未来建立碰撞冷却，使用独立workflow和碰撞合同评价真实横向温度及发射度降低。

## 25. 外部研究证据的正确使用

已有研究支持以下**可行性结论**：

* 气体填充线性 RFQ 可以显著降低离子束发射度；

* 出口 RF 边缘场会恶化冷却后束流质量，出口小型 RFQ/延伸段可降低该退化；

* 锥形八极杆能够实现明显空间聚焦，但传输和下游耦合可能形成权衡；

* 轴向 DC 场可以缩短碰撞多极杆中的停留时间并改善特定运行性能 [6,7]；

* 高 RF 幅值并非无限有利，外层非绝热运动、空间电荷和 RF 能量注入会限制有效约束 [5,8,9]。

这些研究不能直接提供本项目的最佳电压、频率、锥度或压力。所有参数仍须经过统一机器合同、独立求解器、收敛和公差验证。

## 26. 参考文献

1. Herfurth F, Dilling J, Kellerbauer A, et al. *A linear radiofrequency ion trap for accumulation, bunching, and emittance improvement of radioactive ion beams*. Nuclear Instruments and Methods in Physics Research A, 2001, 469(2): 254–275. DOI: 10.1016/S0168-9002(01)00168-1.

2. Boussaid R, Ban G, Quéméner G, Merrer Y, Lorry J. *Development of a radio-frequency quadrupole cooler for high beam currents*. Physical Review Accelerators and Beams, 2017, 20: 124701. DOI: 10.1103/PhysRevAccelBeams.20.124701.

3. Röttgen M A, Judai K, Antonietti J M, Heiz U, Rauschenbach S, Kern K. *Conical octopole ion guide: Design, focusing, and its application to the deposition of low energetic clusters*. Review of Scientific Instruments, 2006, 77: 013302. DOI: 10.1063/1.2162439.

4. Shao Q, Zhao J. *Ion trajectory simulations of a conical octopole ion guide and its comparison with a parallel one in chemical ionization mass spectrometric applications*. Rapid Communications in Mass Spectrometry, 2018, 32(12): 965–972. DOI: 10.1002/rcm.8129.

5. Mikosch J, Frühling U, Trippel S, Schwalm D, Weidemüller M, Wester R. *Evaporation of buffer-gas-thermalized anions out of a multipole rf ion trap*. Physical Review Letters, 2007, 98: 223001. DOI: 10.1103/PhysRevLett.98.223001.

6. Loboda A, Krutchinsky A, Loboda O, et al. *Novel Linac II Electrode Geometry for Creating An Axial Field in a Multipole Ion Guide*. European Journal of Mass Spectrometry, 2000, 6(6). DOI: 10.1255/ejms.383.

7. Mansoori B A, Dyer E W, Lock C M, Bateman K, Boyd R K, Thomson B A. *Analytical performance of a high-pressure radio frequency-only quadrupole collision cell with an axial field applied by using conical rods*. Journal of the American Society for Mass Spectrometry, 1998, 9(8): 775–788. DOI: 10.1016/S1044-0305(98)00042-7.

8. Majima T, Santambrogio G, Bartels C, et al. *Spatial distribution of ions in a linear octopole radio-frequency ion trap in the space-charge limit*. Physical Review A, 2012, 85: 053414. DOI: 10.1103/PhysRevA.85.053414.

9. Höltkemeier B, Weckesser P, López-Carrera H, Weidemüller M. *Buffer-Gas Cooling of a Single Ion in a Multipole Radio Frequency Trap Beyond the Critical Mass Ratio*. Physical Review Letters, 2016, 116: 233003. DOI: 10.1103/PhysRevLett.116.233003.

## 27. 最终工程判断

多极杆的电压、频率和几何参数**能够显著改变出口空间和角度分布**，但设计器必须按以下逻辑判断结果：

```text
先检查是否只是相空间匹配
→ 再检查是否由孔径/损失筛选造成
→ 再检查轴向加速是否只改变几何角度
→ 最后判断是否存在真正耗散冷却
```

对无碰撞多极杆，最可靠的目标是：

> 在不增加发射度的前提下，把入口相空间匹配到目标接口平面，并最小化边缘场和非线性造成的额外增长。

对碰撞冷却多极杆，目标才可以升级为：

> 在满足传输、反应、压力、空间电荷和 RF 加热约束下，真实降低横向温度与发射度，并通过平滑出口把冷却后的相空间交付给下游部件。

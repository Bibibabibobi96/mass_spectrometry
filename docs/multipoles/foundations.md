# 多极杆共同理论、约定与模型层级

> **知识卡**：`document_id=multipoles.foundations` · `version=0.1.0` · `maturity=provisional` · `role=cross_project_design_family_knowledge`

本文件定义四极杆、六极杆、八极杆及一般 $2n$ 极杆共同使用的数学约定。四极杆的 Mathieu 稳定性和质量筛选见[四极杆理论](quadrupole.md)；碰撞与冷却见[碰撞与模型](collisions.md)。

> **重要**
>
> 所有公式都依赖电压参考方式。本文中的 $V$ 是一个相位组相对地的 RF 零到峰值；若硬件或论文给出相邻电极间差分值、杆对间值或峰峰值，必须先转换再代入公式。

## 1. 适用范围与术语

理想二维多极杆由 $2n$ 根沿 $z$ 轴延伸的电极组成，横截面中相邻电极交替施加相反电势。这里：

- $2n$：电极数量，对应中文“几极杆”；
- $n$：理想势函数的径向阶数；
- 四极杆：$2n=4$，因此 $n=2$；
- 六极杆：$2n=6$，因此 $n=3$；
- 八极杆：$2n=8$，因此 $n=4$。

“高阶空间谐波”与“高阶多极杆”不是同一概念。例如，四极杆真实圆杆场中的 $k=6$ 项常称为十二极场分量，但器件本身仍是四根电极的四极杆。

## 2. 坐标、质量与几何约定

- 杆轴和平均束流方向为 $z$。
- 横向位置用 $(x,y)$ 或极坐标 $(r,\theta)$，其中 $x=r\cos\theta$、$y=r\sin\theta$。
- $r_0$ 是轴线到理想电极边界的特征内切半径。它不是圆杆半径 $r_e$，也不一定等于圆杆中心到轴线的距离。
- $\theta_0$ 是多极场相对于 $x$ 轴的旋转角。
- 电荷写成 $Q=sze$，其中 $z\in\mathbb N^+$ 是电荷态绝对值，$s\in\{+1,-1\}$ 是极性符号。
- 质荷比定义为 $\mu=m/(zu)$，数值单位为 Th；$u$ 为统一原子质量常数，极性由 $s$ 单独保存。

对真实圆杆结构，建议机器合同同时保存：

```yaml
geometry:
  coordinate_convention_id: multipole.cartesian.z_axis.v1
  inscribed_radius_m: 0.004
  electrode_radius_m: 0.0046
  electrode_center_radius_m: 0.0086
  effective_length_m: 0.150
  aperture_definition: nearest_electrode_surface
```

## 3. 电压与波形约定

定义一个相位组相对地的电压幅值函数：

$$
W(t)=U+Vg(\Omega t+\phi),\qquad \Omega=2\pi f,
$$

其中 $g$ 是峰值绝对值为 1、平均值通常为 0 的周期函数。正弦 RF-only 运行可取 $U=0$、$g(\alpha)=\cos\alpha$；本文四极质量过滤章节使用 $W(t)=U-V\cos\Omega t$。

相邻电极交替施加 $+W(t)$ 和 $-W(t)$。本文默认：

| 量 | 定义 | 与差分电压的关系 |
|---|---|---|
| $U$ | 一个相位组相对地的 DC 幅值 | 两相位组之间 DC 差值为 $2U$ |
| $V$ | 一个相位组相对地的 RF 零到峰值 | 两相位组之间 RF 零到峰值为 $2V$，差分峰峰值为 $4V$ |
| $V_{pp,\mathrm{diff}}$ | 两相位组之间差分峰峰值 | $V=V_{pp,\mathrm{diff}}/4$ |
| $\phi$ | 电压波形相位 | 必须明确参考时刻和参考电极组 |

> **警告**
>
> 不要只保存字段名 `rf_voltage_V`。机器合同至少要保存 `reference`、`amplitude_type`、`polarity_groups` 和 `waveform`，否则存在 2 倍或 4 倍质量标尺错误。

## 4. 理想二维 $2n$ 极电势

在无自由电荷的二维区域内，电势满足 Laplace 方程。具有 $2n$ 重交替极性的最低阶解可写成：

$$
\Phi_n(r,\theta,t)
=
W(t)\left(\frac{r}{r_0}\right)^n
\cos\left[n(\theta-\theta_0)\right].
$$

理想电极表面是上式的等势面：

$$
\left(\frac{r}{r_0}\right)^n
\cos\left[n(\theta-\theta_0)\right]=\pm1.
$$

三个常用阶数的 Cartesian 形式为：

$$
\begin{aligned}
\Phi_2 &= \frac{W(t)}{r_0^2}(x^2-y^2),\\
\Phi_3 &= \frac{W(t)}{r_0^3}(x^3-3xy^2),\\
\Phi_4 &= \frac{W(t)}{r_0^4}(x^4-6x^2y^2+y^4).
\end{aligned}
$$

四极杆的力对位移线性；六极杆和八极杆的力分别含二次和三次位置项，因此完整横向运动通常是非线性的。

## 5. 电场、力与尺度

由 $\mathbf E=-\nabla\Phi$，理想 $2n$ 极场的极坐标分量为：

$$
\begin{aligned}
E_r &= -\frac{nW(t)}{r_0}
\left(\frac{r}{r_0}\right)^{n-1}
\cos[n(\theta-\theta_0)],\\
E_\theta &= \frac{nW(t)}{r_0}
\left(\frac{r}{r_0}\right)^{n-1}
\sin[n(\theta-\theta_0)].
\end{aligned}
$$

理想纯多极场的幅值与角度无关：

$$
|\mathbf E_n|
=
\frac{n|W(t)|}{r_0}
\left(\frac{r}{r_0}\right)^{n-1}.
$$

| 器件 | $|E|$ 的近轴尺度 | 瞬时力非线性 |
|---|---:|---:|
| 四极杆 | $r$ | 线性 |
| 六极杆 | $r^2$ | 二次 |
| 八极杆 | $r^3$ | 三次 |

无磁场时完整轨迹方程为：

$$
m\ddot{\mathbf r}
=
Q\mathbf E(\mathbf r,t)
+\mathbf F_{\mathrm{collision}}
+\mathbf F_{\mathrm{space\ charge}}.
$$

加入磁场时应使用 $Q(\mathbf E+\dot{\mathbf r}\times\mathbf B)$。任何“忽略碰撞”或“忽略空间电荷”都必须是显式模型选择，而不是求解器默认行为。

## 6. RF 伪势与慢运动近似

对于单频 RF 电势

$$
\Phi(\mathbf r,t)=\Phi_{\mathrm{rf}}(\mathbf r)\cos\Omega t,
$$

当 RF 周期远短于慢运动时间尺度，且一个微运动周期内场变化足够小，可把快速微运动平均为伪势能：

$$
\Psi(\mathbf r)
=
\frac{Q^2}{4m\Omega^2}
\left|\nabla\Phi_{\mathrm{rf}}(\mathbf r)\right|^2.
$$

代入理想 $2n$ 极场：

$$
\Psi_n(r)
=
\frac{Q^2n^2V^2}{4m\Omega^2r_0^2}
\left(\frac{r}{r_0}\right)^{2n-2}.
$$

慢运动的平均径向力为：

$$
F_{r,\mathrm{eff}}
=-\frac{\mathrm d\Psi_n}{\mathrm dr}
\propto-r^{2n-3}.
$$

![四极、六极和八极杆的归一化 RF 伪势随半径的尺度比较。](figures/multipole-pseudopotential-scaling.png)

*理想四极、六极和八极 RF 伪势的归一化径向尺度。高阶多极杆中心区更平坦，但这不等于所有条件下接受度或传输率必然更高。*

伪势是快速筛选工具，不是完整时域轨迹的替代品。以下情况不能只靠伪势发布结论：

- 接近电极或绝热性边界；
- RF 相位、入口突变或边缘场主导；
- 波形非正弦且高次谐波显著；
- 需要瞬时碰撞能量、RF 加热或反应截面；
- 需要预测非线性共振、触杆和有限时间损失。

## 7. 绝热性参数

本文定义局部绝热性参数为：

$$
\eta(\mathbf r)
=
\frac{2|Q|}{m\Omega^2}
\left|\nabla |\mathbf E_{\mathrm{rf}}(\mathbf r)|\right|.
$$

对理想 $2n$ 极场：

$$
\eta_n(r)
=
\frac{2|Q|n(n-1)V}{m\Omega^2r_0^2}
\left(\frac{r}{r_0}\right)^{n-2}.
$$

- 四极杆 $n=2$ 时，$\eta_2$ 在理想截面中与半径无关，并与本文电压约定下 RF-only Mathieu $|q|$ 相同。
- 六极杆和八极杆中，$\eta$ 随半径增长；中心区最接近绝热，靠近电极时最容易失效。
- 文献中的绝热性参数可能因电压参考方式或定义系数不同而相差常数倍。机器合同必须保存 `adiabaticity_definition_id`。

对 $n>2$，若项目合同给出允许上限 $\eta_{\max}$，可定义初筛半径：

$$
\frac{r_{\mathrm{ad}}}{r_0}
=
\left[
\frac{\eta_{\max}m\Omega^2r_0^2}
{2|Q|n(n-1)V}
\right]^{1/(n-2)}.
$$

该半径只表示伪势近似的局部可信范围，不等于实际机械接受半径或传输率边界。

## 8. 尺度律与设计含义

| 量 | 主要尺度 |
|---|---|
| RF 电场 | $E\sim V/r_0$ |
| 伪势特征深度 | $\Psi\sim Q^2V^2/(m\Omega^2r_0^2)$ |
| 四极杆 Mathieu 参数 | $a,q\sim Q\{U,V\}/(m\Omega^2r_0^2)$ |
| 绝热性 | $\eta\sim QV/(m\Omega^2r_0^2)$ |
| 驻留 RF 周期数 | $N=fL/v_z$ |

缩小 $r_0$、提高 $V$ 或降低 $\Omega$ 可以增强约束，但同时改变表面场与击穿裕量、RF 电容和驱动电流、机械误差相对孔径、束流接受度、微运动能量和污染容限。因此不能只根据无量纲动力学做几何缩放。

## 9. 波形与方程类型

| 场与波形 | 数学类型 | 首选初筛方法 | 正式验证 |
|---|---|---|---|
| 正弦理想四极场 | 线性 Mathieu 方程 | 特征值或单周期矩阵 | 有限长度时域轨迹 |
| 任意周期理想四极场 | 线性 Hill 方程 | 单周期传递矩阵/Floquet 乘子 | 真实波形时域轨迹 |
| 正弦六极/八极场 | 非线性周期 ODE | 伪势与绝热性 | 直接时域轨迹 |
| 任意周期高阶多极场 | 非线性周期 ODE | 伪势仅作谨慎估算 | 直接积分加变分/统计分析 |

> **警告**
>
> “所有多极杆都用 Mathieu 稳定图”是错误规则。Mathieu 方程来自理想四极场的线性位置依赖；六极杆和八极杆不能直接套用四极 $a$–$q$ 稳定区。

## 10. 有限长度、端部与轴向场

理想二维模型假定电极无限长，因此 $E_z=0$。真实装置在入口、出口、分段缝隙、透镜和端部存在三维边缘场，可能引起：

- 非绝热 RF 注入；
- 横向与轴向能量交换；
- RF 相位相关的入口接受度；
- 轴向反射、延迟或加速；
- 端部触杆和孔径损失；
- 段间相位或幅值不连续造成的加热。

满足以下任一需求时，必须进入三维模型：

- 绝对传输率、出口相空间或能量分布；
- 入口/出口孔径、透镜、预过滤杆或后置杆；
- 分段电极、轴向 DC 梯度或行波；
- 碰撞池中的压力梯度和气流；
- 正式机械几何和 CAD 验收。

## 11. 圆杆、外壳与空间谐波

真实截面场可在中心区域展开为：

$$
\frac{\Phi(r,\theta,t)}{W(t)}
=
\sum_{k=1}^{\infty}
A_k\left(\frac{r}{r_{\mathrm{ref}}}\right)^k
\cos[k(\theta-\theta_k)].
$$

目标器件应使目标项占主导，并报告寄生项。对理想对称四极杆，常见允许项为 $k=2,6,10,\ldots$；机械错位、电压不平衡和外壳不对称会引入原本被对称性禁止的项。

圆杆优化不应硬编码单一半径比。推荐：

1. 参数化圆杆半径、中心半径、外壳、支撑槽和端部倒角；
2. 用二维场快速拟合目标项与寄生项；
3. 用三维场检查端部和接口；
4. 用轨迹 KPI 与制造公差联合优化；
5. 把最终几何写入项目 baseline，而不是从某个求解器模型反向抄录。

## 12. 公共误差族

| 误差族 | 典型参数 | 主要后果 | 建议诊断 |
|---|---|---|---|
| 电极位置与直线度 | 每根杆的 $\Delta x(z),\Delta y(z)$、倾角 | 偶极/高阶场、触杆方位偏置 | 多极拟合、损失位置直方图 |
| 电极尺寸与圆度 | $r_{e,i}$、椭圆度、粗糙度 | 非线性场、峰尾、局部场增强 | 截面场残差、表面场统计 |
| RF 幅值不平衡 | 各相位组幅值、共模 | 接受度不对称、中心偏移 | 分电极基场叠加 |
| RF 相位误差 | 相位差偏离目标值 | 异常微运动、加热、损失 | 保存真实波形并扫相位 |
| DC 偏置与漂移 | 差模和共模 DC | 质量标尺或轴向漂移 | 独立通道校准 |
| 外壳/支撑/污染 | 接地边界、介质、表面电荷 | 场畸变和长期漂移 | 三维场与实验标定 |

## 13. 模型保真度层级

L0–L5只描述模型包含的物理和证据深度，不直接决定项目产物能否进入 Candidate 或 Formal。生命周期资格仍由目标项目的验收范围、机器合同和门禁独立决定；仿真型正式交付不以实验标定为默认前提。

| 层级 | 物理内容 | 最低证据 | 允许结论 |
|---|---|---|---|
| L0 | 解析理想场与尺度律 | 公式测试向量 | 可行性和无量纲范围 |
| L1 | 理想有限长度轨迹 | 时间步、RF 相位和孔径扫描 | 有限时间趋势 |
| L2 | 真实二维场 | 网格收敛和多极拟合 | 截面几何影响 |
| L3 | 完整三维场与接口 | 与结论相称的独立几何和轨迹比较 | 候选传输与峰形 |
| L4 | 误差、碰撞、空间电荷统计 | 样本/种子收敛、分布来源 | 鲁棒性和置信区间 |
| L5 | 实验校准 | 冻结数据、标定模型和适用域 | 在实验覆盖域内的校准结论 |

## 14. 最小物理合同

每个多极杆 mode 至少绑定：

```json
{
  "field_model_id": "multipole.ideal_2n.v1",
  "multipole": {
    "electrode_count": 4,
    "radial_order_n": 2,
    "orientation_rad": 0.0
  },
  "conventions": {
    "coordinate_id": "multipole.cartesian.z_axis.v1",
    "voltage_id": "multipole.pair_to_ground.zero_to_peak.v1",
    "r0_id": "nearest_ideal_electrode_surface.v1"
  },
  "waveform": {
    "type": "sinusoidal",
    "frequency_Hz": 2000000.0,
    "phase_reference": "x_positive_group_at_t0"
  },
  "assumptions": {
    "collision_model": "disabled",
    "space_charge_model": "disabled",
    "magnetic_field_model": "disabled"
  },
  "model_level": "L0"
}
```

派生量如 $a$、$q$、伪势、绝热性和驻留周期数应由统一 Python 参考实现计算，不应在多个软件中手工维护。

## 15. 公共参考测试

| 测试 ID | 内容 | 判据示例 |
|---|---|---|
| `multipole.laplace.v1` | 解析势满足 $\nabla^2\Phi=0$ | 随机点残差低于数值容差 |
| `multipole.symmetry.v1` | 旋转 $\pi/n$ 后电势反号 | 相对误差低于 $10^{-12}$ |
| `multipole.field_scaling.v1` | $E(\lambda r)=\lambda^{n-1}E(r)$ | 相对误差低于 $10^{-10}$ |
| `multipole.pseudopotential_scaling.v1` | $\Psi(\lambda r)=\lambda^{2n-2}\Psi(r)$ | 相对误差低于 $10^{-10}$ |
| `multipole.zero_voltage.v1` | $V,U\rightarrow0$ 时回到直线运动 | 轨迹误差随步长收敛 |
| `multipole.basis_superposition.v1` | 单位电压基场线性叠加 | 与直接场解一致 |

项目可采用更严格阈值，但不得降低测试语义或省略电压约定。

## 16. 参考资料

1. W. Paul, “Electromagnetic traps for charged and neutral particles,” *Reviews of Modern Physics* 62, 531–540 (1990), [DOI 10.1103/RevModPhys.62.531](https://doi.org/10.1103/RevModPhys.62.531).
2. D. Gerlich, “Inhomogeneous RF Fields: A Versatile Tool for the Study of Processes with Slow Ions,” *Advances in Chemical Physics* 82, 1–176 (1992), [DOI 10.1002/9780470141397.ch1](https://doi.org/10.1002/9780470141397.ch1).
3. D. J. Douglas, “Linear quadrupoles in mass spectrometry,” *Mass Spectrometry Reviews* 28, 937–960 (2009), [DOI 10.1002/mas.20249](https://doi.org/10.1002/mas.20249).
4. I. Szabo, “New ion-optical devices utilizing oscillatory electric fields. I. Principle of operation and analytical theory of multipole devices with two dimensional fields,” *International Journal of Mass Spectrometry and Ion Processes* 73, 197–235 (1986), [DOI 10.1016/0168-1176(86)80001-5](https://doi.org/10.1016/0168-1176(86)80001-5).

# Wiley–McLaren 型双区正交空间聚焦加速器

## 1. 文档职责

本文定义 oa-TOF 项目中双区正交加速器的一维、分段均匀场参考模型，给出：

- 坐标、电压、能量和长度的统一约定；
- 一阶空间—时间聚焦面的严格位置；
- 质量/电荷消去关系；
- `D = 0` 的特殊紧凑边界及其适用范围；
- 机器合同、参考程序和最低验证要求。

本文不保存当前项目电压、尺寸、候选状态或正式结果。当前事实仍以项目 `config/` 和 `docs/PROJECT.md` 为准。本文件用于替代活跃理论入口中的 `三栅加速器总长度符号推导.docx`。旧 DOCX 如需保留，只能作为带日期和 superseded 标记的历史证据，不能继续作为当前公式权威。

配套求解器无关参考实现为：

```text
analysis/accelerator_time_focus.py
```

正式使用前仍需由三维静电场、粒子轨迹、COMSOL/SIMION 对等和统一 FWHM 后处理闭合。

## 2. 名称与术语

推荐正式名称：

> **Wiley–McLaren 型双区正交空间聚焦加速器**

项目内可简称：

> **双区正交加速器** 或 **oa 加速器**

旧称“三栅加速器”只适合作为历史兼容名称。其不足在于：

- 真正决定一阶聚焦的是两个加速场区，而不是“栅”的数量；
- 实际第二场区可以由环栈、场整形电极或等效边界构成，并不一定只有三张实体栅网；
- “空间聚焦”比“加速器”更准确地说明该部件补偿的是初始释放位置造成的到达时间差。

机器类型 ID 建议使用：

```text
two_region_orthogonal_space_focusing_accelerator
```

## 3. 坐标、电压和几何约定

建立一维局部坐标 `x`，沿正交抽取方向增加：

| 平面 | 局部位置 | 电位 |
|---|---:|---:|
| 排斥极/起始边界 | `x = 0` | `V_R` |
| 中间栅/第一场区出口 | `x = g_1` | `V_G` |
| 末级场出口参考面 | `x = g_1 + g_2` | `V_X` |

所有解析公式先将末级出口电位作为参考：

$$
\widetilde V_R = V_R-V_X,
\qquad
\widetilde V_G = V_G-V_X.
$$

要求：

$$
\widetilde V_R>\widetilde V_G>0,
\qquad
g_1>0,
\qquad
g_2>0.
$$

为简化下文，除非特别说明，均写作：

$$
V_R\equiv\widetilde V_R,
\qquad
V_G\equiv\widetilde V_G,
\qquad
V_X=0.
$$

两个理想均匀场为：

$$
E_{A1}=\frac{V_R-V_G}{g_1},
\qquad
E_{A2}=\frac{V_G}{g_2}.
$$

离子在第一间隙内的标称释放位置为：

$$
x=x_c,
\qquad 0<x_c<g_1.
$$

当前参考模型默认：

$$
x_c=\frac{g_1}{2},
$$

但程序允许显式指定其他释放中心。

## 4. 能量每电荷与单位

令离子电荷量为：

$$
q=ze>0.
$$

本文统一使用能量每电荷：

$$
W\equiv\frac{K}{q},
$$

其 SI 单位为伏特。离子在位置 `x` 由静止释放并到达接地出口后的能量每电荷为：

$$
W(x)=V_R-E_{A1}x.
$$

在标称释放位置：

$$
W_0=V_R-E_{A1}x_c.
$$

若 `x_c=g_1/2`：

$$
W_0=\frac{V_R+V_G}{2}.
$$

离子穿过第一场区后、进入第二场区时的能量每电荷为：

$$
W_{2}(x)=W(x)-V_G=E_{A1}(g_1-x).
$$

因此实际动能为：

$$
K=qW=zeW.
$$

以电子伏特表示时：

$$
K[\mathrm{eV}]=zW[\mathrm V].
$$

禁止把 `W = 4000 V` 在未声明 `z=1` 的情况下直接写成“所有离子均为 4000 eV”。

### 4.1 空间宽度对应的能量宽度

设释放区完整轴向宽度为 `Δx`，分布关于 `x_c` 对称。仅由位置引入的能量每电荷半范围为：

$$
\Delta W_x=\frac{E_{A1}\Delta x}{2}.
$$

机器合同必须明确宽度语义，例如：

```json
{
  "release_full_width_mm": 1.0,
  "spatial_energy_half_range_V": 20.0,
  "spread_definition": "symmetric_full_width_and_half_range"
}
```

`Δx`、半宽、标准差和 FWHM 不得混用。

## 5. 理想模型假设

本解析模型要求：

1. 轴向一维运动；
2. 两场区内电场均匀且静态；
3. 离子初始轴向速度为零；
4. 栅极无厚度、无边缘场、无透射损失；
5. 无碰撞、无空间电荷、无磁场；
6. 离子不触及电极，且完整穿过两个加速区；
7. 时间起点对所有离子一致。

若存在初始轴向能量、延迟抽取、脉冲上升沿、三维边缘场或空间电荷，本文只能作为初值和回归参考，不能作为 Formal 结果。

## 6. 分段飞行时间

定义：

$$
\alpha=\frac{q}{m}.
$$

离子到达中间栅和末级出口时的速度分别为：

$$
v_2(x)=\sqrt{2\alpha\,[W(x)-V_G]},
$$

$$
v_3(x)=\sqrt{2\alpha W(x)}.
$$

各段时间为：

$$
t_1(x)=\frac{v_2(x)}{\alpha E_{A1}},
$$

$$
t_2(x)=\frac{v_3(x)-v_2(x)}{\alpha E_{A2}},
$$

$$
t_D(x)=\frac{D_A}{v_3(x)}.
$$

从释放到末级出口后距离 `D_A` 的总时间：

$$
T_A(x;D_A)=t_1+t_2+t_D.
$$

## 7. 一阶空间—时间聚焦面

一阶空间聚焦条件为：

$$
\left.\frac{\partial T_A}{\partial x}\right|_{x=x_c}=0.
$$

解得末级场出口面到一阶聚焦面的场自由漂移距离：

$$
D_A=
\frac{v_3^3}{\alpha E_{A1}}
\left[
\frac{1}{v_2}
+
\frac{E_{A1}}{E_{A2}}
\left(
\frac{1}{v_3}-\frac{1}{v_2}
\right)
\right]_{x=x_c}.
$$

由于 `v_2`、`v_3` 均正比于 `√α`，上式中的 `m/q` 完全消去。因此：

> 理想一阶聚焦面的几何位置只由电压、间距和释放中心决定，与离子质荷比无关。

可使用去掉公共 `√α` 因子的速度：

$$
\bar v_2=\sqrt{2[W_0-V_G]},
\qquad
\bar v_3=\sqrt{2W_0},
$$

于是：

$$
D_A=
\frac{\bar v_3^3}{E_{A1}}
\left[
\frac{1}{\bar v_2}
+
\frac{E_{A1}}{E_{A2}}
\left(
\frac{1}{\bar v_3}-\frac{1}{\bar v_2}
\right)
\right].
$$

### 7.1 聚焦面而不是固定出口面

定义：

$$
z_{A,\mathrm{out}}=z_{A,0}+g_1+g_2,
$$

$$
z_{A,f}=z_{A,\mathrm{out}}+D_A.
$$

其中：

- `z_A,out`：双区正交加速器末级场出口参考面；
- `z_A,f`：一阶时间聚焦面；
- `D_A`：两者之间的有符号距离。

含义如下：

| `D_A` | 含义 |
|---:|---|
| `D_A > 0` | 聚焦面位于出口下游无场区 |
| `D_A = 0` | 聚焦面恰好位于出口面 |
| `D_A < 0` | 数学聚焦面位于出口上游，不能按“出口后无场焦面”使用 |

改变 `V_R`、`V_G`、`g_1` 或 `g_2` 后，必须重新计算 `D_A` 和 `z_A,f`。不得把聚焦面永久硬编码为出口面。

### 7.2 等场退化检查

若 `E_A1=E_A2`，则：

$$
D_A=2(g_1+g_2-x_c).
$$

当 `x_c=g_1/2`：

$$
D_A=g_1+2g_2.
$$

这是参考程序的一个基础回归测试。

## 8. `D_A = 0` 的特殊紧凑边界

`D_A=0` 表示一阶聚焦面位于末级出口。它可以用于计算一个特殊的局部紧凑边界，但不能直接称为 oa-TOF 整机最优。

设外部给定：

- 标称能量每电荷 `W_0`；
- 由释放位置引入的能量半范围 `ΔW_x`；
- 释放区完整宽度 `Δx`；
- 第一间隙机械下限 `g_min`。

定义：

$$
r=\frac{W_0}{\Delta W_x},
\qquad
s=\frac{g_1^*}{\Delta x},
\qquad
 g_1^*=\max(\Delta x,g_{\min}).
$$

必须满足：

$$
0<s<r.
$$

否则中间电极相对出口的电位非正，当前模型失效。

第一场强和电压为：

$$
E_{A1}=\frac{2\Delta W_x}{\Delta x},
$$

$$
V_R=W_0+\Delta W_x s,
\qquad
V_G=W_0-\Delta W_x s.
$$

使 `D_A=0` 的场强比：

$$
\rho^*\equiv\frac{E_{A1}}{E_{A2}}
=
\frac{\sqrt r}{\sqrt r-\sqrt s}.
$$

因此：

$$
E_{A2}^*=\frac{E_{A1}}{\rho^*},
$$

$$
g_2^*
=
\frac{\Delta x}{2}
\left(r+\sqrt{rs}\right),
$$

$$
L_{A,\mathrm{compact}}
=g_1^*+g_2^*
=
\frac{\Delta x}{2}
\left(r+2s+\sqrt{rs}\right).
$$

### 8.1 工程下限生效时仍有闭式解

当 `g_min > Δx`：

$$
s=\frac{g_{\min}}{\Delta x},
$$

仍然存在上述闭式解，不需要为了该理想问题进行数值优化。

此时：

$$
L_{A,\mathrm{compact}}
=
 g_{\min}
+
\frac{r\Delta x}{2}
+
\frac{1}{2}\sqrt{r g_{\min}\Delta x}.
$$

因此，当固定机械下限生效时，总长不再与 `Δx` 严格线性；其中含有 `√Δx` 项。

### 8.2 为什么它不是整机最优

`D_A=0` 只回答：

> 如果允许一阶焦面恰好位于加速器出口，理想双区加速段可以做到多紧凑？

它没有考虑：

- 焦面到反射镜入口的布局；
- 加速器在焦面处的二阶时间曲率；
- 反射镜场强和穿透深度；
- 探测器位置；
- 三维边缘场与栅透过；
- 实际到达时间峰的 FWHM；
- 制造、电压和装配公差。

整机优化必须使用 `oatof_oaaccelerator_coupling.md` 中的联合时间模型。

## 9. 参考程序接口

### 9.1 核心 API

```python
focus_drift_mm(
    u1_v,
    u2_v,
    d1_mm,
    d2_mm,
    *,
    exit_v=0.0,
    release_position_mm=None,
    require_downstream_focus=True,
    zero_tolerance_mm=None,
)
```

历史位置参数名称保持兼容，但其物理含义为：

| 参数 | 物理含义 |
|---|---|
| `u1_v` | 排斥极电位 `V_R` |
| `u2_v` | 中间栅电位 `V_G` |
| `d1_mm` | 第一场区间距 `g_1` |
| `d2_mm` | 第二场区等效间距 `g_2` |

程序还提供：

```python
accelerator_state(...)
compact_exit_focus_bound(...)
normalized_time_to_plane_mm_sqrt_v(...)
time_to_plane_s(...)
```

### 9.2 推荐机器合同

```json
{
  "design": {
    "local_geometry_mm": {
      "gap1": 3.0,
      "gap2": 100.0,
      "release_position": 1.5,
      "ring_pitch": 10.0,
      "ring_count": 9
    },
    "electrodes_V": {
      "repeller": 4000.0,
      "grid1": 3900.0,
      "exit": 0.0
    },
    "target_global_focus_z_mm": 500.0,
    "require_downstream_focus": true,
    "focus_zero_tolerance_mm": 1e-9
  },
  "expected_tolerance": {
    "absolute": 1e-10,
    "relative": 1e-12
  }
}
```

示例数值仅说明字段，不是项目 baseline。

### 9.3 输出必须区分的平面

程序输出至少包括：

```text
accelerator_exit_local_z_mm
first_order_focus_drift_after_exit_mm
first_order_focus_local_z_mm
accelerator_exit_global_z_mm
first_order_focus_global_z_mm
```

不得只输出含糊的 `focus_z` 而不说明局部/全局坐标和参考面。

## 10. 设计与验证边界

### 10.1 解析模型可以做什么

- 检查电压、间距和焦面位置的量纲与符号；
- 生成早期几何候选；
- 证明理想焦面与 `m/z` 无关；
- 为 COMSOL/SIMION 提供独立回归值；
- 识别数学焦面落在出口上游的不可用候选。

### 10.2 解析模型不能证明什么

- 实际透过率；
- 栅网散射和遮挡；
- 三维边缘场下的真实焦面；
- 初始速度、时间、横向发射度和空间电荷的影响；
- 最终质量分辨率；
- CAD 可制造性和高压安全性。

## 11. 最低参考测试

| 测试 ID | 内容 | 期望 |
|---|---|---|
| `ACC-TF-001` | 文档公式与 `focus_drift_mm` | 数值一致 |
| `ACC-TF-002` | `E_A1=E_A2` 退化 | `D_A=2(g_1+g_2-x_c)` |
| `ACC-TF-003` | 整体同比例缩放所有相对电压 | 焦面几何不变 |
| `ACC-TF-004` | 改变 `m/z` | `D_A` 不变，时间按 `√(m/z)` 缩放 |
| `ACC-TF-005` | `D_A=0` 一般闭式解 | 与直接公式一致 |
| `ACC-TF-006` | `g_min>Δx` | 仍能使用一般闭式解 |
| `ACC-TF-007` | `D_A<0` | Candidate/Formal 路径拒绝 |
| `ACC-TF-008` | 释放区越出第一间隙 | 拒绝 |
| `ACC-TF-009` | 三维场/时间步/粒子数收敛 | 按项目契约通过 |

运行参考自检：

```powershell
python .\analysis\accelerator_time_focus.py --self-test
```

## 12. 非理想模型升级

按以下顺序升级：

1. 一维均匀场解析模型；
2. 一维真实轴向电势积分；
3. 二维轴对称或三维静电场；
4. 有限栅厚、栅透过率和边缘场；
5. 冻结的六维粒子表与释放时间；
6. 空间电荷、脉冲波形和电压误差；
7. COMSOL/SIMION 独立闭合及正式 CAD。

每升级一级，都必须保留低一级模型作为回归参考，不能用更复杂模型替代基本守恒和极限检查。

## 13. 参考文献

1. W. C. Wiley, I. H. McLaren, “Time-of-Flight Mass Spectrometer with Improved Resolution,” *Review of Scientific Instruments*, 26(12), 1150–1157 (1955), DOI: `10.1063/1.1715212`。
2. R. Stein, “Space and velocity focusing in time-of-flight mass spectrometers,” *International Journal of Mass Spectrometry and Ion Physics*, 14(2), 205–218 (1974), DOI: `10.1016/0020-7381(74)80008-2`。
3. D. P. Seccombe, T. J. Reddish, “Theoretical study of space focusing in linear time-of-flight mass spectrometers,” *Review of Scientific Instruments*, 72, 1330–1338 (2001), DOI: `10.1063/1.1336824`。

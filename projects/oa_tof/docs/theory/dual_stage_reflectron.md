# 单次反射 oa-TOF 二级反射镜等时聚焦参考

## 1. 文档职责

本文定义单次反射 oa-TOF 中二级、分段均匀场反射镜的一维参考模型，包括：

- 反射镜入口、出口和有效无场路径的严格定义；
- 一阶与二阶能量聚焦条件；
- 第一、第二级场强的求解；
- 低能离子进入第二级和高能离子不穿底的包络条件；
- 三阶能量像差的正确定位；
- 与整机耦合模型的职责边界。

本文件用于替代活跃理论入口中的 `单次反射TOF二级反射镜等时聚焦推导.docx`。旧 DOCX 中的勘误过程和已关闭偏差如需追溯，应迁入带日期的 `docs/history/` 快照，不能留在当前理论正文中。

配套求解器无关参考实现为：

```text
analysis/reflectron_dual_stage_solver.py
```

本文的闭式解是**局部、未耦合参考解**：它把双区正交加速器一阶时间聚焦面视为有效时间源，并令反射镜段自身的一、二阶能量导数为零。oa-TOF 整机二阶聚焦必须使用：

```text
docs/theory/oatof_oaaccelerator_coupling.md
analysis/oatof_oaaccelerator_coupling.py
```

## 2. 模型与符号

设离子从双区正交加速器的一阶时间聚焦面出发，经过以下区域：

1. 从加速器一阶焦面到反射镜入口的无场路径 `L_up`；
2. 反射镜第一级，轴向长度 `ℓ_1`，均匀场强 `F_1`；
3. 反射镜第二级，均匀场强 `F_2`，离子在其中减速至零并折返；
4. 离开反射镜后到有效探测面的无场路径 `L_down`。

定义：

$$
L=L_{\mathrm{up}}+L_{\mathrm{down}}.
$$

这里的 `L_up` **不是**末级加速电极出口到反射镜入口的距离，而是：

> 双区正交加速器一阶时间聚焦面到反射镜入口参考面的无场路径长度。

第一反射级吸收的能量每电荷为：

$$
U_{R1}=F_1\ell_1.
$$

离子进入反射镜前的能量每电荷为：

$$
W=\frac{K}{q},
$$

标称值为 `W_0`。

为了避免与加速器的 `V_R`、`V_G`、`g_1`、`g_2` 混淆，反射镜统一使用：

| 符号 | 含义 |
|---|---|
| `W_0` | 标称入射能量每电荷 |
| `U_R1` | 反射镜第一级电压降 |
| `F_1`、`F_2` | 两级轴向场强 |
| `ℓ_1`、`ℓ_2` | 两级几何长度 |
| `L_up`、`L_down` | 焦面前后两段无场路径 |

## 3. 理想模型假设

本解析模型要求：

1. 轴向一维运动；
2. 两级反射场均匀、静态且同轴；
3. `L_up` 和 `L_down` 都是真正无场区；
4. 反射前后场外动能相同；
5. 离子全部穿过第一级，并在第二级内部折返；
6. 离子不触碰第二级终端电极；
7. 无横向路径差、边缘场、碰撞和空间电荷；
8. 电压、能量每电荷和场强的参考极性一致。

如果任一离子在第一级中途折返，本文的二级时间公式不再适用于该离子。

## 4. 归一化飞行时间

令：

$$
q=ze>0,
\qquad
v(W)=\sqrt{\frac{2qW}{m}},
$$

$$
v_1(W)=\sqrt{\frac{2q(W-U_{R1})}{m}}.
$$

无场时间为：

$$
t_{\mathrm{drift}}(W)=\frac{L}{v(W)}.
$$

第一级往返时间为：

$$
t_{R1}(W)=\frac{2m[v(W)-v_1(W)]}{qF_1}.
$$

第二级往返时间为：

$$
t_{R2}(W)=\frac{2m v_1(W)}{qF_2}.
$$

总时间：

$$
T_R(W)=t_{\mathrm{drift}}+t_{R1}+t_{R2}.
$$

将公共质荷比因子提出：

$$
T_R(W)=\sqrt{\frac{m}{2q}}\,\tau_R(W),
$$

其中：

$$
\tau_R(W)=
\frac{L}{\sqrt W}
+
\frac{4}{F_1}
\left(\sqrt W-\sqrt{W-U_{R1}}\right)
+
\frac{4}{F_2}\sqrt{W-U_{R1}}.
$$

当长度单位为 mm、场强单位为 V/mm 时，`τ_R` 的单位为 mm/√V，实际时间还需乘以 `10^-3`：

$$
T_R[\mathrm s]
=
10^{-3}
\sqrt{\frac{m}{2q}}
\tau_R.
$$

## 5. 为什么只依赖 `L_up + L_down`

在理想模型中：

$$
t_{\mathrm{up}}+t_{\mathrm{down}}
=
\frac{L_{\mathrm{up}}}{v(W)}
+
\frac{L_{\mathrm{down}}}{v(W)}
=
\frac{L}{v(W)}.
$$

因此局部反射镜解只依赖：

$$
L=L_{\mathrm{up}}+L_{\mathrm{down}}.
$$

该不变量只在以下条件同时成立时有效：

- 两段均无场；
- 反射镜外速度相同；
- 不存在后加速、透镜场或探测器场；
- 不计离轴路径差；
- `L_up` 从加速器一阶时间焦面开始。

在三维整机中，`L_up/L_down` 的具体分配仍影响机械布局、孔径、离轴路径、边缘场和探测器接受度。

## 6. 局部一阶与二阶能量聚焦条件

局部参考解要求：

$$
\left.\frac{\mathrm d\tau_R}{\mathrm dW}\right|_{W_0}=0,
$$

$$
\left.\frac{\mathrm d^2\tau_R}{\mathrm dW^2}\right|_{W_0}=0.
$$

记：

$$
s_0=\sqrt{W_0},
\qquad
s_1=\sqrt{W_0-U_{R1}}.
$$

一阶条件为：

$$
-
\frac{L}{2s_0^3}
+
\frac{2}{F_1}
\left(
\frac{1}{s_0}-\frac{1}{s_1}
\right)
+
\frac{2}{F_2s_1}
=0.
$$

二阶条件为：

$$
\frac{3L}{4s_0^5}
+
\frac{1}{F_1}
\left(
-
\frac{1}{s_0^3}
+
\frac{1}{s_1^3}
\right)
-
\frac{1}{F_2s_1^3}
=0.
$$

再加入几何约束：

$$
U_{R1}=F_1\ell_1.
$$

## 7. 未耦合闭式参考解

给定：

- `W_0`；
- `L=L_up+L_down`；
- 第一级长度 `ℓ_1`；

可以直接得到：

$$
U_{R1}
=
\frac{2W_0(L+2\ell_1)}{3L},
$$

$$
F_1
=
\frac{U_{R1}}{\ell_1}
=
\frac{2W_0(L+2\ell_1)}{3L\ell_1}.
$$

存在性条件：

$$
0<\ell_1<\frac{L}{4}.
$$

然后由一阶条件计算第二级场：

$$
\frac{1}{F_2}
=
\frac{s_1}{2}
\left[
\frac{L}{2s_0^3}
-
\frac{2}{F_1}
\left(
\frac{1}{s_0}-\frac{1}{s_1}
\right)
\right].
$$

该形式比展开成大型根式更适合程序实现，因为：

- 变量含义清晰；
- 易于检查正场强；
- 易扩展到加速器耦合项；
- 避免文档和代码维护两份复杂代数式。

参考程序会重新计算一、二阶残差，不只返回字段值。

## 8. 第二级长度是包络约束

只要离子在第二级内部折返，`ℓ_2` 不进入理想飞行时间表达式；但它是不可省略的几何安全约束。

### 8.1 低能离子必须进入第二级

对完整能量包络：

$$
W\in[W_{\min},W_{\max}],
$$

必须满足：

$$
W_{\min}>U_{R1}.
$$

否则低能尾部会在第一级内折返，当前二级模型失效。

“`0<ℓ_1<L/4`”只保证标称解存在，不保证完整能量包络有效。

### 8.2 高能离子不得穿底

理想均匀第二场中，最高能量离子的穿透深度为：

$$
d_{2,\mathrm{high}}
=
\frac{W_{\max}-U_{R1}}{F_2}.
$$

所以至少要求：

$$
\ell_2
\ge
 d_{2,\mathrm{high}}
+
\delta_{\mathrm{fringe}}
+
\delta_{\mathrm{manufacturing}}.
$$

如果使用比例和绝对裕量：

$$
\ell_{2,\mathrm{req}}
=
 d_{2,\mathrm{high}}(1+\eta)+\delta_{\mathrm{abs}}.
$$

标称穿透深度：

$$
d_{2,0}=\frac{W_0-U_{R1}}{F_2}
$$

只能作为诊断值，不能代替高能包络。

### 8.3 真实场的积分判据

对真实三维或轴向非均匀场，应检查：

$$
\int_0^{\ell_2}F_z(z)\,\mathrm dz
\ge
W_{\max}-U_{R1}.
$$

程序中的均匀场深度只是 L0/L1 参考，不取代场图积分和轨迹折返点验证。

## 9. 质量与电荷依赖

场解 `U_R1`、`F_1`、`F_2` 只依赖：

- `W_0`；
- `L`；
- `ℓ_1`；
- 在耦合模型中还依赖加速器的归一化时间导数。

它们不依赖具体 `m/z`。总飞行时间满足：

$$
T\propto\sqrt{\frac{m}{q}}.
$$

如果使用质荷比 `μ=m/z`，以 Th 表示，则无需再单独输入电荷态来计算飞行时间缩放。

固定相对能散 `ΔW/W_0` 时，理想相对时间像差与 `m/z` 无关。若输入固定绝对动能宽度 `ΔK[eV]`，必须先转换：

$$
\Delta W[\mathrm V]
=
\frac{\Delta K[\mathrm{eV}]}{z}.
$$

因此固定绝对 eV 宽度时，结果会依赖电荷态 `z`。

## 10. 三阶像差与 FWHM

当一、二阶导数为零时，可以定义归一化三阶导数：

$$
\tau_R'''(W_0)
=
-
\frac{15L}{8W_0^{7/2}}
+
\frac{3}{2F_1}
\left[
W_0^{-5/2}
-
(W_0-U_{R1})^{-5/2}
\right]
+
\frac{3}{2F_2}
(W_0-U_{R1})^{-5/2}.
$$

对单侧能量偏移 `ΔW`，可形成三阶端点估计：

$$
|\Delta T_{\mathrm{endpoint}}|
\approx
10^{-3}
\sqrt{\frac{m}{2q}}
\frac{|\tau_R'''(W_0)|}{6}
|\Delta W|^3.
$$

这个量可以用于候选预筛选，但它不是时间峰 FWHM。

禁止直接写：

$$
R=\frac{T_0}{2|\Delta T_{\mathrm{endpoint}}|}
$$

并把它称为正式质量分辨率。原因是三次映射后的峰一般非高斯，端点偏移、半范围、标准差和 FWHM 没有固定换算关系。

正式分辨率必须执行：

```text
冻结的粒子/能量/时间分布
→ 逐粒子计算到达时间
→ 构造时间峰
→ 调用仓库统一 FWHM 算法
→ R = T_peak / (2 * FWHM_t)
```

参考程序只输出：

```text
cubic_endpoint_time_offset_s
endpoint_resolution_proxy_not_FWHM
formal_FWHM_eligible = false
```

## 11. 与加速器耦合的必要性

局部闭式解令：

$$
\tau_R'(W_0)=0,
\qquad
\tau_R''(W_0)=0.
$$

但双区正交加速器到其一阶焦面的时间 `τ_A(W)` 通常满足：

$$
\tau_A'(W_0)=0,
\qquad
\tau_A''(W_0)\ne0.
$$

所以整机时间：

$$
\tau_{\mathrm{total}}(W)
=
\tau_A(W)+\tau_R(W)
$$

会有：

$$
\tau_{\mathrm{total}}''(W_0)
=
\tau_A''(W_0),
$$

并不自动为零。

因此：

- 本文闭式解用于独立回归、初值和局部对照；
- 需要整机二阶聚焦时，必须由耦合求解器重新求 `U_R1`、`F_1` 和 `F_2`；
- 不得把局部闭式解直接标记为 oa-TOF Formal 设计。

## 12. 参考程序接口

### 12.1 核心 API

```python
solve_reflectron_fields(
    nominal_energy_per_charge_v,
    stage1_length_mm,
    *,
    upstream_from_accelerator_focus_mm,
    downstream_to_detector_mm,
    energy_min_v=None,
    energy_max_v=None,
    stage2_margin_fraction=0.0,
    stage2_margin_mm=0.0,
)
```

程序还提供：

```python
normalized_flight_time_mm_sqrt_v(...)
flight_time_s(...)
normalized_derivatives(...)
normalized_third_derivative(...)
energy_aberration_diagnostics(...)
arrival_time_samples(...)
```

### 12.2 推荐机器合同

```json
{
  "design": {
    "nominal_energy_per_charge_V": 4000.0,
    "field_free_lengths_mm": {
      "upstream_from_accelerator_focus": 600.0,
      "downstream_to_detector": 400.0
    },
    "energy_envelope_V": {
      "half_range": 20.0
    },
    "reflectron": {
      "stage1_length_mm": 50.0,
      "stage2_length_mm": 100.0,
      "stage2_margin": {
        "fraction": 0.2,
        "absolute_mm": 0.0
      }
    }
  },
  "particle": {
    "mass_to_charge_Th": 100.0
  }
}
```

示例数值只说明字段，不是项目 baseline。

## 13. 最低参考测试

| 测试 ID | 内容 | 期望 |
|---|---|---|
| `REF-TF-001` | 闭式解一阶残差 | 接近零并满足合同容差 |
| `REF-TF-002` | 闭式解二阶残差 | 接近零并满足合同容差 |
| `REF-TF-003` | 改变 `L_up/L_down`、保持总和 | 局部场解不变 |
| `REF-TF-004` | `ℓ_1 → L/4` | `U_R1 → W_0`，退化到单级极限 |
| `REF-TF-005` | `W_min ≤ U_R1` | 拒绝二级模型 |
| `REF-TF-006` | 使用 `W_max` 计算第二级深度 | 高能深度大于标称深度 |
| `REF-TF-007` | 改变 `m/z` | 场解不变，时间按 `√(m/z)` 缩放 |
| `REF-TF-008` | 三阶导数解析值与步长扫描 | 在稳定区间一致 |
| `REF-TF-009` | 粒子级时间输出 | 可交给统一 FWHM 后处理 |
| `REF-TF-010` | 真实轴向场积分和折返点 | 不穿底且网格收敛 |

运行自检：

```powershell
python .\analysis\reflectron_dual_stage_solver.py --self-test
```

## 14. 当前模型的禁止用法

不得用本文直接证明：

- 三维反射镜的正式分辨率；
- 环栈离散场与理想均匀场完全等价；
- 固定 20%–50% 裕量对所有能散和场图都足够；
- 单个三阶端点偏移就是 FWHM；
- 局部反射镜二阶聚焦等于整机二阶聚焦；
- 约 17% 的解析—COMSOL 偏差必然来自网格或三维场。

任何解析—求解器偏差都必须通过受控 run、坐标/场强定义检查、场积分、网格收敛和 manifest 证据归因。

## 15. 参考文献

1. B. A. Mamyrin, V. I. Karataev, D. V. Shmikk, V. A. Zagulin, “The mass-reflectron, a new nonmagnetic time-of-flight mass spectrometer with high resolution,” *Soviet Physics JETP*, 37(1), 45–48 (1973)。
2. W. C. Wiley, I. H. McLaren, “Time-of-Flight Mass Spectrometer with Improved Resolution,” *Review of Scientific Instruments*, 26(12), 1150–1157 (1955), DOI: `10.1063/1.1715212`。
3. R. Stein, “Space and velocity focusing in time-of-flight mass spectrometers,” *International Journal of Mass Spectrometry and Ion Physics*, 14(2), 205–218 (1974), DOI: `10.1016/0020-7381(74)80008-2`。
4. R. P. Schmid, C. Weickhardt, “Designing reflectron time-of-flight mass spectrometers with and without grids: a direct comparison,” *International Journal of Mass Spectrometry*, 206, 181–190 (2001), DOI: `10.1016/S1387-3806(00)00311-0`。

# oa-TOF 双区正交加速器—二级反射镜纵向耦合

## 1. 文档职责

本文定义 oa-TOF 中双区正交加速器与二级反射镜的求解器无关、一维纵向耦合参考模型。核心目标是避免以下错误：

- 把加速器末级出口误当成固定时间焦面；
- 把 `L_up` 从错误的参考面开始计算；
- 分别令加速器和反射镜“局部最优”，却不检查整机总到达时间；
- 忽略加速器在一阶焦面处仍存在的二阶时间曲率；
- 用单个能量端点偏移代替真实到达时间峰 FWHM。

配套参考实现为：

```text
analysis/oatof_oaaccelerator_coupling.py
```

文件名和模型 ID 中的 `oaaccelerator` 指 oa-TOF 的 orthogonal-acceleration accelerator，不表示新的独立项目。

## 2. 权威边界

本文保存：

- 参考面定义；
- 理想耦合方程；
- 模型有效范围；
- 求解流程和参考测试。

本文不保存：

- 当前项目电压、尺寸和空间变换；
- Candidate/Formal 状态；
- 当前 COMSOL、SIMION 或 CAD 资产路径；
- 某次运行的 FWHM、分辨率或偏差结论。

这些内容仍分别属于项目 `config/`、`docs/PROJECT.md` 和 `artifacts/`。

## 3. 参考面与长度定义

### 3.1 加速器出口面

双区正交加速器末级场出口面：

```math
z_{A,\mathrm{out}}.
```

### 3.2 加速器一阶时间聚焦面

由加速器电压和尺寸计算：

```math
z_{A,f}=z_{A,\mathrm{out}}+D_A.
```

其中 `D_A` 可以随候选设计变化，不得假定恒为零。

### 3.3 反射镜入口面

反射镜第一级理想场的入口参考面：

```math
z_{R,\mathrm{in}}.
```

真实环栈或边缘场模型中，必须在机器合同中定义等效入口面的构造方式。

### 3.4 `L_up` 的正式定义

```math
L_{\mathrm{up}}
=
\text{从 }z_{A,f}\text{ 到 }z_{R,\mathrm{in}}\text{ 的场自由路径长度}.
```

即：

> `L_up` 从双区正交加速器的一阶时间聚焦面开始，而不是从加速器末级出口面开始。

若轴向坐标方向一致且两面之间为直线正向传播，可写成：

```math
L_{\mathrm{up}}=z_{R,\mathrm{in}}-z_{A,f}.
```

若仪器路径折转、坐标轴相反或存在离轴中心轨迹，应在合同中直接保存正的路径长度，不能对坐标差静默取绝对值。

### 3.5 `L_down` 的正式定义

```math
L_{\mathrm{down}}
=
\text{反射镜出口参考面到有效探测面的场自由路径长度}.
```

定义总场自由路径：

```math
L=L_{\mathrm{up}}+L_{\mathrm{down}}.
```

## 4. 耦合模型的适用范围

本模型假设：

1. 加速器是一维、双区、分段均匀静电场；
2. 离子在第一加速间隙内由静止释放；
3. 参数 `W` 的变化来自释放位置变化；
4. `L_up` 和 `L_down` 均为无场区；
5. 反射镜为一维、二级、分段均匀场；
6. 所有离子进入反射镜第二级并在其中折返；
7. 不含横向运动、栅透过、边缘场、碰撞、空间电荷和探测器响应。

本模型对“由初始位置引起的能量—时间相关性”进行解析耦合，但不完整表示独立初始能量散布、释放时间散布和横向相空间。后者必须通过冻结粒子表和时域轨迹处理。

## 5. 加速器到焦面的归一化时间

加速器相对末级出口的电位为：

- 排斥极 `V_R`；
- 中间栅 `V_G`；
- 出口 `0`。

场强：

```math
E_{A1}=\frac{V_R-V_G}{g_1},
\qquad
E_{A2}=\frac{V_G}{g_2}.
```

对由释放位置决定的出口能量每电荷 `W`：

```math
W>V_G.
```

从释放到加速器一阶焦面的时间写成归一化形式。若长度用 mm、场强用 V/mm，则：

```math
T_A(W)=10^{-3}\sqrt{\frac{m}{2q}}\,\tau_A(W),
```

其中：

```math
\tau_A(W)=
\frac{2\sqrt{W-V_G}}{E_{A1}}
+
\frac{2\left(\sqrt W-\sqrt{W-V_G}\right)}{E_{A2}}
+
\frac{D_A}{\sqrt W}.
```

在标称能量 `W_0` 处，`D_A` 按加速器一阶焦点公式确定，因此：

```math
\tau_A'(W_0)=0.
```

但通常：

```math
\tau_A''(W_0)\ne0.
```

这正是必须进行整机二阶耦合求解的原因。

## 6. 加速器时间导数

令：

```math
R_A=W-V_G.
```

一阶导数：

```math
\tau_A'(W)=
\frac{1}{E_{A1}\sqrt{R_A}}
+
\frac{1}{E_{A2}}
\left(
\frac{1}{\sqrt W}-\frac{1}{\sqrt{R_A}}
\right)
-
\frac{D_A}{2W^{3/2}}.
```

二阶导数：

```math
\tau_A''(W)=
-
\frac{1}{2E_{A1}R_A^{3/2}}
+
\frac{1}{E_{A2}}
\left(
-
\frac{1}{2W^{3/2}}
+
\frac{1}{2R_A^{3/2}}
\right)
+
\frac{3D_A}{4W^{5/2}}.
```

三阶导数：

```math
\tau_A'''(W)=
\frac{3}{4E_{A1}R_A^{5/2}}
+
\frac{1}{E_{A2}}
\left(
\frac{3}{4W^{5/2}}
-
\frac{3}{4R_A^{5/2}}
\right)
-
\frac{15D_A}{8W^{7/2}}.
```

参考程序使用解析导数，避免以极小步长有限差分制造“浮点噪声即精确聚焦”的错误结论。

## 7. 反射镜段归一化时间

定义：

- 第一级长度 `ℓ_1`；
- 第一级电压降 `U_R1`；
- `F_1=U_R1/ℓ_1`；
- 第二级场强 `F_2`。

反射镜及两段无场路径的归一化时间为：

```math
\tau_R(W)=
\frac{L}{\sqrt W}
+
\frac{4}{F_1}
\left(
\sqrt W-\sqrt{W-U_{R1}}
\right)
+
\frac{4}{F_2}
\sqrt{W-U_{R1}}.
```

要求：

```math
W>U_{R1}.
```

## 8. 整机总时间

从离子释放到有效探测面的归一化总时间为：

```math
\tau_{\mathrm{total}}(W)
=
\tau_A(W)+\tau_R(W).
```

实际飞行时间：

```math
T_{\mathrm{total}}(W)
=
10^{-3}
\sqrt{\frac{m}{2q}}
\tau_{\mathrm{total}}(W),
```

其中长度用 mm、场强用 V/mm。

这一定义没有丢弃从离子释放到加速器焦面的飞行时间。`L_up` 从焦面开始，只是对后续无场距离重新选取了正确参考面。

## 9. 全局一阶与二阶聚焦条件

要求：

```math
\tau_{\mathrm{total}}'(W_0)=0,
```

```math
\tau_{\mathrm{total}}''(W_0)=0.
```

记：

```math
s_0=\sqrt{W_0},
\qquad
s_1=\sqrt{W_0-U_{R1}},
```

```math
A_1=\tau_A'(W_0),
\qquad
A_2=\tau_A''(W_0).
```

对正确的一阶焦面，理论上 `A_1=0`，但程序仍保留该项以便检查序列化和参考面误差。

给定试探 `U_R1`，有：

```math
F_1=\frac{U_{R1}}{\ell_1}.
```

由全局一阶条件可解出：

```math
\frac{1}{F_2}
=
\frac{s_1}{2}
\left[
\frac{L}{2s_0^3}
-
A_1
-
\frac{2}{F_1}
\left(
\frac{1}{s_0}-\frac{1}{s_1}
\right)
\right].
```

然后把它代入全局二阶残差：

```math
G(U_{R1})=
A_2
+
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
\frac{1}{F_2s_1^3}.
```

求：

```math
G(U_{R1})=0.
```

因此耦合问题可降为一个受物理边界约束的一维根求解。

### 9.1 物理搜索域

必须满足：

```math
0<U_{R1}<W_{\min},
```

```math
F_1>0,
\qquad
F_2>0.
```

参考程序先扫描有效区间寻找符号变化，再使用二分法；不依赖 SciPy，也不以未经检查的 Newton 初值直接发布结果。收敛判据同时检查电压区间宽度与按各二阶项尺度归一化后的最终残差，不使用量纲含义不明的固定绝对残差。

### 9.2 与局部反射镜解的关系

若人为令：

```math
A_1=0,
\qquad
A_2=0,
```

上述方程退化为 `dual_stage_reflectron.md` 中的未耦合闭式解。

实际加速器通常仅保证 `A_1=0`，而 `A_2≠0`。所以耦合求得的 `U_R1`、`F_1`、`F_2` 可以明显不同于局部闭式值，这是正确行为，不是程序误差。

## 10. 能量包络和反射镜深度

### 10.1 空间引起的能量包络

若释放区完整宽度为 `Δx`，则：

```math
\Delta W_x=\frac{E_{A1}\Delta x}{2}.
```

仅考虑空间相关时：

```math
W_{\min}=W_0-\Delta W_x,
```

```math
W_{\max}=W_0+\Delta W_x.
```

### 10.2 独立初始能量宽度

若另有独立能量每电荷半范围 `ΔW_intrinsic`，几何安全包络可保守写成：

```math
W_{\min}=W_0-\Delta W_x-\Delta W_{\mathrm{intrinsic}},
```

```math
W_{\max}=W_0+\Delta W_x+\Delta W_{\mathrm{intrinsic}}.
```

但当前解析时间函数 `τ_A(W)` 把 `W` 视为由释放位置产生的相关变量，不能完整表示独立初始速度。只要 `ΔW_intrinsic>0`，正式峰形必须改用粒子级时域模型。

### 10.3 进入第二级和不穿底

必须满足：

```math
W_{\min}>U_{R1}.
```

第二级所需深度：

```math
\ell_{2,\mathrm{req}}
=
\frac{W_{\max}-U_{R1}}{F_2}(1+\eta)
+
\delta_{\mathrm{abs}}.
```

真实场还需检查轴向电势积分和三维折返点。

## 11. 源位置采样与正式峰形

参考程序可以在第一间隙内对释放位置进行确定性采样：

```math
x_i\in
\left[
 x_c-\frac{\Delta x}{2},
 x_c+\frac{\Delta x}{2}
\right].
```

对应能量：

```math
W_i=V_R-E_{A1}x_i.
```

逐粒子计算：

- `accelerator_focus_time_s`；
- `detector_arrival_time_s`；
- 位置、能量和时间的关联。

该采样可作为解析回归数据，但仍不能自动成为 Formal FWHM，因为它通常没有包含：

- 独立初始能量；
- 释放时间宽度；
- 横向位置和角度；
- 三维边缘场；
- 栅网散射与损失；
- 检测器响应；
- 统计采样不确定度。

正式流程为：

```text
共享粒子表
→ COMSOL/SIMION 独立轨迹
→ 统一有效探测面与命中规则
→ 统一时间峰和 FWHM 后处理
→ R = T_peak / (2 * FWHM_t)
```

## 12. 推荐机器合同

```json
{
  "design": {
    "oa_accelerator": {
      "local_geometry_mm": {
        "gap1": 2.0,
        "gap2": 110.0,
        "release_position": 1.0
      },
      "electrodes_V": {
        "repeller": 1010.0,
        "grid1": 990.0,
        "exit": 0.0
      },
      "assembly_translation_z_mm": 0.0
    },
    "layout_mm": {
      "upstream_from_accelerator_focus": 300.0,
      "downstream_to_detector": 200.0
    },
    "source": {
      "release_full_width_mm": 1.0,
      "intrinsic_energy_per_charge_half_range_V": 0.0,
      "sample_count": 1001
    },
    "reflectron": {
      "stage1_length": 20.0,
      "stage2_length": 100.0,
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

### 12.1 不允许重复输入的派生量

以下量应由程序派生，不应在多个合同中手工重复：

```text
E_A1
E_A2
W_0
D_A
z_A,f
spatial_energy_half_range
U_R1
F_1
F_2
required_stage2_depth
```

如项目为了门禁保存 `expected_derived`，它只能用于回归比较，不能成为反向参数源。

## 13. 参考程序接口

核心 API：

```python
solve_coupled_reflectron_fields(
    accelerator,
    stage1_length_mm,
    upstream_from_accelerator_focus_mm,
    downstream_to_detector_mm,
    *,
    energy_min_v=None,
    energy_max_v=None,
    stage2_margin_fraction=0.0,
    stage2_margin_mm=0.0,
)
```

总时间：

```python
coupled_normalized_flight_time_mm_sqrt_v(...)
coupled_flight_time_s(...)
```

粒子级解析采样：

```python
source_position_samples(...)
```

CLI：

```powershell
python -m projects.oa_tof.analysis.oatof_oaaccelerator_coupling `
  .\config\oatof_longitudinal_contract.json `
  --write-derived <derived.json> `
  --write-samples <samples.csv>
```

## 14. 最低参考测试

| 测试 ID | 内容 | 期望 |
|---|---|---|
| `OATOF-LONG-001` | 加速器焦面一阶导数 | `τ_A'(W_0)` 满足容差 |
| `OATOF-LONG-002` | `L_up` 参考面 | 从 `z_A,f` 开始，不从 `z_A,out` 开始 |
| `OATOF-LONG-003` | 耦合总一阶残差 | 接近零 |
| `OATOF-LONG-004` | 耦合总二阶残差 | 接近零 |
| `OATOF-LONG-005` | 未耦合与耦合场解比较 | 当 `τ_A''≠0` 时允许明显不同 |
| `OATOF-LONG-006` | `W_min>U_R1` | 全包络进入第二级 |
| `OATOF-LONG-007` | 高能穿透深度 | 不穿底且有合同裕量 |
| `OATOF-LONG-008` | 源位置采样 | 焦面与探测面时间可重算 |
| `OATOF-LONG-009` | `m/z` 缩放 | 时间按 `√(m/z)` 缩放，场解不变 |
| `OATOF-LONG-010` | COMSOL/SIMION 同一粒子表 | 坐标、能量、时间和命中定义一致 |
| `OATOF-LONG-011` | 网格、时间步、样本数 | 分别收敛 |
| `OATOF-LONG-012` | 统一 FWHM | 使用仓库分析合同，不用端点代理 |

运行轻量自检：

```powershell
python -m projects.oa_tof.analysis.oatof_oaaccelerator_coupling --self-test
```

## 15. 从解析耦合到 Formal 的升级路线

### L0：局部解析

- 独立加速器一阶焦面；
- 独立反射镜局部闭式解。

### L1：一维耦合解析

- 本文总时间；
- 全局一、二阶导数；
- 能量包络和第二级深度。

### L2：一维真实轴向场

- 使用 COMSOL/SIMION 轴线电势；
- 数值积分分段时间；
- 检查等效入口面和折返点。

### L3：三维无空间电荷轨迹

- 冻结六维粒子表；
- 栅透过、边缘场、横向路径和探测面；
- 网格和时间步收敛。

### L4：真实脉冲与集体效应

- 抽取脉冲波形；
- 初始时间分布；
- 空间电荷；
- 电压误差和制造公差。

### Formal

- COMSOL/SIMION 独立闭合；
- 统一 FWHM 与样本量；
- GUI 可检查；
- CAD 同步；
- run config、summary、manifest 和 SHA-256 完整。

## 16. 禁止性结论

仅凭本模型不得宣称：

- 当前 oa-TOF 已达到某个正式分辨率；
- `D_A=0` 是整机最优；
- 局部反射镜闭式解已经满足整机二阶聚焦；
- `L_up` 可以从加速器出口面开始；
- 三阶端点像差等于 FWHM；
- 解析—三维求解器偏差的原因已经确定；
- 任何未冻结的自然语言参数可以直接驱动 Formal CAD。

## 17. 参考文献

1. W. C. Wiley, I. H. McLaren, “Time-of-Flight Mass Spectrometer with Improved Resolution,” *Review of Scientific Instruments*, 26(12), 1150–1157 (1955), DOI: `10.1063/1.1715212`。
2. B. A. Mamyrin, V. I. Karataev, D. V. Shmikk, V. A. Zagulin, “The mass-reflectron, a new nonmagnetic time-of-flight mass spectrometer with high resolution,” *Soviet Physics JETP*, 37(1), 45–48 (1973)。
3. R. Stein, “Space and velocity focusing in time-of-flight mass spectrometers,” *International Journal of Mass Spectrometry and Ion Physics*, 14(2), 205–218 (1974), DOI: `10.1016/0020-7381(74)80008-2`。
4. J. H. J. Dawson, M. Guilhaus, “Orthogonal-acceleration time-of-flight mass spectrometer,” *Rapid Communications in Mass Spectrometry*, 3, 155–159 (1989), DOI: `10.1002/rcm.1290030511`。

---
description: Astral 类质量分析器的 AI 可复现实现流程、机器合同、解析与三维求解分层、优化顺序、验证矩阵、结果指标和发布门禁。
keywords:
  - reproducible simulation
  - Astral replication
  - COMSOL
  - SIMION
  - Python
  - validation
  - physics contract
document_id: astral_replication.implementation_validation
version: 1.0.0
maturity: reference
---

# 实现、复现与验证协议

本文件把理论转换为 AI 可以执行的工程流程。目标不是一次性建立一个“看起来像 Astral”的轨迹图，而是形成：

- 可追溯的几何和电压合同；
- 求解器无关的解析参考；
- 可重复的粒子源；
- 明确的空间、时间和振荡事件定义；
- 跨求解器和实验可升级的验证证据。

## 1. 系统模块边界

推荐把系统拆成以下物理模块：

```text
source_and_extraction
injection_optics
isochronous_mirrors
original_drift_control OR dual_stripe_drift_control
steering_prism
post_acceleration_and_detector
particle_tracking
peak_analysis
calibration
space_charge
```

每个模块应输出明确的合同，而不是在 COMSOL、SIMION、MATLAB 和 Python 中各自保存一套参数。

## 2. 单向数据流

```text
理论模型与工程约束
→ baseline 参数
→ resolved 几何与电压
→ COMSOL / SIMION / CAD
→ 原始场和轨迹
→ 统一粒子结果
→ 峰形、FWHM、透过率和振荡数
→ 验证报告
```

求解器不得反向修改 baseline。若某个几何在 COMSOL 中更容易网格化，也不能据此静默改变理论尺寸。

## 3. 最小物理合同

建议建立 `physics_contract.json`：

```json
{
  "schema_version": "1.0.0",
  "model_id": "astral.dual_stripe.parallel_mirrors.v1",
  "coordinate_system": {
    "x": "transverse_mirror_focusing",
    "y": "longitudinal_drift",
    "z": "fast_reflection",
    "origin": "nominal_injection_midplane"
  },
  "particle_convention": {
    "charge_sign": 1,
    "mass_to_charge_unit": "Th",
    "energy_per_charge_unit": "V"
  },
  "nominal": {
    "energy_per_charge_V": 4000.0,
    "mirror_period_definition": "full_two_mirror_oscillation",
    "target_oscillation_count": 25,
    "drift_length_mm": 335.0
  },
  "mirror_model": {},
  "drift_model": {},
  "prism_model": {},
  "source_model": {},
  "detector_model": {},
  "required_reference_tests": []
}
```

## 4. 几何合同

几何合同必须定义：

- 所有电极的稳定 ID；
- 每个电极所属模块；
- 电极电位参考；
- 位置、旋转和镜像关系；
- 厚度、倒角、孔、槽和最小间隙；
- 中央棱镜走廊；
- 原镜收敛角或平行度；
- Stripe 形状的参数化方式；
- 探测面和终止面；
- 机械支撑和绝缘体是否进入场模型。

双 Stripe 建议以同一函数生成 CAD、COMSOL 和 SIMION 边界：

```text
shape_1(y; coefficients_1)
shape_2(y; coefficients_2)
```

不要在三个软件中手工绘制三套近似曲线。

## 5. 电压合同

电压合同应区分：

- 绝对电位；
- 相对于镜中央无场区的电位；
- 相对于离子源抬升电位的电位；
- 静态电位；
- 脉冲波形；
- 调谐坐标和实际电极电压。

示例：

```json
{
  "mirror": {
    "U0_V": 0.0,
    "U1_V": null,
    "U2_V": null,
    "U3_V": null,
    "U4_V": null
  },
  "dual_stripe": {
    "v1_V": null,
    "v2_V": null,
    "tuning_basis": {
      "drift_return": [null, null],
      "drift_time": [null, null]
    }
  },
  "prism": {
    "bias_V": null
  }
}
```

## 6. 粒子源合同

正式源不能由求解器内部随机生成后丢失。应先生成冻结粒子表：

```text
particle_id
mass_to_charge_Th
charge_state
release_time_s
x0_m, y0_m, z0_m
vx0_m_per_s, vy0_m_per_s, vz0_m_per_s
kinetic_energy_eV
rf_phase_rad
macro_charge_C
species_id
```

要求：

- 固定随机种子；
- 保存分布来源；
- 同一粒子 ID 可在不同求解器中追踪；
- 空间和速度相关性不能被拆成独立高斯，除非源模型明确如此；
- 高电荷模拟保存宏粒子权重。

## 7. L0 解析参考实现

至少建立以下独立函数：

```python
compute_planar_mirror_potential(...)
compute_turning_point(...)
compute_mirror_action(...)
compute_mirror_period(...)
compute_mirror_period_slope(...)
compute_poincare_linear_map(...)
compute_kappa(...)
compute_generalized_tau(...)
compute_prism_bias(...)
compute_dual_stripe_response(...)
```

这些函数不得依赖 COMSOL 或 SIMION API。

## 8. L0 镜优化算法

伪代码：

```text
normalize units and polarity
build Berdnikov field basis
for each candidate geometry:
    solve turning points over energy grid
    compute regularized action and period
    compute three-energy period slopes
    reject missing-turning-point candidates
    compute paraxial map and phase advance
    compute averaged transverse time coefficient
    evaluate engineering constraints
optimize weighted residuals
save candidate, raw residuals and precision settings
```

必须保存：

- 能量网格；
- 积分算法；
- 转折点分支；
- 差分步长；
- 优化器和初值；
- 变量边界；
- 未缩放残差；
- 收敛状态。

## 9. L0 漂移优化算法

### 9.1 原方案

```text
load c0 ... c5 or solve project coefficients
regularize kappa and tau integrals
compute kappa(1), kappa'(1)
compute tau over full accepted eta_D range
calculate theta0, Theta and stripe scale
verify K window
```

### 9.2 双 Stripe

```text
select voltage-pair candidates v1, v2
compute exact response factors A and h
invert target psi/g to p1/p2
convert p1/p2 to signed shape deviations
add positive baseline widths
reject geometry conflicts
optimize exact action over energy and eta grids
recompute generalized kappa and tau_g
rank by time plateau, geometry, field and condition number
```

## 10. 端点积分实现

对于

$$
I(\eta_D)
=
\int_0^{\eta_D}
\frac{N(\eta)}
{\sqrt{\psi(\eta_D)-\psi(\eta)}}
\,\mathrm d\eta,
$$

使用

$$
\eta=\eta_D-u^2.
$$

生产实现应显式处理 $u\rightarrow0$ 极限。不要用浮点精确比较作为唯一策略，也不要截断上限。

建议：

- 在 $u<u_{\mathrm{switch}}$ 使用解析极限或级数；
- 其余区间使用自适应 Gauss–Kronrod；
- 用高精度库复验关键基准；
- 对 $\eta_D$ 导数使用多步长和局部拟合。

## 11. L1/L2 二维场模型

二维模型至少包含：

- 五电极镜真实截面；
- 电极间隙和厚度；
- 中央无场区；
- Stripe 或双 Stripe 截面；
- 真实电压基场。

输出：

```text
phi(z, x)
Ez(z, x)
Ex(z, x)
axis potential phi0(z)
high-order axis derivatives
field interpolation metadata
```

### 11.1 网格收敛

至少用三档网格比较：

- 轴势；
- 转折位置；
- 周期；
- Poincaré 矩阵；
- 峰值场；
- 高阶导数。

高阶导数通常比电势本身更敏感，不能只看 $\varphi$ 的相对误差。

## 12. L3 三维模型

完整三维模型应加入：

- 镜沿 $y$ 的有限长度；
- 原方案的收敛或双 Stripe 的平行镜；
- 端部修正器；
- 中央接地板；
- 棱镜；
- 注入透镜；
- 源槽；
- 探测器和后加速入口；
- 支撑和绝缘体；
- 真空域边界。

## 13. 静电基场策略

静电系统对电压线性，可预计算单位电压基场：

$$
\mathbf E(\mathbf r)
=
\sum_i V_i\mathbf E_i^{(1\ \mathrm V)}(\mathbf r).
$$

应分别保存：

- 每个镜电极基场；
- 每个 Stripe 基场；
- 棱镜基场；
- 端部修正器基场；
- 后加速基场。

轨迹和时间对电压不是线性的，因此不能用线性插值替代粒子重算，除非误差已验证。

## 14. 轨迹积分器要求

- 使用双精度；
- 支持自适应步长或明确的最大步长；
- 在转折点、边缘场和薄间隙处自动减小步长；
- 使用事件定位而非步间符号猜测；
- 保存失败原因；
- 检查能量守恒；
- 在无电场区验证直线运动；
- 对静电轨迹验证时间反演。

## 15. 事件和状态定义

推荐状态：

```text
launched
entered_analyzer
mirror_turn
completed_oscillation
crossed_prism_first
crossed_prism_second
detected
hit_electrode
left_domain
wrong_oscillation_count
timeout
invalid
```

振荡数应由转折事件或同向 Poincaré 截面事件计算，不能仅由总时间除以标称周期并取整。

## 16. 探测器命中定义

必须明确：

- 探测面方程；
- 有效面积；
- 法向方向；
- 第一次交点还是最后一次交点；
- 后加速是否包含在飞行时间；
- 擦边是否算命中；
- 多次穿面如何处理。

探测器面积会改变 overtone 和透过率，因此它是物理参数，不只是绘图平面。

## 17. 结果表合同

每粒子至少输出：

```text
particle_id
status
mass_to_charge_Th
charge_state
start_time_s
arrival_time_s
flight_time_s
oscillation_count
mirror_turn_count
prism_pass_count
final_x_m
final_y_m
final_z_m
final_vx_m_per_s
final_vy_m_per_s
final_vz_m_per_s
loss_element_id
```

建议额外输出：

```text
max_abs_x_m
max_abs_y_m
max_abs_z_m
max_electric_field_V_per_m
energy_error_relative
adiabatic_action_error
```

## 18. 峰形和 FWHM

正式峰算法需要版本化：

1. 选择 `detected` 粒子；
2. 不按期望结果删除尾部；
3. 固定直方图或核估计规则；
4. 计算峰中心；
5. 计算 FWHM；
6. 报告多峰、肩峰或无半高交点；
7. 同时报告透过率和 overtone。

对于非高斯峰，应报告：

- FWHM；
- 10–90% 宽度或分位数；
- 偏度和峰度；
- 主峰面积；
- overtone 面积；
- 尾部比例。

## 19. Overtone 定义

建议按实际振荡数分类：

```text
main peak: K_target
overtone -1: K_target - 1
overtone +1: K_target + 1
...
```

同一时间附近的粒子也必须按事件数分类，不能只靠峰位置猜测。

## 20. 误差预算

至少包含：

### 20.1 几何

- 镜间距；
- 平行度/收敛角；
- 扭转；
- 电极边界；
- Stripe 形状；
- 棱镜位置；
- 探测器位置；
- 热膨胀。

### 20.2 电气

- 镜电压比例误差；
- Stripe 电压误差；
- 棱镜电压误差；
- 电源噪声；
- 脉冲时序抖动；
- RF 相位和关断时间。

### 20.3 源

- 位置；
- 时间；
- 速度；
- 能量；
- 角度；
- 电荷数量；
- 质量组成。

### 20.4 数值

- 网格；
- 场插值；
- 时间步；
- 积分容差；
- 事件定位；
- 粒子数和随机种子。

## 21. 参数灵敏度和 Jacobian

对关键指标 $\mathbf y$ 和参数 $\mathbf p$，计算

$$
\mathbf J
=
\frac{\partial\mathbf y}{\partial\mathbf p}.
$$

指标可包含：

```text
period slopes at three energies
phase advance
averaged transverse time coefficient
K
spatial focus residual
time plateau residual
FWHM
transmission
overtone fraction
peak field
```

使用 SVD 识别：

- 可独立调节方向；
- 退化参数；
- 条件数；
- 校准方向；
- 制造最敏感尺寸。

## 22. 跨求解器验证

COMSOL、SIMION 或其他求解器必须使用：

- 相同几何合同；
- 相同电压；
- 相同粒子表；
- 相同时间原点；
- 相同探测面；
- 相同状态映射；
- 相同 FWHM 算法。

比较：

1. 单位电压场；
2. 轴势；
3. 关键截面场；
4. 转折点；
5. 单粒子到达时间；
6. Poincaré 映射；
7. 振荡数；
8. 粒子级状态；
9. FWHM 和透过率。

## 23. 参考基准

### 23.1 镜

```text
w0 = 4000 V
energy nodes = 3900, 4000, 4100 V
```

### 23.2 原漂移方案

```text
L = 335 mm
W = 641 mm
K = 25
theta0 ≈ 1.78 deg
Theta ≈ 0.045 deg
vs ≈ -13.8 V
```

### 23.3 棱镜

```text
alpha = 4 deg
beta = 1.8 deg
w0 = 4000 V
vd ≈ -152.8 V
```

这些基准用于验证方程和单位，不代表新设计的最终参数。

## 24. 双 Stripe 专项报告

每个候选必须报告：

| 指标 | 必填内容 |
|---|---|
| 电压对 | $v_1,v_2$ 和能量穿越裕量 |
| 响应矩阵 | 行列式和条件数 |
| 形状 | 基线、最小/最大宽度、斜率、曲率 |
| 作用量 | $n=0,1,2,3$ 能量导数误差 |
| 漂移 | $\kappa'(1)$、$K$ 分布、转折位置 |
| 时间 | 全角度、全能量时间平台 |
| 三维场 | 横向踢、边缘场、峰值场 |
| 性能 | FWHM、透过率、overtone、峰形 |
| 鲁棒性 | 平行度、电压、形状和源分布敏感度 |

## 25. 优化器使用规则

- 先用低维物理参数，不要直接优化每个 CAD 点；
- 对约束使用显式变量变换或不等式；
- 保存所有初值和失败候选；
- 使用多初值或全局预扫描；
- 训练代理模型时保留真实求解器验证集；
- 不允许通过减少粒子、粗化网格或删尾部来获得“更好”指标；
- 优化目标应包含透过率和高场，不能只最小化 FWHM。

## 26. 容易犯错的地方

1. **没有固定坐标和周期语义**；
2. **不同求解器使用不同粒子表**；
3. **把场线性叠加误解为时间线性叠加**；
4. **只看中心轨迹**；
5. **未记录转折和振荡事件**；
6. **在转折点使用过大时间步**；
7. **用模型文件存在证明运行成功**；
8. **只比较最终 FWHM，不比较粒子级轨迹**；
9. **把统计噪声当优化改进**；
10. **改变 detector area 后仍比较同一透过率**；
11. **未把基线 Stripe 作用量纳入镜校准**；
12. **把 aperture 截束造成的窄峰当高分辨**；
13. **没有同时报告峰宽和主峰面积**；
14. **用生产二进制反向定义 baseline**；
15. **没有区分解析检查通过和真实三维验证通过**。

## 27. 发布门禁

### L0 发布

需要：

- 公式单元测试；
- 论文公开基准回归；
- 数值积分和导数收敛；
- 明确适用范围。

### L2 发布

需要：

- 真实二维场；
- 网格收敛；
- 映射和高阶导数验证；
- 解析模型误差报告。

### L3 候选

需要：

- 完整三维几何；
- 同源粒子表；
- 跨求解器比较；
- FWHM、透过率和 overtone；
- 电压和几何误差扫描。

### L4/L5 正式

需要：

- 空间电荷和统计不确定度；
- 制造公差；
- 实验校准；
- 冻结分析合同；
- 适用电荷、质量和工作模式范围。

## 28. 推荐目录绑定

```text
projects/<astral_like_project>/
├─ README.md
├─ docs/
│  ├─ PROJECT.md
│  └─ PHYSICS.md
├─ config/
│  ├─ project.json
│  ├─ baseline.json
│  ├─ resolved_geometry.json
│  ├─ physics_contract.json
│  ├─ source.json
│  ├─ modes.json
│  └─ analysis_contract.json
├─ analysis/
│  ├─ mirror_reference.py
│  ├─ drift_reference.py
│  ├─ dual_stripe_reference.py
│  ├─ prism_reference.py
│  └─ peak_metrics.py
├─ comsol/
├─ simion/
├─ cad/
└─ tests/
```

理论正文保留在跨项目知识目录；具体项目只绑定模型版本和当前参数。

## 29. 主要来源

- D. Grinfeld et al., *Nuclear Instruments and Methods in Physics Research A* 1060 (2024) 169017. DOI: `10.1016/j.nima.2023.169017`.
- A. S. Berdnikov et al., *Journal of Analytical Chemistry* 74 (2019) 1437–1446. DOI: `10.1134/S1061934819140041`.
- H. Stewart et al., *Journal of the American Society for Mass Spectrometry* 35 (2024) 74–81. DOI: `10.1021/jasms.3c00311`.
- H. Stewart et al., “Crowd Control of Ions in the Astral Analyzer,” ChemRxiv. DOI: `10.26434/chemrxiv-2023-p6zln`.

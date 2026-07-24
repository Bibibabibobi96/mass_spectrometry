---
description: Astral 类开放路径多反射飞行时间质量分析器的理论复刻入口，覆盖等时离子镜、绝热漂移、Ion Foil、双 Stripe 非倾斜方案、注入棱镜、源与校准、数值实现和验证。
keywords:
  - Astral
  - MR-TOF
  - isochronous ion mirror
  - adiabatic drift
  - Ion Foil
  - dual stripe
  - non-tilt analyzer
  - time-of-flight mass spectrometry
document_id: astral_replication.index
version: 1.0.0
maturity: reference_with_provisional_extension
---

# Astral 类质量分析器理论复刻知识包

本知识包面向需要**理解、实现、优化和验证** Astral 类开放路径多反射飞行时间质量分析器的研究人员与 AI Agent。它把原论文公开的理论结构、可复算方程和工程接口整理为一条可执行的复刻路线，同时单独给出“平行镜 + 双 Stripe”非倾斜方案的理论模型。

> **边界说明**：公开论文足以复现理论方程、优化目标和系统工作方式，但没有公开完整的生产 CAD、电极精确宽度、全部间隙、端部修正器尺寸、未舍入优化系数和最终制造公差。因此，本知识包支持建立功能等价的研究模型，不声称恢复商业仪器的专有工程图。

## 1. 文档组成

| 文件 | 主要职责 |
|---|---|
| [`isochronous_mirror_design.md`](./isochronous_mirror_design.md) | 五电极无栅格等时镜、Berdnikov 解析势、三点能量等时性、Poincaré 稳定性、横向时间像差和镜电压优化 |
| [`adiabatic_drift_and_original_ion_foil.md`](./adiabatic_drift_and_original_ion_foil.md) | 原 Astral 的绝热不变量、漂移赝势、Ion Foil/Stripe、镜面收敛、空间与时间聚焦及公开无量纲解 |
| [`dual_stripe_non_tilt_design.md`](./dual_stripe_non_tilt_design.md) | 平行镜双 Stripe 新方案的精确作用量响应、两类目标函数、形状反演、基线宽度、全能区优化和三维实现要求 |
| [`injection_prism_source_and_calibration.md`](./injection_prism_source_and_calibration.md) | 脉冲提取离子源、第一时间焦点、注入光学、棱镜折射、探测、TE1/TE2 校准和空间电荷 |
| [`implementation_and_validation.md`](./implementation_and_validation.md) | AI/代码复现流程、数据合同、求解器分层、参考测试、误差预算、跨求解器验证和发布条件 |

建议阅读顺序：

```text
index
→ isochronous_mirror_design
→ adiabatic_drift_and_original_ion_foil
→ dual_stripe_non_tilt_design
→ injection_prism_source_and_calibration
→ implementation_and_validation
```

## 2. 坐标、能量和周期约定

本知识包统一采用：

- $z$：离子在两面镜之间快速往返的**反射方向**；
- $y$：沿伸长镜的**慢漂移方向**；
- $x$：垂直于 $y$–$z$ 运动平面的**横向聚焦方向**；
- $q$：带符号电荷；以下多数公式默认正离子，负离子需反转全部电压极性；
- $m$：离子质量；
- $\varepsilon$：能量；
- $w=\varepsilon/q$：能量/电荷，以伏特表示；
- $T_0$：标称能量下，在两镜之间完成一次完整轴向振荡的周期；
- $W$：有效镜间距离，定义为

$$
W=T_0\sqrt{\frac{\varepsilon_0}{2m}}
  =T_0\sqrt{\frac{q w_0}{2m}}.
$$

$W$ 是“标称速度乘以半周期”，是动力学等效长度，不等同于任意一条 CAD 尺寸。

## 3. 整体理论框架

Astral 类分析器不是单一 reflectron，而是以下子系统的耦合：

```text
热化与脉冲提取
    ↓
第一时间焦点与四维/六维源相空间
    ↓
透镜与棱镜设定注入位置、方向和角度
    ↓
五电极等时离子镜控制 z 向周期与 x 向稳定
    ↓
绝热漂移控制器控制 y 向返回和角度相关时间像差
    ↓
离子完成 K 次轴向振荡并返回注入端附近
    ↓
第二次通过棱镜，部分抵消第一次棱镜的时间像差
    ↓
额外反射与后加速探测
    ↓
镜电压、漂移电压和注入角联合校准
```

三个方向的任务必须分开理解：

| 方向 | 主要动力学 | 主要设计对象 |
|---|---|---|
| $z$ | 快速周期运动、能量等时性 | 五电极镜轴势、转折点、周期和能量导数 |
| $x$ | 镜内横向聚焦与稳定 | Poincaré 映射、焦距、相位进动、高阶时间像差 |
| $y$ | 缓慢漂移、反转和最终空间返回 | 作用量绝热不变量、漂移赝势、Ion Foil 或双 Stripe |

## 4. 原 Astral 与双 Stripe 非倾斜方案

### 4.1 原论文方案

原 Astral 通过两种不同机制共同控制漂移：

1. 形状化低压 Stripe/Ion Foil 改变一段轴向路径中的静电势；
2. 两面镜轻微收敛，使无场轴向路径随 $y$ 缩短。

二者对**空间漂移力**相加，但对**周期的能量响应**具有相反符号，因此能够同时获得漂移返回和宽时间平台。

### 4.2 双 Stripe 平行镜方案

新方案取消有意镜面收敛，使两镜在设计上平行，并使用两套独立偏压、独立形状的 Stripe。该方案不能只按“线性 Stripe 产生线性赝势”理解；实现高分辨的关键是同时控制：

- 标称能量下的作用量扰动 $\Delta J(\varepsilon_0,y)$；
- 作用量对能量的一阶导数 $\partial_\varepsilon\Delta J(\varepsilon_0,y)$；
- 在完整能量窗口内的二阶和更高阶残差；
- 两套真实电极的非负宽度、独立电压区、边缘场和横向透镜效应。

本知识包把双 Stripe 定义为新的模型族：

```text
astral.dual_stripe.parallel_mirrors.v1
```

它应以原论文方案为参考目标，但必须独立完成优化和三维验证。

## 5. 已公开的关键基准

原 Astral 主论文公开了下列理论基准，可用于回归测试：

| 量 | 公开值 |
|---|---:|
| 标称能量/电荷 $w_0$ | $4000\ \mathrm{V}$ |
| 镜三点等时能量 | $3900,4000,4100\ \mathrm{V}$ |
| 标称漂移长度 $L$ | $335\ \mathrm{mm}$ |
| 有效镜间距离 $W$ | $641\ \mathrm{mm}$ |
| 理论振荡次数 $K$ | $25$ |
| 标称注入角 $\vartheta_0$ | $1.78^\circ$ |
| 镜面收敛角 $\Theta$ | $0.045^\circ$ |
| Stripe 偏压 $v_s$ | $-13.8\ \mathrm{V}$ |
| 分析器内近似路径 | $32\ \mathrm{m}$ |

这些数字是论文样机和其理论工作点的参考，不应直接成为新几何的固定常数。

## 6. 复刻模型层级

| 层级 | 模型内容 | 可以回答的问题 |
|---|---|---|
| L0 | 一维轴势、作用量、无量纲漂移积分 | 方程是否自洽、标称参数和尺度律 |
| L1 | 理想二维镜、硬边界 Stripe、傍轴映射 | 三点等时性、线性稳定、初步动态孔径 |
| L2 | 真实二维截面、有限间隙和厚度 | 场误差、真实横向聚焦、边缘场修正 |
| L3 | 完整三维镜、端部、Stripe、棱镜和探测面 | 透过率、振荡数、峰形、overtone 和装配误差 |
| L4 | 六维源分布、空间电荷、制造和电压统计 | 鲁棒性、动态范围和运行包络 |
| L5 | 实验标定和冻结校准 | 仪器工作点、质量标定和正式性能 |

AI 在输出任何结论时应附带模型层级。例如，“$T'(4000\ \mathrm V)=0$”属于 L0/L1；“给定真实离子源时分辨率超过某值”至少属于 L3/L4。

## 7. AI 复刻的最小输入

至少需要以下机器可读输入：

```json
{
  "coordinate_system": "astral.xyz.reflection_z.drift_y.transverse_x.v1",
  "charge_polarity": "positive",
  "nominal_energy_per_charge_V": 4000.0,
  "mirror": {
    "model": "planar_five_electrode_gridless",
    "geometry_parameters": {},
    "electrode_voltages_V": {},
    "end_corrector_parameters": {}
  },
  "drift_control": {
    "model": "original_stripe_plus_tilt | dual_stripe_parallel",
    "nominal_drift_length_mm": 335.0,
    "target_oscillation_count": 25,
    "parameters": {}
  },
  "source": {
    "particle_table": "path/to/frozen_particles.parquet",
    "time_origin": "extraction_trigger",
    "energy_definition": "kinetic_energy_per_charge_after_acceleration"
  },
  "detector": {
    "surface_definition": {},
    "hit_rule": "first_valid_intersection"
  }
}
```

几何、场、粒子和分析定义必须是不同合同；不要把电极尺寸、粒子随机分布和 FWHM 算法混在同一个脚本中。

## 8. 主要来源

1. D. Grinfeld et al., “Multi-reflection Astral mass spectrometer with isochronous drift in elongated ion mirrors,” *Nuclear Instruments and Methods in Physics Research A* 1060 (2024) 169017. DOI: `10.1016/j.nima.2023.169017`.
2. A. S. Berdnikov et al., “Analytical Potentials for the Efficient Simulation of Planar and Axisymmetric Ion Mirrors,” *Journal of Analytical Chemistry* 74 (2019) 1437–1446. DOI: `10.1134/S1061934819140041`.
3. H. Stewart et al., “A Conjoined Rectilinear Collision Cell and Pulsed Extraction Ion Trap with Auxiliary DC Electrodes,” *Journal of the American Society for Mass Spectrometry* 35 (2024) 74–81. DOI: `10.1021/jasms.3c00311`.
4. H. Stewart et al., “Crowd Control of Ions in the Astral Analyzer,” ChemRxiv preprint. DOI: `10.26434/chemrxiv-2023-p6zln`.
5. H. Stewart et al., “A Multi-Reflection Time-of-Flight Analyzer with a Long Focus Lens,” ChemRxiv preprint. DOI: `10.26434/chemrxiv-2024-xl3kt`.

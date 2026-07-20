# 多极杆碰撞、冷却与扩展物理模型

> **知识卡**：`document_id=multipoles.collisions` · `version=0.1.0` · `maturity=provisional` · `role=cross_project_design_family_knowledge`

本文件定义四极杆、六极杆、八极杆中气体碰撞和冷却模型的共同知识。它不保存某个项目当前压力、电压或通过状态；这些只属于项目 `config/`、`docs/PROJECT.md` 和运行 manifest。

> **重要**
>
> 碰撞模型不能由 AI 在运行时临时搜索并自由选择。正式计算只能引用已版本化的数据集、明确的模型 ID、适用能量范围和通过验证的参考测试。实时搜索只用于发现候选知识。

## 1. 为什么碰撞必须显式建模

多极杆中的气体碰撞可能同时产生：横向和轴向动能耗散、出口束斑收缩、轴向速度降低、速度扩散、RF 微运动中断加热、触杆或反射概率变化，以及非弹性激发、解离、电荷交换、团簇和化学反应。

因此“有气体就冷却”和“低压就可忽略碰撞”都不是可靠规则。是否需要碰撞模型取决于气体数密度、截面、相对速度、器件长度、离子轨迹和目标观测量。

## 2. 气体状态与必需输入

每个气体组分 $j$ 至少需要：物种和分子质量 $M_j$；温度场 $T_j(\mathbf r)$；压力或数密度场；体流速度 $\mathbf u_{g,j}(\mathbf r)$；总、弹性、非弹性或反应截面；散射角分布；数据来源、版本、插值和外推规则。

在理想气体且局部平衡近似下：

$$
n_j(\mathbf r)=\frac{p_j(\mathbf r)}{k_{\mathrm B}T_j(\mathbf r)}.
$$

高压、强温度梯度或复杂混合物应使用项目批准的状态方程或流体解。中性粒子速度应从以局部体流速度为均值的 Maxwell–Boltzmann 分布抽样；只把中性粒子设为静止会扭曲相对能量和轴向拖曳。

## 3. 相对速度与碰撞能量

离子速度为 $\mathbf v$，抽样中性速度为 $\mathbf u$：

$$
\mathbf g=\mathbf v-\mathbf u,\qquad g=|\mathbf g|.
$$

约化质量与质心碰撞能量为：

$$
\mu_r=\frac{mM}{m+M},\qquad E_{\mathrm{rel}}=\frac12\mu_rg^2.
$$

截面查表、反应阈值和散射模型都应使用明确能量定义。实验数据若使用实验室系离子能量，导入时必须转换并保存原始定义。

## 4. 碰撞率与随机事件

对组分 $j$ 和通道 $k$，局部碰撞频率为：

$$
\nu_{jk}(\mathbf r,\mathbf v,t)
=n_j(\mathbf r)\sigma_{jk}(E_{\mathrm{rel}})g.
$$

总碰撞频率：

$$
\nu_{\mathrm{tot}}=\sum_j\sum_k\nu_{jk}.
$$

若一个时间步内 $\nu_{\mathrm{tot}}$ 可近似不变，则至少一次碰撞概率为：

$$
P_{\mathrm{coll}}=1-\exp(-\nu_{\mathrm{tot}}\Delta t).
$$

发生碰撞后，通道按 $\nu_{jk}/\nu_{\mathrm{tot}}$ 选择。若场、速度、压力或截面在步内变化明显，应使用事件驱动、null-collision 或 thinning 方法。

给定一条先验轨迹，预期碰撞数为：

$$
N_{\mathrm{coll}}
=\int_{t_0}^{t_1}\nu_{\mathrm{tot}}(\mathbf r(t),\mathbf v(t),t)\,\mathrm dt.
$$

$N_{\mathrm{coll}}\ll1$ 只能支持“碰撞可能较弱”的初筛；当关注极小尾部、峰宽或反应产额时，少量碰撞也可能重要。

## 5. 弹性二体碰撞

碰撞前质心速度为：

$$
\mathbf V_{\mathrm{cm}}
=\frac{m\mathbf v+M\mathbf u}{m+M}.
$$

在质心系中把相对速度 $\mathbf g$ 按差分截面抽样的散射角旋转为 $\mathbf g'$，弹性碰撞满足 $|\mathbf g'|=|\mathbf g|$。碰撞后：

$$
\begin{aligned}
\mathbf v'&=\mathbf V_{\mathrm{cm}}+\frac{M}{m+M}\mathbf g',\\
\mathbf u'&=\mathbf V_{\mathrm{cm}}-\frac{m}{m+M}\mathbf g'.
\end{aligned}
$$

该更新应在数值精度内守恒总动量和总动能。若气体被视为无限热浴，可丢弃 $\mathbf u'$，但仍必须用它做单次碰撞守恒测试。

> **警告**
>
> “各向同性散射”是模型假设，不是普遍事实。若差分截面强前向散射，各向同性模型会错误预测能量弛豫、角扩散和触杆概率。

## 6. 碰撞模型等级

| 等级 | 模型 | 必需输入 | 适用目的 | 不允许声称 |
|---|---|---|---|---|
| C0 | 无碰撞确定性轨迹 | 场、粒子初值 | 高真空基线、解析回归 | 气体冷却和压力效应 |
| C1 | 常截面或简化弹性 Monte Carlo | $p,T,M,\sigma$、散射假设 | 初步碰撞聚焦、能量损失趋势 | 精确能量尾和反应产额 |
| C2 | 能量相关总/差分截面、RF 相位分辨 | 版本化截面、能量域、散射模型 | 定量冷却、加热、出口能量和损失 | 未建模的非弹性通道 |
| C3 | 弹性 + 非弹性/反应通道 | 各通道截面、阈值和产物 | CID、反应池、电荷交换、团簇 | 未覆盖物种或能区的化学结论 |
| C4 | 碰撞 + 气流 + 空间电荷/化学耦合 | 压力流场、离子密度、耦合策略 | 高压接口、强离子流、复杂反应池 | 超出耦合收敛和实验校准域的结果 |

项目 mode 必须显式声明一个等级。`collision_model: disabled` 等价于 C0；不得由求解器默认阻尼节点替代。

## 7. 冷却、扩散与 RF 加热

### 7.1 自由空间冷却

在无 RF 场、无外部做功且气体为热浴时，重复弹性碰撞使离子速度分布趋向与气体温度相容的平衡状态。弛豫速度由质量比、碰撞频率和散射角分布共同决定。

### 7.2 RF 场中的微运动

局部单频场的一阶微运动速度幅值约为：

$$
v_{\mathrm{micro,amp}}
\approx\frac{|Q|E_{\mathrm{rf}}}{m\Omega}.
$$

周期平均微运动动能为：

$$
\langle K_{\mathrm{micro}}\rangle
\approx\frac{Q^2E_{\mathrm{rf}}^2}{4m\Omega^2}
=\Psi(\mathbf r).
$$

碰撞在任意 RF 相位发生，会改变瞬时速度而不立即改变电场相位。RF 驱动随后可重新注入微运动能量，部分能量转入慢运动。轴线附近场小，碰撞更接近普通热化；外层场大，可能出现加热和长能量尾。高阶多极杆中心低场区更宽，但空间电荷或入口失配把离子推到外层后，场随半径增长更快。

### 7.3 质量比与压力

离子与气体质量比影响单次能量交换和 RF 加热趋势，但不存在跨所有多极阶数、$q$、压力分布和空间气体分布使用的单一“安全质量比”。自动设计器不得只根据 $M/m$ 做二元通过/拒绝。

增加压力可能先改善聚焦和冷却，随后因轴向动能过度损失、扩散、反射或触杆而降低传输。因此优化变量应包含压力分布和停留时间，不能只最大化碰撞数。

## 8. 迁移率—扩散与 Langevin 近似

当碰撞频繁、离子接近局部热平衡且不需要逐 RF 相位碰撞能量时，可使用低场迁移率—扩散近似：

$$
\mathbf v_d=\mathbf u_g+sK\mathbf E,
$$

$$
D=\frac{Kk_{\mathrm B}T}{|Q|}.
$$

这里 $K>0$ 是标量迁移率，$s=\operatorname{sign}(Q)$；若采用带符号迁移率，必须在合同中明确另一套约定，不能与本式混用。

或使用满足涨落耗散关系的 Langevin 模型：

$$
m\,\mathrm d\mathbf v
=Q\mathbf E\,\mathrm dt
-m\gamma(\mathbf v-\mathbf u_g)\,\mathrm dt
+\sqrt{2m\gamma k_{\mathrm B}T}\,\mathrm d\mathbf W_t.
$$

这些模型通常不能直接预测 RF 相位分辨的微运动中断、非热高能尾、单次碰撞角分布、少碰撞过渡区或复杂反应网络。连续模型与 Monte Carlo 模型有重叠适用域时，应交叉验证。

## 9. 非弹性与反应碰撞

C3 模型中，每个通道至少保存：

```yaml
channel_id: n2_cid_v1
reactants:
  ion: analyte_parent
  neutral: N2
threshold_eV_cm: 4.2
cross_section_dataset: datasets/n2_cid_v1.csv
energy_range_eV_cm: [4.2, 100.0]
products:
  - ion: fragment_a
    branching_model: tabulated
energy_partition_model: phase_space_v1
extrapolation: forbidden
```

总截面应与部分截面一致；输入能量超出数据域时，默认应让使用该数据的项目门禁失败，而不是静默常数外推。反应后必须更新离子质量、电荷、身份、动量、后续截面集合、反应树和事件时间。

## 10. 空间电荷与碰撞耦合

碰撞冷却会降低离子动能并增加停留时间，可能提高局部离子密度，使空间电荷不可忽略。建议分级：

- S0：忽略空间电荷，但计算电流/密度上界；
- S1：固定或解析均场；
- S2：粒子—网格自洽迭代；
- S3：碰撞、流体和反应网络联合自洽。

开启空间电荷后，必须检查粒子数、宏粒子权重、网格、平滑、更新频率和迭代收敛。

## 11. 模型选择规则

| 条件 | 最低建议模型 |
|---|---|
| 高真空，$N_{\mathrm{coll}}$ 上界远小于 1，压力敏感度可忽略 | C0 |
| 需要判断碰撞聚焦或轴向能量损失趋势 | C1 |
| 需要出口能量、RF 加热、质量比或压力定量优化 | C2 |
| 存在解离、反应、电荷交换或团簇 | C3 |
| 压力梯度、气流和强空间电荷共同控制 | C4 |

模型升级必须同时增加输入证据和验证，而不只是增加复杂度。

## 12. Monte Carlo 碰撞轨迹算法

```text
for each particle:
    initialize state, species, RNG stream and RF phase
    while not terminated:
        evaluate basis-field superposition E(r, t)
        advance deterministic motion to next substep/event
        sample local neutral velocity
        compute relative energies and channel rates
        sample collision time/channel using MCC or null-collision
        if collision occurs:
            apply elastic scattering or reaction update
            record gas, channel, RF phase, radius and energy
        test electrode/aperture/interface/timeout events
    write immutable event history and terminal state
```

时间步或事件步必须同时解析 RF 波形、最小几何特征穿越时间、场插值变化、碰撞概率、反应阈值和边缘场快速变化。项目必须通过步长收敛，而不是硬编码“每 RF 周期 20 步”。

每个 run 保存全局种子和粒子 RNG 子流规则；不同求解器可以使用相同初始粒子表，但随机碰撞既应支持同源对照，也应有独立种子统计。失败或中断运行仍应保存 manifest 和已完成样本数。

## 13. 必须输出的观测量

| 类别 | 最小输出 |
|---|---|
| 传输 | 通过率、触杆/反射/超时比例、损失 $z$ 和电极编号 |
| 碰撞 | 每粒子碰撞数、组分、通道、碰撞半径、RF 相位 |
| 能量 | 入口/出口总动能、轴向/径向能量、分位数和高能尾 |
| 相空间 | 出口位置、速度、时间、RF 相位和协方差 |
| 冷却 | 能量或束斑随 $z$、时间和碰撞数的演化 |
| 反应 | 母/子离子产额、反应位置、反应树和能量预算 |
| 鲁棒性 | 压力、温度、截面、种子和几何误差敏感度 |

“平均能量下降”不足以证明冷却 mode 有效。验收通常还需限制传输损失、能量尾、出口束斑、停留时间和反应副产物。

## 14. 参考验证矩阵

| 测试 ID | 测试内容 | 必须验证 |
|---|---|---|
| `collision.zero_pressure_limit.v1` | $p\rightarrow0$ | 收敛到 C0 轨迹和统计 |
| `collision.single_event_conservation.v1` | 单次弹性碰撞 | 动量和动能守恒 |
| `collision.poisson_rate.v1` | 均匀气体、常速、常截面 | 碰撞数满足 Poisson 统计 |
| `collision.maxwell_sampling.v1` | 中性热速度抽样 | 均值、方差和各向同性正确 |
| `collision.free_thermalization.v1` | 无 RF、受控体系 | 长时间分布符合目标热浴行为 |
| `collision.mobility_overlap.v1` | 低场高碰撞重叠域 | MCC 与迁移率模型一致 |
| `collision.rf_cooling_heating.v1` | 扫描半径、RF、质量比 | 能表示冷却与微运动相关加热两种趋势 |
| `collision.step_convergence.v1` | 时间步或 null-collision 上界 | 传输和能量分布收敛 |
| `collision.sample_seed_convergence.v1` | 粒子数和多种子 | 均值、分位数和置信区间收敛 |
| `collision.independent_implementation.v1` | 独立实现 | 统一输入下统计一致 |

项目阈值应写入机器分析合同；理论文件只定义测试语义。

## 15. 机器合同示例

```json
{
  "model_id": "elastic_mcc.energy_dependent.v1",
  "model_level": "C2",
  "gas": {
    "species": [{
      "name": "N2",
      "mole_fraction": 1.0,
      "temperature_K": 300.0,
      "pressure_field": "data/pressure_map.vtk"
    }],
    "bulk_flow_field": "data/gas_velocity.vtk"
  },
  "cross_sections": {
    "elastic_total": "dataset:n2_elastic_total_v3",
    "differential_model": "tabulated_legendre_v1",
    "energy_range_eV_cm": [0.01, 50.0],
    "extrapolation": "forbidden"
  },
  "sampling": {
    "method": "null_collision",
    "rng": "pcg64dxsm",
    "seed": 20260720
  },
  "required_reference_tests": [
    "collision.zero_pressure_limit.v1",
    "collision.single_event_conservation.v1",
    "collision.rf_cooling_heating.v1",
    "collision.sample_seed_convergence.v1"
  ]
}
```

若项目使用该模型支持正式结论，项目门禁还应检查数据文件哈希、代码版本、压力场来源、截面不确定度，以及与结论风险相称的独立验证证据。

## 16. 与现有 RF 四极杆项目的绑定

现有项目入口为 [`projects/rf_quadrupole_collision_cooling/README.md`](../../projects/rf_quadrupole_collision_cooling/README.md)。接入本文件时遵守：

- 无碰撞 mode 必须显式绑定 C0，COMSOL 和 SIMION 都不得创建或启用碰撞/阻尼模型；
- 质量过滤参考 mode 默认先以 C0 建立解析和无碰撞基线；
- 碰撞冷却 mode 只有在气体数据、截面、模型 ID、参考测试和 Candidate 门禁齐全后才可执行；
- 旧脚本、旧几何或求解器默认阻尼不能绕过共享契约恢复为当前入口；
- 项目当前状态和开放任务仍只写 `docs/PROJECT.md`。

本次运行实际选择的 `collision_model_id`、数据集哈希和种子应写入 `run_config.json`，并由 `run_manifest.json` 冻结输出。

## 17. AI 搜索与数据引入

AI 搜索得到的碰撞截面、迁移率或反应模型入库前必须完成：

1. 固定论文、数据库版本、DOI 和许可；
2. 记录原始能量坐标、截面单位、温度和物种状态；
3. 转换为平台统一单位并保留原始列；
4. 声明插值、平滑和外推；
5. 建立数据完整性和物理边界测试；
6. 用公开或内部基准验证实现；
7. 标注不确定度和允许用途；
8. 审批后才允许项目机器配置引用。

未完成流程的数据只能标记为 `provisional`，不得用于正式报告或自动修改验收条件。

## 18. 参考资料

1. D. Gerlich, “Inhomogeneous RF Fields: A Versatile Tool for the Study of Processes with Slow Ions,” *Advances in Chemical Physics* 82, 1–176 (1992), [DOI 10.1002/9780470141397.ch1](https://doi.org/10.1002/9780470141397.ch1).
2. D. J. Douglas and J. B. French, “Collisional focusing effects in radio frequency quadrupoles,” *Journal of the American Society for Mass Spectrometry* 3, 398–408 (1992), [DOI 10.1016/1044-0305(92)87067-9](https://doi.org/10.1016/1044-0305%2892%2987067-9).
3. D. J. Douglas, “Applications of collision dynamics in quadrupole mass spectrometry,” *Journal of the American Society for Mass Spectrometry* 9, 101–113 (1998), [DOI 10.1016/S1044-0305(97)00246-8](https://doi.org/10.1016/S1044-0305%2897%2900246-8).
4. A. V. Tolmachev, H. R. Udseth, and R. D. Smith, “Radial stratification of ions as a function of mass to charge ratio in collisional cooling radio frequency multipoles used as ion guides or ion traps,” *Rapid Communications in Mass Spectrometry* 14, 1907–1913 (2000), [DOI 10.1002/1097-0231(20001030)14:20<1907::AID-RCM111>3.0.CO;2-M](https://doi.org/10.1002/1097-0231%2820001030%2914%3A20%3C1907%3A%3AAID-RCM111%3E3.0.CO%3B2-M).
5. D. J. Douglas, “Linear quadrupoles in mass spectrometry,” *Mass Spectrometry Reviews* 28, 937–960 (2009), [DOI 10.1002/mas.20249](https://doi.org/10.1002/mas.20249).

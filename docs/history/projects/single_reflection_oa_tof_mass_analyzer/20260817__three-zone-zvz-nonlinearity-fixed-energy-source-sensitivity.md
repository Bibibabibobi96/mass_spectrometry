# 三区真实PA经验z-vz非线性、能谱与横向源敏感性

DOC_STATUS: ARCHIVED_READ_ONLY

> `DOC_STATUS: ARCHIVED_READ_ONLY`

## 结论

2026-08-17在冻结三区加速器、真实SIMION PA、相同经验`z`点、相同100个有序母粒子ID及相同数值
设置下，完成四个描述性源臂的顺序分解：

1. `affine_zvz_fixed_10eV_transverse_collapsed`
2. `observed_zvz_fixed_10eV_transverse_collapsed`
3. `observed_z_vz_energy_transverse_collapsed`
4. `full_observed_6d`

每个源臂的N=1机制门均1/1到达探测器并只授权同臂N=100；四个N=100均100/100到达探测器。结果为：

| 描述性源臂 | detector | sigma / ns | direct FWHM / ns | mass R |
|---|---:|---:|---:|---:|
| `affine_zvz_fixed_10eV_transverse_collapsed` | 100/100 | `0.0919962628688373` | `0.12019462424817107` | `130335.41997` |
| `observed_zvz_fixed_10eV_transverse_collapsed` | 100/100 | `0.8197245483242594` | `2.4711425665380204` | `6339.42574` |
| `observed_z_vz_energy_transverse_collapsed` | 100/100 | `0.8197190661516853` | `2.471435672756428` | `6338.67443` |
| `full_observed_6d` | 100/100 | `0.8542897551953191` | `2.582946853863177` | `6065.03031` |

以首个固定10 eV affine臂到完整六维臂的总峰宽退化为分母，相邻步骤的顺序份额为：

| 恢复的源特征 | sigma份额 | direct FWHM份额 |
|---|---:|---:|
| observed非线性`z-vz`残差 | `95.46563%` | `95.46019%` |
| observed逐粒子能谱 | `-0.00072%` | `0.01190%` |
| observed完整横向位置与速度方向 | `4.53509%` | `4.52791%` |

能谱步骤的sigma变化极小且符号为负，不能解释为已证明的物理改善；它与FWHM的微小正变化都只能按本次
单一N=100数值实现报告。本轮最强证据是：在当前冻结三区设计内，把同一经验`z`点上的authority affine
`vz(z)`替换为逐ID observed `z-vz`，解释了约95.46%的首尾峰宽退化。后续残差审计表明其中主要是
重新affine匹配后仍存在的non-affine/stochastic scatter，而不是一个已辨识的光滑低阶非线性函数。它是
固定设计灵敏度，不是“非线性不可补偿”的结论。

## 四臂逐粒子构造

共同物种为100 amu、+1，当前源中心为
`(x_c,y_c,z_c)=(-69.01362184380704,0,-61.49423982071021) mm`，当前pulse clock为
`45.416793965641695 us`。所有位置从旧observed authority施加同一个中心平移
`Delta z=-43.06505301729918 mm`；没有把旧、当前clock差解释为连续飞行。对每个相同母ID `i`，共同
使用移植后的经验位置`z_i`，且前三臂均令`x_i=x_c`、`y_i=y_c`、`v_y,i=0`和`v_x,i>0`。

固定10 eV总速率为

```text
v_10 = sqrt(2 * 10 eV * e / (100 u)) = 4392.842636759329 m/s.
```

- `affine_zvz_fixed_10eV_transverse_collapsed`：
  `v_z,i = mu + g * (z_i-z_c)`，`v_x,i = sqrt(v_10^2-v_z,i^2)`，`E_i=10 eV`。
- `observed_zvz_fixed_10eV_transverse_collapsed`：
  `v_z,i = v_z,observed,i`，`v_x,i = sqrt(v_10^2-v_z,i^2)`，`E_i=10 eV`。
- `observed_z_vz_energy_transverse_collapsed`：保持同一observed `z_i/v_z,i/E_i/clock`，
  `v_x,i=sqrt(v_x,observed,i^2+v_y,observed,i^2)`。
- `full_observed_6d`：保持observed `x/y/z/vx/vy/vz/E`，位置只做上述共同中心平移，并采用当前clock。

前两个臂的平方根均严格可行：affine臂`max(|vz|)=281.3209302147572 m/s`、
`min(vx)=4383.825380367443 m/s`；observed固定能量臂`max(|vz|)=273.65276801299996 m/s`、
`min(vx)=4384.310731904102 m/s`。每行能量均由质量和三维速度重算，不能只把CSV能量列改成10 eV。

## 经验源统计与affine权威

100个母ID采用全宽分层选择，经验`z`统计为：mean `-61.54372926278318 mm`、sample sigma
`0.46429565161258446 mm`、范围`[-62.71094097849918,-60.486236065699174] mm`，p05/p50/p95为
`-62.32321244358918/-61.54530670669918/-60.760945592959175 mm`。

当前affine `vz(z)`不是由本轮结果拟合。令`x_i=z_i-z_c`，该authority基准及逐ID总残差为

```text
v_affine,0,i = mu_0 + k_0 * x_i
delta_i = v_observed,i - v_affine,0,i
```

它由
`config/simion_single_flight.json`中的`canonical_ideal_linear_z_vz_2p2mm_n1000`指向
`config/accelerator_phase_space_match.json`的冻结输入，参数为
`mu_0=-2.9323518410018137 m/s`、`k_0=228.80604377795845 m/s/mm`、
`z_c=-61.49423982071021 mm`。在相同经验`z`点上，`observed-affine`的`vz`残差mean为
`-10.571079245072369 m/s`、sample sigma `60.31450253683516 m/s`、RMS
`60.9361021112184 m/s`，范围`[-137.6338233765392,112.13269518528362] m/s`。因此本轮比较隔离的是
经验点上的逐ID observed-affine偏离，而不是理想等距2.2 mm样本与经验位置分布的混合差异。

为区分可重新affine匹配的部分与真正non-affine散布，在同一100个经验`z`点上对observed `vz`做
detector-blind最小二乘affine拟合，得到

```text
mu_* = -14.23113383538515 m/s
k_*  = 214.10184185468654 m/s/mm
r_nl,i = v_observed,i - [mu_* + k_* * x_i].
```

数值上`sum(r_nl)≈0`且`sum(x_i*r_nl)≈0`，即该残差与affine基函数正交；其RMS为
`59.626484577 m/s`、sample sigma `59.926871791 m/s`，范围
`[-127.8834,127.9377] m/s`。按正交均方分解，`r_nl`占原`delta`均方的`95.7478586%`，重新匹配
`mu/k`能够吸收的affine修正只占`4.2521414%`。对`r_nl`增加2至6阶多项式只捕获
`0.92%—1.14%`，不能据此宣称已发现光滑二阶、三阶或更高阶确定性曲线；当前最准确术语是
`non-affine/stochastic scatter residual`。逐ID observed CSV是精确源authority，所有多项式结果仅是
detector-blind diagnostic，不得替代逐粒子状态或成为新的源真值。

## 冻结设计、源与数值身份

- 三区layout：`three_zone_t5_primary_shaping_rings_1p4_v1`；四平面repeller/I1/I2/exit为
  `-62.992615/-59.742615/-54.642615/-42.742615 mm`，整形环为1+4布局。
- 场：`accelerator_real_three_zone_pa_real_reflectron`，真实native accelerator PA与真实reflectron；
  frontend grid为`frontend_isotropic_020_accelerator_overlay_z005`。
- 数值：oaTOF profile `oatof_formal_mesh`、trajectory quality `tqual_8`、time integration `dt160`；
  本轮没有改变PA、网格、时间步、终止条件或峰形分析口径。
- 三区resolved candidate：
  `artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20260817_181000__build__python__three-zone-t5-candidate/results/three_zone_t5_simion_candidate_resolved.json`，
  SHA-256 `CF744FD57957DF18D627F71EE2D2252A62420B343D7DD0AB1CEF493B876A7339`。
- observed authority：run
  `20260811_003000__sim__simion__rf-oatof-exact-formal-field-bridge__n1000`；manifest SHA-256
  `AC4E68D8EF7AADE2DB5759B07D7509660ED0D3CD47A1CC15AD487055279F4C37`，996行状态表SHA-256
  `4BCA44684CA3EA533775C20BA04AD34BD36FD9F31B9CB0DF08C8A1BA26583EEC`。
- affine authority：`accelerator_phase_space_match.json` SHA-256
  `6996E2E893160662B00D48AAE6743B9DD23EE3877E3922B0FF4AEF7AE99AC33F`；source profile所在
  `simion_single_flight.json` SHA-256
  `689994E36E886C12E9F852F038BCC1EF49A4C0720DA1BAB8C358AA3D54C32BCA`。
- 四行固定能量campaign：
  `three_zone_t5_real_pa_zvz_nonlinearity_fixed_10ev_n1_n100_campaign.json`，SHA-256
  `EFFC21011251E213DA706FC725FBE135D4740CC721FB0AD0E409B863926A6FD7`。

## 真实运行与manifest

| 描述性源臂与粒子数 | parent run | parent manifest SHA-256 | detector |
|---|---|---|---:|
| `affine_zvz_fixed_10eV_transverse_collapsed`, N=1 | `20260817_235941__sim__cross__three-zone-real-pa-affine-fixed10-n1__n1` | `622CF8B5EC813992334603191C86A81725A276BC4C3C81984FA01EB3D7F79807` | 1/1 |
| `observed_zvz_fixed_10eV_transverse_collapsed`, N=1 | `20260817_235942__sim__cross__three-zone-real-pa-observed-fixed10-n1__n1` | `C870CCBE06D3375967823A19B01BA51A892A1A8C9E7A4767964B8AB6DF73C4E8` | 1/1 |
| `affine_zvz_fixed_10eV_transverse_collapsed`, N=100 | `20260817_235943__sim__cross__three-zone-real-pa-affine-fixed10-n100__n100` | `4E4FD21876E6823119CE68CB03377DBFD06CB81CD4A9D4126573DA963C01ADC9` | 100/100 |
| `observed_zvz_fixed_10eV_transverse_collapsed`, N=100 | `20260817_235944__sim__cross__three-zone-real-pa-observed-fixed10-n100__n100` | `431BE6784A22DD3589B8354427F868848CA5753A3BC123FD1822B31E25A19FC4` | 100/100 |
| `observed_z_vz_energy_transverse_collapsed`, N=1 | `20260817_235954__sim__cross__three-zone-real-pa-observed-c-n1__n1` | `FF14221289B0BA17D4D61F5A12F4493E4551D668772F06B509FC3513D9D8313B` | 1/1 |
| `full_observed_6d`, N=1 | `20260817_235955__sim__cross__three-zone-real-pa-observed-d-n1__n1` | `B83DAF551E73691C11CF444AA97FE353A2C8C281BCB180D95256A407B6A7EF6C` | 1/1 |
| `observed_z_vz_energy_transverse_collapsed`, N=100 | `20260817_235956__sim__cross__three-zone-real-pa-observed-c-n100__n100` | `BCD60A842AEC16CADED7F37719136BD344E48E07C2519212F3050EFAD505578B` | 100/100 |
| `full_observed_6d`, N=100 | `20260817_235957__sim__cross__three-zone-real-pa-observed-d-n100__n100` | `A38B0600DE2C2C7B9AE83E05913C2B1CD922600E92CE2F819A0B5546FBDF1834` | 100/100 |

canonical四臂顺序比较run为
`20260817_235946__analysis__python__three-zone-source-sequential-attribution__n100`，位于integration
artifact根；manifest SHA-256为
`C7E4E7C86AA5B249F690EF1CA439B46506593CDC5EC131CB822FEA259B2C1E8E`并已通过
`verify_run_manifest`。summary SHA-256为
`7C1FE8E56A58499AEDE23C2CAF477D2F37A83B756EAF24BF86BDB842726682DA`；顺序归因JSON与逐粒子delta
CSV的SHA-256分别为`1E12114D1B20F9450661F50B92B4182D421CC2D8F5E32AEBE559FF2F9C216390`和
`7850E835B743CF74EF377F5D49AC40B99692CCF4BCAFA194F1A33EC3624827DC`。该run明确发布
`FUNCTIONAL_ONLY`、`formal_gate_passed=false`和`paired_particle_count=100`，不做阈值或资格判定。

## Focus到detector的残差放大与重映射

canonical比较同时在`accelerator_focus_forward`与`detector_crossing`读取同一100个ID。把固定10 eV
affine `z-vz`替换为固定10 eV observed `z-vz`时，focus处sigma增加`0.229571 ns`（`21.1787%`）、
direct FWHM增加`1.564822 ns`（`112.0364%`）、R降低`52.8024%`；到detector时对应变化扩大为sigma
增加`0.727728 ns`（`791.041%`）、direct FWHM增加`2.350948 ns`（`1955.951%`）、R降低
`95.1361%`。因此下游场与反射过程显著放大并重映射了源残差，detector终点份额不能直接当作源端局部
扰动强度。

逐粒子能谱步骤在focus和detector都近零。恢复完整横向状态在focus使sigma增加`1.398%`，但direct
FWHM降低`5.855%`、R增加`6.211%`；到detector则变为sigma增加`4.217%`、direct FWHM增加
`4.512%`、R降低`4.317%`。相邻步骤的排序和符号可以随下游动力学改变，故本轮顺序分解只属于已声明
checkpoint和固定臂顺序，不是顺序无关的factorial effect。

逐ID telescoping closure在detector的time `max_abs=0`，`y` closure约
`1.7763568394e-15 mm`；这证明相邻delta代数闭合到首尾差，不证明各源因素在非线性动力学中相互独立。

## 理论升级交接

本轮结果把当前固定设计下的主要峰宽敏感性定位到经验`z`点上的observed `z-vz`偏离，其中绝大部分是
重新affine匹配后仍存在的non-affine/stochastic scatter residual。下一阶段不能把
这一固定设计诊断直接写成不可补偿机理，而应回答以下问题：

1. 从observed authority建立detector-blind经验源模型，冻结经验`z`边缘分布、条件`vz|z`的可辨识均值、
   non-affine散布/异方差及其与能谱和横向状态的相关性；模型拟合和选择不得读取detector TOF、FWHM或
   命中结果，也不得因低阶多项式捕获不足而虚构光滑高阶规律。
2. 以该source model作为新的理论输入，重新联合求解三区平面位置/场强分配、整形环或等价场自由度及
   reflectron耦合条件；不得在当前affine设计上只做事后电压扫描并称为理论补偿。
3. 用相同母ID、相同源模型和预注册数值合同，严格比较`fixed-design sensitivity`与
   `recompiled compensability`。后者必须从重新编译的几何、真实PA和反射器结果获得，不能由本轮四个
   run外推。
4. 若重新编译显示可补偿，再以N=1000、网格/时间步收敛和独立统计重复量化剩余的非线性、能谱和横向
   贡献；若不可行，也必须报告设计域、约束和失败边界，不能把单个候选失败推广成普遍不可补偿。

## 声明边界

全部结论仅适用于100 Th、冻结三区设计、真实SIMION PA、单一N=100样本和当前数值profile，资格为
`FUNCTIONAL_ONLY`。本轮没有N=1000、统计重复、网格/时间步收敛、连续真实handoff、COMSOL/CAD、
工程包络、优化或Formal/Candidate晋升；不改变524 Da oaTOF Formal baseline与资产身份。

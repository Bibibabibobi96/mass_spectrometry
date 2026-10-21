# 全仓 1 / 10 / 100 ps 精度需求审查

DOC_STATUS: ARCHIVED_READ_ONLY

完成日期：2026-10-21。本记录冻结已完成的合同审查、轻量算术和静态实现风险核对，
不构成新的求解器或项目资格，也不改写此前只读调研及旧 acceptance。

## 结论与适用范围

本仓库没有一个可以统一授予所有项目的 1 ps、10 ps 或 100 ps 验收线。
时间差小不能单独证明网格、场梯度、轨迹、碰撞、事件提取或分辨率正确。
应先由项目的功能和下游接受度选择需要保持的量，再分配相应数值误差；本审查不自动批准 10 ps 或 100 ps。
方法、公式、计算器和查表仅引用[从分辨率分配时间误差预算][method]，不在此维护第二套规则。

必须区分时间戳记录间隔、输出采样间隔、内部积分步长、逐粒子终点误差、公共时间漂移和峰宽变化。
这里的 RF 相位换算只描述同一时钟的时间偏差，不把积分步长直接解释为全局时间误差。
旧的 FAIL、INCONCLUSIVE 和资格边界全部保留；新预算仅能约束后续预先冻结的比较，不能事后改写旧 acceptance。

| 对象 | 当前任务或评价重点 | 1 / 10 / 100 ps 的解释 |
|---|---|---|
| 单反射 OA-TOF | 同一 FEM 上的原生 CPT 参考一致性、直接峰宽与质量 R | 本轮旧 1 ps 门仍 FAIL；峰宽效应另报 |
| MR-TOF | 完整返回、传输、目标十万 R、源及场敏感性 | 需分别看公共漂移、相对时间和实际峰宽，不用一个最大差替代 |
| 独立正交加速器 | 完整源传输、焦面方向、局部时间聚焦及出口状态 | 1.5 ns 峰峰告警不是 1.5 ns 数值容差，也不是系统 R 门 |
| RF 四/六/八极杆 | 身份/损失、束心、束宽、角度、能量、交接相空间 | 现有家族工程合同没有 ps 接受门 |
| Ion Processor | 捕获、冷却、压缩、引出、碰撞统计及开关时序 | 毫秒驻留不决定纳秒出口宽度的精度；随机实现须单独评价 |
| 双锥串联四极杆 | 气体辅助传输、损失、出口半径/能量、驻留时间 | 先闭合事件定义、记录精度和统计误差，不能直接宣称 ps 级 |
| EI 源 / Wehnelt 电子枪 | 受治理功能求解、电离产额或收集及损失分类 | 目前没有已批准 ps 合同，功能证据尚未闭合 |

## OA-TOF：1 ps FAIL 与功能指标变化并列保留

新受控比较来自成功封存的 [165143 分析][oa-comparison]，参考 B 为 `162540__...fixed2-dp5-rtol12-dense-b`，
A2 为 `160603__...fixed2-dp5-rtol11-dense-a`；两者均 N=100，分析的 reference 命名不表示绝对真值。
下表均来自该 JSON；时间单位从 ns 换为 ps，没有重新拟合或删除粒子。

| 指标 | A2 | B / A2−B |
|---|---:|---:|
| 平均 TOF，μs | 71.3527986134833 | B：71.3527985967909 |
| 直接时间 FWHM，ps | 963.039916002 | B：962.788180090 |
| 直接质量分辨率 R | 37045.6425431 | B：37055.3309550 |
| 最大逐粒子 TOF 差，ps | — | 1.064140591 |
| TOF 差去均值 RMS，ps | — | 0.392673656 |
| TOF 差均值，ps | — | +0.016692407 |
| 直接质量 R 相对变化 | — | −0.026145798% |

[原 acceptance][oa-acceptance] 的 `tof_max_abs_ns=0.001`、`calibration_tof_pass=false`、`qualification=false` 不变。
因此不能因直接 R 变化较小就将 A2−B 改判通过，也不能把旧门的失败解释为所有功能指标均失效。
反过来，较小 R 变化只支持该冻结源、该有限样本和既定峰宽分析器下的敏感性，尚非绝对物理误差界。
B 的 Gaussian proxy 时间 FWHM 为 1429.220885 ps，与直接 962.788180 ps 明显不同；不能任意交换宽度口径。
当前诊断的峰宽与 R 来自 N100，不替代旧 N1000 Formal；[PROJECT][oa-project] 原 Formal 的合同和 GUI/CAD 身份保留。
时间零点仍是有效提取脉冲，不把多极杆此前的出生或驻留时间加入 OA 分辨率时钟。
同 FEM 的积分比较也不覆盖 FEM 场误差；当前检测窗回推有局部直线假设，不能称直接读取了原生边界停止时间。

## MR-TOF：目标余量很小，三类时间变化不能混用

[当前 PROJECT][mr-project] 的 OA 分支在固定候选电压、镜区 z=0.02 mm、4 ns/Q8 和同一 KDE 下记录：

| 源 σEy，eV | 平均 TOF，μs | KDE FWHM，ns | R | 命中 |
|---|---:|---:|---:|---:|
| 0.15 | 764.216444815 | 3.768379855 | 101398.541848 | 98/100 |
| 0.20，主条件 | 764.216316535 | 4.721538636 | 80928.736944 | 95/100 |

十万目标在约 764.216 μs 对应总 FWHM 约 3.82108 ns；用第一行精确时间计算为 3.821082224 ns。
第一组已测宽度到该上限只有约 **52.7024 ps** 差额；这不是可任意全部花在某一个求解器环节上的误差预算。
第二组主条件尚未达到十万，不能以缩小源 σ 或只展示第一组代替主条件资格。
[机器目标][mr-target] 的十万值原是镜单体初始 L0 分配，明确要求后续给源、Stripe、Prism 和数值项分配非零份额。

同一 PROJECT 报告镜网格 z=0.04→0.02 mm 时：

- 平均公共 TOF 漂移约 +94 ps；它不是峰宽增量。
- 同粒子相对高斯 ID1 的检测时间最大变化为 29.653 / 29.147 ps；高斯 ID1 不是名义源中心。
- 两组直接峰宽变化为 −5.991 / −5.196 ps；命中与损失身份不变。

这三项同时成立，没有必要选其一覆盖另外两项；100 ps 大于第一组剩余峰宽差额也不能直接推导 R 失败。
必须按权威方法区分误差的共同、差分和相关结构，并直接复核完整峰形、源母群及损失。
PROJECT 中约 0.2 ns 的初始总体工程预算不是单环节或严格误差界，不能据此豁免此处所需的局部核查。
已有数值比较、有限 N100 和局部时间步稳定性均不授予完整统计、制造、探测器或整机 Formal 资格。

## 独立加速器与电子项目

[封闭二区组件 campaign][acc-contract] 要求 100% 传输，声明 `maximum_focus_peak_to_peak_time_ns=1.5`，
且 `time_spread_exceedance=warning`；该峰峰展宽告警不是硬性 ps 数值门，也不是 FWHM 或质量分辨率目标。
它另设出口三轴能量误差各 0.05 V/q、带符号横向速度偏差 1e−4 mm/μs；完整队列与方向门仍需满足。
数值配置 Q8、最大步长 0.0005 μs=0.5 ns 不能直接当作终点误差。独立器件没有统一 TOF/R 基线；
具体仪器的装配、源到检测器时间和联合聚焦由消费者拥有，见[加速器 PROJECT][acc-project]。

[EI 源 PROJECT][ei-project] 当前仅 build-only 闭合，功能粒子结果未闭合；模型统计主电子电离碰撞，
不追踪独立重离子，不等于完整上游离子源接口。其[数值模式][ei-numerics] 声明 50 ns 区间、0.5 ns 时间间隔，
不是已测 500 ps 或更高终点精度，不能因数值模式存在就宣布功能通过。
[Wehnelt PROJECT][gun-project] 同样只有构建证据，现行功能求解未运行；随机 seed 未冻结，旧收集率不是当前结果。
其[数值模式][gun-numerics] 声明 0–40 ns、0.1 ns 间隔，既非 100 ps 接受合同，也未证明粒子计时误差。
这两项目先补 N≥100、实际输出数、收集/碰撞与未分类损失、可重复释放和 GUI Compute；再按功能需要定义时间指标。

## RF 三项目：先核对物理用途与步长的真实消费者

当前四/六/八极杆三模式基线均为 1.1 MHz、杆长 79.6 mm；最长追踪时间配置为 80 μs，不能写成平均实测飞行时间。
频率分别见[四极杆机械合同][quad-drive]、[六极杆机械合同][hex-drive]、[八极杆机械合同][oct-drive]。
家族 COMSOL 基线字段为 80 点/周期、时间细化 160；SIMION 为 40/80，另有具名后续数值档。
[功能合同][rf-functional] 要求传输率至少 0.8、比较臂传输数差为零、交接 ID 集精确相同、孔径余量为正。
[工程合同][rf-engineering] 的六项限值为束心/束宽差各 0.2 mm、方向/角宽差各 1°、均能/能散差各 0.2 eV。
TOF、时间宽度、RF 相位、发射度和尾部分布为 report-only；工程 PASS 不改变数值收敛 `DEFERRED_NOT_WAIVED`。
例如[六极杆预登记][hex-prereg] 仍无有来源的连续误差预算，不能从阈值缺失推导 100 ps 足够或必须达到 1 ps。

四极杆的接口就绪数值筛选另有[专用合同][quad-interface]：均 TOF 相对差 1%、半径 2%、发散 3%、能量 0.4%，
且身份集精确相同；该窄 workflow 的筛选门不能替代家族或整机要求，均值差还可能掩盖相反方向逐粒子误差。
[RF+DC 质量过滤][quad-filter] 则评价质量扫描的中心透过率、端点抑制和对比度；跨求解器数值容差尚未冻结。
即使 TOF 足够稳定，也须另外检查质量响应、稳定边界、相空间和损失，不能只按一个时间指标资格化。

## RF 时间偏差的量级换算

下表仅计算同一 RF 参考时钟的 `δφ=360 f δt`；δt 是时间偏差，不是假定每步积分误差。

| 工作点 | 周期，ns | 1 ps，° | 10 ps，° | 100 ps，° |
|---|---:|---:|---:|---:|
| 四/六/八极杆 1.1 MHz | 909.090909 | 0.000396 | 0.00396 | 0.0396 |
| IP 3.7 MHz | 270.270270 | 0.001332 | 0.01332 | 0.1332 |
| 双锥标称 570 kHz | 1754.385965 | 0.0002052 | 0.002052 | 0.02052 |
| 双锥下端 550 kHz | 1818.181818 | 0.000198 | 0.00198 | 0.0198 |
| 双锥上端 590 kHz | 1694.915254 | 0.0002124 | 0.002124 | 0.02124 |

相位偏差小不自动保证碰撞后轨迹、接受边缘或长程微运动相同；RF 端点尚未扫描，表格不是新运行结果。
释放时间与 instrument clock 必须保持同一参考；不能把出生时刻偏移和净飞行时间相互替换。

## IP 与双锥：统计、开关和事件定义优先

IP [物理合同][ip-baseline] 为 3.7 MHz，capture/transfer/lift 为 1500/6000/7500 μs，终止上限 7520 μs。
[数值合同][ip-numerics] 的 10 ns cap、每周期至少 27 步、HS1 每平均自由程 20 步之外，
[活动 runtime][ip-runtime] 还按碰撞及阶段边界缩步；普通 1 μs / 提取 5 ns 的记录间隔不能当作内部步长。
[验收合同][ip-acceptance] 为捕获/引出≥90%、捕获均能≤1 eV、引出前轴向 σ≤2 mm、引出均能3500–4500 eV。
[IP PROJECT][ip-project] 封存源出口 σt=3.179094 ns；100 ps 约其 3.15%，这只是量纲对照而非合格结论。
共同时间偏移不改变束宽，相关误差也不能简单相加；毫秒驻留使均匀 ps 步长代价极大，但不决定最终 ns 束宽精度。
应分别检查开关回调/相位、全母群传输、能量/相空间、碰撞统计和多种子重复；截面尚未标定，完整收敛未闭合。

双锥两级均为 570 kHz、每组对地峰值 300 V、SDS 碰撞；[物理合同][cone-science] 与[数值合同][cone-numerics] 分开。
成功 run 的[58 个终态记录][cone-csv] 时间为468.026316–2481.2334 μs，均值668.941725466 μs，追踪上限3000 μs。
这是越过观察面后的回调记录，不是已插值平面 TOF；1 μs 轨迹采样也不等于内部积分步。
[PROJECT][cone-project] 已记录相同场/源/RF/PA 配置曾产生58/100与60/100；seed 不证明 Fly2+SDS 逐粒子位复现。
因此单独要求碰撞轨迹逐 ID 在 ps 内相同，不能替代传输、损失、能量、驻留分布与统计不确定性审查。
当前没有已批准的 ps 接受门；气流网格、稳定化和空包络近似的物理限制也不能由轨迹计时精度补偿。

## 三项静态实现风险及原生验证边界

1. 家族 COMSOL [作者][family-author] 由 `T/rf_steps_per_period` 算 dt，仅写 Transient.tlist，随后创建自动求解序列。
   当前函数未显式设置/回读活动 tsteps、内部 maxstep 或 rtol；80→160 首先只能证明输出表加密。
   是否默认 Strict、内部步是否随之变化，需原生回读；本次没有启动 COMSOL，不能据字段名认定内部最大步已二分。
   SIMION [RF kernel][rf-kernel] 则明确生成 T/N cap，二者相同字段名不能作为相同数值精度的证明。
2. 双锥 `maximum_step_us=0.0125` 尚未接入已检查的生产链。补查不只做字符串搜索：
   [prepare.ps1][cone-prepare-ps]→[prepare.py][cone-prepare] 显式构造 Lua 字段，没有该值；
   [生产 Fly 入口][cone-runner] 直接调用 SIMION，只传 Q、粒子/Program 和 SDS 可调项，没有通用步长消费者。
   公共 [IOB 重绑器][iob-builder] 只绑定 PA/Program/FLY2，不读取数值 JSON；[runtime][cone-runtime] 只取两级 RF cap。
   可静态确认此字段未在这条链强制12.5 ns；RF cap约21.93 ns，SDS/原生引擎可能再缩步，实际步序列未核验。
3. 双锥 runtime 的终止判断在越过面后执行，未做穿越插值，且 CSV 使用 `%.9g`。
   100–999 μs 记录量化间隔约1 ps，1000–3000 μs约10 ps，后者单次舍入可达约5 ps。
   这限制由已有 CSV 可证明的精度；不能把多位小数或成功退出当作1 ps事件精度，也不能反推实际积分误差。

以上均为静态证据，不是新商业复验，不推翻既有原型/功能结论，也未实施修复。
main HEAD 为 `7d4d37376a9f4b5be7d87ea6c2a7ec56f6cf68f1`；下列路径及双锥 workflow 的 scoped status/diff 均为空。
因此这些被审文件与该提交一致；这不表示整个 main 干净，也不表示其它分支或旧 run 使用相同字节。

| 文件标识 | 本次 main 文件 SHA-256 |
|---|---|
| family-author | 31EF2C922FD00DE8291C8D8557DC06E5A7C01712EAD8CB22C56D280F08907F6A |
| rf-kernel | A07C1B19614242610D2087694C72DCF22ED3670BBBED5FD4A053D533F0E319EB |
| iob-builder | E2F613ED571629FD20A3084361D7EEBD3028B97171663DC068A5661042BA1EDB |
| cone-numerics | 7F99F8F692DC03960AD12CEDEB8D93D1A4C376D47AC2618B979E1E6714237AAF |
| cone-prepare | 210B08C38C24D25DEB76C0F2152027FCAF64BBBD767F6740EC473BE4F5ECBB6B |
| cone-runtime | 9BB311BC0C89CBE3E4EB54AD41218D2637222778967EB69606021A70E7E18A65 |
| cone-prepare-ps | 65F73917588133CCBC62C17C2166E0313D63D0E5466C97AB0189C7F6D9630E9F |
| cone-runner | C6ECE5BC9F828BEBF88B92F9894B721B70BFF3E3D659792DB33256F81306F18B |

后续各项目按权威方法冻结功能预算与唯一变量；优先核实实际配置、事件和输出，再进行相称受控收敛。
固定完整母群与损失，统计重复和确定性数值对照分开；新预算不改写旧 FAIL，不自动开展大型模型或参数扫描。
本稿只发布需求审查，不把未完成的原生设置核验、统计资格或全局误差预算称为已关闭。

## 出处

[method]: ../../docs/VALIDATION_METHODS.md#从分辨率分配时间误差预算
[oa-comparison]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165143__analysis__python__oatof-cpt-comparison/results/comparison.json
[oa-acceptance]: ../../../artifacts/projects/single_reflection_oa_tof_mass_analyzer/runs/20261021_165143__analysis__python__oatof-cpt-comparison/results/acceptance.json
[oa-project]: ../../projects/single_reflection_oa_tof_mass_analyzer/docs/PROJECT.md "审查定位行号：108"
[mr-project]: ../../projects/parallel_mirror_dual_stripe_mr_tof/docs/PROJECT.md "审查定位行号：266"
[mr-target]: ../../projects/parallel_mirror_dual_stripe_mr_tof/config/simion_candidate_two_zone.json "审查定位行号：133"
[acc-contract]: ../../projects/orthogonal_accelerator/config/two_zone_component_focus_campaign.json "审查定位行号：68"
[acc-project]: ../../projects/orthogonal_accelerator/docs/PROJECT.md "审查定位行号：63"
[ei-project]: ../../projects/apertured_tube_electron_impact_ion_source/docs/PROJECT.md "审查定位行号：13"
[ei-numerics]: ../../projects/apertured_tube_electron_impact_ion_source/config/numerical_modes.json "审查定位行号：27"
[gun-project]: ../../projects/transverse_helical_filament_wehnelt_electron_gun/docs/PROJECT.md "审查定位行号：26"
[gun-numerics]: ../../projects/transverse_helical_filament_wehnelt_electron_gun/config/numerical_modes.json "审查定位行号：44"
[quad-drive]: ../../projects/rf_quadrupole_ion_optics/config/requests/baseline.json "审查定位行号：63"
[hex-drive]: ../../projects/rf_hexapole_ion_optics/config/requests/mechanical_base.json "审查定位行号：63"
[oct-drive]: ../../projects/rf_octupole_ion_optics/config/requests/mechanical_base.json "审查定位行号：63"
[rf-functional]: ../../common/multipole/functional_transport_acceptance.json "审查定位行号：13"
[rf-engineering]: ../../common/multipole/engineering_progression_acceptance.json "审查定位行号：29"
[hex-prereg]: ../../projects/rf_hexapole_ion_optics/config/qualification/n100_convergence_preregistration.json "审查定位行号：127"
[quad-interface]: ../../projects/rf_quadrupole_ion_optics/config/same_solver_numerical_convergence.json "审查定位行号：25"
[quad-filter]: ../../projects/rf_quadrupole_ion_optics/config/modes/mass_filter_reference.json "审查定位行号：48"
[ip-baseline]: ../../projects/dual_pressure_rectilinear_ion_processor/config/baseline.json "审查定位行号：17"
[ip-numerics]: ../../projects/dual_pressure_rectilinear_ion_processor/config/numerics.json "审查定位行号：3"
[ip-runtime]: ../../projects/dual_pressure_rectilinear_ion_processor/simion/runtime.lua "审查定位行号：224"
[ip-acceptance]: ../../projects/dual_pressure_rectilinear_ion_processor/config/acceptance.json "审查定位行号：3"
[ip-project]: ../../projects/dual_pressure_rectilinear_ion_processor/docs/PROJECT.md "审查定位行号：73"
[cone-science]: ../../projects/dual_cone_tandem_quadrupole_ion_interface/config/ion_transport_science.json "审查定位行号：8"
[cone-numerics]: ../../projects/dual_cone_tandem_quadrupole_ion_interface/config/simion_solver_numerics.json "审查定位行号：20"
[cone-csv]: ../../../artifacts/projects/dual_cone_tandem_quadrupole_ion_interface/runs/20260914_162400__sim__simion__dual-cone-comsol-field-n100/results/terminal_plane_transmitted.csv
[cone-project]: ../../projects/dual_cone_tandem_quadrupole_ion_interface/docs/PROJECT.md "审查定位行号：116"
[family-author]: ../../common/multipole/solve_finite_3d_transport.m "审查定位行号：1152"
[rf-kernel]: ../../common/multipole/simion_rf_drive.lua "审查定位行号：84"
[cone-prepare-ps]: ../../projects/dual_cone_tandem_quadrupole_ion_interface/workflows/gas_assisted_transport/prepare.ps1 "审查定位行号：14"
[cone-prepare]: ../../projects/dual_cone_tandem_quadrupole_ion_interface/simion/prepare.py "审查定位行号：139"
[cone-runner]: ../../projects/dual_cone_tandem_quadrupole_ion_interface/workflows/gas_assisted_transport/run_gas_field_prototype.ps1 "审查定位行号：105"
[iob-builder]: ../../common/multipole/build_simion_runtime_iob.lua "审查定位行号：4"
[cone-runtime]: ../../projects/dual_cone_tandem_quadrupole_ion_interface/simion/programs/gas_assisted_transport.lua "审查定位行号：58"

# Paper 1 C3_J3：真实场局部可微性合同

> `STATUS: N=1 FUNCTIONAL GATE PASSED / N=100 REAL-PA PLATFORM COMPLETE / INDEPENDENT AXIS REFERENCE PENDING`

C3_J3只检验一个问题：C2_J3中理想轴向的三区局部控制方向，经过真实PA、真实边缘场和完整事件分类后，是否仍可在一个有限信赖域内定义稳定的一阶响应。它不恢复失败的J2比较，也不检验峰宽、传输率、锁定预测或多质量普适性。

## 冻结输入与设计

- 基准只能是已绑定的三栅Candidate；旧T5编译器继续作为该基准的历史适配器，不改变其语义。
- `three_zone_solver_free_funnel_v1`保留其原始哈希绑定，不能在扩展轴向状态oracle后继续执行；当前可执行理论合同为v2。旧T5 Candidate仍是历史基准，若要把它用于新的C3 run，必须单独绑定其原始receipt与本次C3物理请求，不能假称由v2重编译。
- 新的`CandidateControlRequest`把加速器电压、grid2/exit几何和反射器两项控制的扰动、绝对边界与`-2h,-h,0,+h,+2h`一次性冻结。它不读取探测器结果，也不选择“最好”的扰动。
- 请求必须显式给出从C2_J3抽象方向到物理电极方向的映射；不得把理想`Γ3`系数直接当作电压。
- 该映射现由`paper1_c3_j3_mapping.py`逐点重推：它要求C2的improve/zero/worsen是对称方向，并把zero点逐项绑定到冻结T5 Candidate。`paper1_c3_j3_publish.py`已将S1五个点原子发布为`20260826_023000__build__python__paper1-c3-j3-s1-candidates`；仍须由integration把每一个派生Candidate编译为独立PA/IOB后才可启动N=1。
- 每一候选重新生成PA，并保存完整母cohort的命中、撞击、损失和事件序列。不得只以共同命中交集计算导数或峰宽。
- OA时钟只用每一冻结layout的`pulse_effective_time_us`；不再进行时间窗扫选。

## 分两步门槛

1. N=1贯通：五个点均能构建、运行、记录grid2/exit/reflectron/detector事件和完整数值身份。失败即`FAIL_STOP`，不得把缺失事件当作零导数。
2. N=100步长平台：以同一冻结100离子执行cohort完成五点。该cohort是按源粒子ID顺序取得的前100个实际传输terminal handoff，不读取探测器结果；完整1000离子母cohort及上游损失仍为分母。拟合`+h/-h`与`+2h/-2h`的中心差分，并与独立导出轴场积分器比较。每个可比较方向的相对导数偏差必须不超过5%；五点事件拓扑和母cohort损失分类必须稳定。

独立参考的每一点必须通过唯一 single-flight 入口以`BuildOnly + ProgramAxisFieldExport`建立新的 immutable
field-only run；它必须绑定与对应真实PA点逐字节相同的 Candidate，使用相同有效脉冲时刻，并输出
`repeller → grid2`的五实例 Workbench 总轴场。积分器只读取同一真实PA点、同一粒子的
`pre_pulse_state(z,v_z)`并积分到该点记录的共同`local_accelerator_exit`面。它以
`dt=1e-4, 5e-5, 2.5e-5 µs`重算中心导数；最细两档相对差必须不超过1%，否则独立参考未收敛，阶段只能
`INCONCLUSIVE_REVISE`。历史上缺少 run-local frontend/overlay placement 重放的导出即使产生CSV也不具备
这一身份和数值对照条件，保留为失败排错证据，不得复用。

N=1只允许使用`terminal_handoff_smoke_source_particle_id`明确登记的一个、已实际传输的上游粒子；运行器仍保留完整母cohort的上游损失记录，并将该粒子映射为SIMION粒子1。它只是构建、时钟和事件序列的功能烟雾测试，禁止输出或解释峰宽、传输率、导数、排序或任何性能指标。

## 已完成的 N=1 功能门槛

2026-08-26，S1的五个预注册物理点`-2h,-h,0,+h,+2h`均以
`multipole_handoff_ballistic_centroid_v1`解析的固定脉冲时刻`45.56495820366112 µs`完成真实PA单飞。
每个点都保留1000离子母分母、明确的上游粒子ID 1、独立PA身份、完整事件链及成功的父/子manifest；
五点均为`1 → grid1 → intermediate2 → accelerator exit → reflectron → detector`，检测器`1/1`。
这只关闭N=1贯通门槛：它既不比较五点TOF，也不支持导数、峰宽、传输或J3主张。C3仍须完成同一五点的
N=100中心差分、事件拓扑稳定性和独立轴场积分器比较后才能形成阶段结论。

N=100的正式campaign是[`paper1_c3_j3_s1_fixed_pulse_derivative_n100.json`](../../../../../integrations/rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer/config/explorations/paper1_c3_j3_s1_fixed_pulse_derivative_n100.json)。其执行cohort由`first_n_transmitted_terminal_handoffs_in_source_particle_id_order`唯一指定，ID序列哈希已冻结；五点共享现有`multipole_handoff_ballistic_centroid_v1`脉冲计划，不含时间窗扫描。

首次`−2h` N=100运行（`20260826_081000__sim__cross__paper1-c3-j3-s1-fixed-pulse-derivative-m2__n100`）的原始三批飞行与checkpoint已完成，但在空间图后处理时被错误要求存在上游source-region diagnostic 而失败。terminal-handoff continuation 的合法起点没有该checkpoint，因此这不是场、粒子事件或物理`FAIL_STOP`；原run按失败证据保留。修复后的重跑必须使用新的run ID，且仍使用同一五点、cohort、固定pulse与母cohort分母。

五点N=100的当前闭合状态是：`−2h`以`20260826_082000__sim__simion__rf-oatof-single-flight-gap0__n100__r02`成功，`−h`的原始N=100行因一个已损坏的前端PA cache generation而在飞行前失败，保留为非物理失败证据；`−h`以`20260826_083000__sim__simion__rf-oatof-single-flight-gap0__n100__r02`重建并重新校验缓存后成功，`0,+h,+2h`三个原登记行也均成功。五点均为100个固定source ID启动、98个在固定pulse时刻合格且98个完整到达探测器，所有登记的下游事件均为98。

独立轴场积分器只能重算从`pre_pulse_state`到`local_accelerator_exit`的传播，不能与完整 detector TOF 混合比较。因此配对分析器也按同一段计算：`±h`与`±2h`中心差分均值分别为`1.5042704087e-4`与`1.5042704087e-4 ns/h`，步长平台相对误差`1.1568e-11`，98个共同粒子的事件拓扑不变。该结果只证明真实PA局部差分和事件拓扑稳定；独立导出轴场积分器尚未提供同段参考导数，因此当前机器结论仍为`INCONCLUSIVE_REVISE`，不得进入C4。

## 结论格式

唯一结论为`PASS_CONTINUE`、`FAIL_STOP`或`INCONCLUSIVE_REVISE`，并连同`stage_contract.md`、`stage_manifest.json`、`stage_report.md/json`、`stage_conclusion.md`发布到C3_J3 artifact目录。`PASS_CONTINUE`只授权C4_J3的锁定三维预测设计；它不支持J2、FWHM、传输、结构优越性、工程可制造性或Formal主张。
